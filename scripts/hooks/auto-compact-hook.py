import datetime
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys

sys.dont_write_bytecode = True

DEFAULT_HARNESS_ROOT = str(pathlib.Path(__file__).resolve().parent.parent.parent)
HARNESS_ROOT = pathlib.Path(os.environ.get('GEMINI_HARNESS_ROOT', DEFAULT_HARNESS_ROOT))
_CONFIG_DIR = HARNESS_ROOT / 'Config'
if str(_CONFIG_DIR) not in sys.path:
    sys.path.insert(0, str(_CONFIG_DIR))
try:
    import config_loader as _cfg_loader
    HARNESS_CFG = _cfg_loader.load_config(str(HARNESS_ROOT))
except Exception:
    HARNESS_CFG = {}

WARN_TOKENS = int(os.environ.get('AUTO_COMPACT_WARN_TOKENS', '300000'))
TRIGGER_TOKENS = int(os.environ.get('AUTO_COMPACT_TRIGGER_TOKENS', '400000'))
EOF_COMPACT_TOKENS = int(os.environ.get('AUTO_COMPACT_EOF_TOKENS', '150000'))
COOLDOWN_SECONDS = int(os.environ.get('AUTO_COMPACT_COOLDOWN_SECONDS', '180'))


def cfg_path(section: str, key: str, fallback: pathlib.Path) -> pathlib.Path:
    v = HARNESS_CFG.get(section, {}).get(key, '')
    return pathlib.Path(v) if v else fallback

EOF_RE = re.compile(r'unexpected\s+eof|stream\s+reading\s+error|\beof\b|stream\s+closed', re.IGNORECASE)

BREAKDOWN_DIRECTIVE = (
    'Break down the remaining task into smaller, decoupled pieces, run a brief planning pass, '
    'and write a concise Markdown plan file (e.g. scratch/BREAKDOWN_PLAN.md) before resuming execution '
    'so each turn stays small and avoids another EOF.'
)

EOF_RESUME_PROMPT = (
    'EOF recovery: context has been compacted. Now break down the remaining task into smaller pieces, '
    'do a planning pass, and write a brief Markdown plan file before continuing.'
)


def load_check_module():
    mod_path = pathlib.Path(__file__).resolve().parent / 'check-context.py'
    spec = importlib.util.spec_from_file_location('check_context_mod', mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def trace_log(hroot: pathlib.Path, msg: str):
    try:
        lp = cfg_path('hooks', 'trace_log', hroot / 'logs' / 'hook_trace.log')
        lp.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with lp.open('a', encoding='utf-8') as f:
            f.write(f'{ts} {msg}\n')
    except Exception:
        pass


def load_state(path: pathlib.Path) -> dict:
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding='utf-8-sig'))
    except Exception:
        pass
    return {}


def save_state(path: pathlib.Path, data: dict):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        pass


def compact_request_path(hroot: pathlib.Path) -> pathlib.Path:
    return cfg_path('compact', 'request_file', hroot / 'tmp' / 'compact_request.json')


def compact_processing_active(hroot: pathlib.Path) -> bool:
    req_p = compact_request_path(hroot)
    try:
        for p in req_p.parent.glob(req_p.name + '.processing.*'):
            if p.is_file():
                return True
    except Exception:
        pass
    return False


def compact_in_flight(hroot: pathlib.Path) -> bool:
    return compact_request_path(hroot).is_file() or compact_processing_active(hroot)


def mark_compact_request_ready(hroot: pathlib.Path) -> bool:
    req_file = compact_request_path(hroot)
    if not req_file.is_file() or compact_processing_active(hroot):
        return False
    try:
        data = json.loads(req_file.read_text(encoding='utf-8-sig'))
        if not isinstance(data, dict):
            return False
        data['dispatch_ready'] = True
        data['stopped_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        req_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        return True
    except Exception:
        return False


def write_ready_compact_request(
    hroot: pathlib.Path,
    conv_id: str,
    transcript_path: str,
    tokens: int,
    reason: str,
    resume_prompt: str,
) -> bool:
    req_file = compact_request_path(hroot)
    try:
        req_file.parent.mkdir(parents=True, exist_ok=True)
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        req_id = 'hookcmp-' + now_utc.strftime('%Y%m%d_%H%M%S')
        payload = {
            'request_id': req_id,
            'conversation_id': conv_id,
            'transcript_path': transcript_path,
            'command': '/compact',
            'resume_prompt': resume_prompt,
            'reason': reason,
            'current_tokens': tokens,
            'delay_seconds': 2,
            'enter_count': 1,
            'char_delay_ms': 0,
            'dispatch_ready': True,
            'created_at': now_utc.isoformat(),
            'stopped_at': now_utc.isoformat(),
        }
        req_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        return True
    except Exception:
        return False


def clear_eof_signal(hroot: pathlib.Path):
    try:
        p = cfg_path('watchdog', 'eof_signal_file', hroot / 'tmp' / 'eof_signal.json')
        if p.is_file():
            p.unlink()
    except Exception:
        pass


def make_system_msg(text: str) -> dict:
    return {'injectSteps': [{'systemMessage': {'systemMessage': text}}]}


def handle_pre_invocation(payload: dict, ctx: dict, cstate: dict, hroot: pathlib.Path) -> dict:
    tokens = int(ctx.get('current_tokens', 0))
    cp_count = int(ctx.get('checkpoint_count', 0))
    steps = int(ctx.get('steps_since_compact', 0))
    cooldown = int(ctx.get('cooldown_remaining_seconds', 0))

    # 1. Post-EOF compaction completed -> Step 2: remind model to break down & write brief .md plan
    pending_cp = cstate.get('pending_eof_breakdown_after_cp')
    if pending_cp is not None and cp_count > int(pending_cp):
        cstate.pop('pending_eof_breakdown_after_cp', None)
        clear_eof_signal(hroot)
        return make_system_msg(
            f'[EOF RECOVERY - STEP 2] Compaction after unexpected EOF is complete (now {tokens:,} tokens). '
            + BREAKDOWN_DIRECTIVE
        )

    # 2. Fresh EOF detected via transcript or watchdog eof_signal.json
    eof_key = ''
    if ctx.get('watchdog_eof_active'):
        eof_key = 'wd:' + str(ctx.get('watchdog_eof_id', ''))
    elif ctx.get('last_eof_step_idx', -1) >= 0:
        eof_key = f'tr:{cp_count}:{ctx["last_eof_step_idx"]}'

    if eof_key and cstate.get('last_eof_key') != eof_key:
        cstate['last_eof_key'] = eof_key
        if tokens < EOF_COMPACT_TOKENS:
            clear_eof_signal(hroot)
            return make_system_msg(
                f'[EOF RECOVERY - BREAKDOWN ONLY] Unexpected EOF detected at {tokens:,} tokens '
                f'(< {EOF_COMPACT_TOKENS:,}; do NOT compact). ' + BREAKDOWN_DIRECTIVE
            )
        elif cooldown == 0:
            cstate['pending_eof_breakdown_after_cp'] = cp_count
            clear_eof_signal(hroot)
            return make_system_msg(
                f'[EOF RECOVERY - COMPACT THEN BREAKDOWN] Unexpected EOF detected at {tokens:,} tokens '
                f'(>= {EOF_COMPACT_TOKENS:,}). Step 1: Save current progress and immediately execute the '
                f'auto-compact skill, then end your turn. Step 2 (after compaction): '
                + BREAKDOWN_DIRECTIVE
            )

    # 3. Normal token bands (<300k silent; 300k-400k throttled advisory; >=400k mandatory)
    if tokens < WARN_TOKENS or cooldown > 0 or compact_in_flight(hroot):
        return {}

    if tokens >= TRIGGER_TOKENS:
        last_step = int(cstate.get('last_urgent_step', -999))
        if steps - last_step >= 2 or cstate.get('last_urgent_cp') != cp_count:
            cstate['last_urgent_step'] = steps
            cstate['last_urgent_cp'] = cp_count
            return make_system_msg(
                f'[AUTO-COMPACT MANDATORY] Context reached {tokens:,} tokens (>= {TRIGGER_TOKENS:,} hard limit). '
                'Finish the current atomic write, update your disk checkpoint, immediately run the auto-compact '
                'skill, and end your turn.'
            )
        return {}

    # 300k <= tokens < 400k
    last_warn_step = int(cstate.get('last_warn_step', -999))
    if steps - last_warn_step >= 8 or cstate.get('last_warn_cp') != cp_count:
        cstate['last_warn_step'] = steps
        cstate['last_warn_cp'] = cp_count
        return make_system_msg(
            f'[AUTO-COMPACT ADVISORY] Context is {tokens:,} tokens ({WARN_TOKENS:,}-{TRIGGER_TOKENS:,} band). '
            'Complete the current milestone, persist checkpoint, then run the auto-compact skill.'
        )
    return {}


def handle_stop(payload: dict, ctx: dict, cstate: dict, hroot: pathlib.Path) -> dict:
    # If a compact request is queued, stamp dispatch_ready=True for host watchdog and allow exit cleanly
    req_file = compact_request_path(hroot)
    if req_file.is_file():
        if os.environ.get('AUTO_COMPACT_HOOK_DRY_RUN') != '1':
            ok = mark_compact_request_ready(hroot)
            trace_log(hroot, f'Stop saw compact_request.json -> mark_compact_request_ready={ok}')
        else:
            mark_compact_request_ready(hroot)
            cstate['dry_run_dispatched_pending'] = True
        return {'decision': 'allow'}
    if compact_processing_active(hroot):
        trace_log(hroot, 'Stop saw compact_processing_active -> allow')
        return {'decision': 'allow'}

    tokens = int(ctx.get('current_tokens', 0))
    cp_count = int(ctx.get('checkpoint_count', 0))
    cooldown = int(ctx.get('cooldown_remaining_seconds', 0))
    term_reason = str(payload.get('terminationReason', ''))
    err_text = str(payload.get('error', ''))
    cont_active = bool(payload.get('continuationActive', False))
    conv_id = str(payload.get('conversationId') or ctx.get('conversation_id', ''))
    tpath = str(payload.get('transcriptPath') or ctx.get('transcript_path', ''))

    # 1. Terminal EOF error on Stop
    is_eof_stop = (term_reason == 'ERROR' and bool(EOF_RE.search(err_text)))
    if is_eof_stop:
        eof_key = f'stop:{cp_count}:{ctx.get("total_steps", 0)}'
        if cstate.get('last_stop_eof_key') != eof_key:
            cstate['last_stop_eof_key'] = eof_key
            if tokens < EOF_COMPACT_TOKENS:
                if not cont_active:
                    clear_eof_signal(hroot)
                    return {
                        'decision': 'continue',
                        'reason': (
                            f'[EOF RECOVERY - BREAKDOWN ONLY] Turn ended with unexpected EOF at {tokens:,} tokens '
                            f'(< {EOF_COMPACT_TOKENS:,}; skip compaction). ' + BREAKDOWN_DIRECTIVE
                        ),
                    }
            elif cooldown == 0:
                cstate['pending_eof_breakdown_after_cp'] = cp_count
                clear_eof_signal(hroot)
                if os.environ.get('AUTO_COMPACT_HOOK_DRY_RUN') != '1':
                    ok = write_ready_compact_request(
                        hroot, conv_id, tpath, tokens, 'EOF stop hook (>=150k)', EOF_RESUME_PROMPT
                    )
                    trace_log(hroot, f'Stop EOF >=150k -> write_ready_compact_request={ok}')
                else:
                    cstate['dry_run_spawned_compact'] = {
                        'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        'tokens': tokens,
                        'resume_prompt': EOF_RESUME_PROMPT,
                    }
                return {'decision': 'allow'}

    # 2. Option A hard guardrail: >= 400k and agent stopped normally without compacting
    if (
        term_reason == 'NO_TOOL_CALL'
        and tokens >= TRIGGER_TOKENS
        and cooldown == 0
        and not cont_active
        and cstate.get('last_stop_pullback_cp') != cp_count
    ):
        cstate['last_stop_pullback_cp'] = cp_count
        return {
            'decision': 'continue',
            'reason': (
                f'[AUTO-COMPACT MANDATORY GUARD] Context is {tokens:,} tokens (>= {TRIGGER_TOKENS:,} hard limit) '
                'and compaction was not executed before ending the turn. Persist any pending state to a disk '
                'checkpoint and execute the auto-compact skill now, then end your turn.'
            ),
        }

    return {'decision': 'allow'}


def main():
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        event = str(payload.get('hookEventName', ''))
        conv_id = str(payload.get('conversationId', ''))
        tpath = str(payload.get('transcriptPath', ''))

        chk = load_check_module()
        ctx = chk.analyze_context(
            conversation_id=conv_id,
            transcript=tpath,
            warn_tokens=WARN_TOKENS,
            trigger_tokens=TRIGGER_TOKENS,
            eof_compact_tokens=EOF_COMPACT_TOKENS,
            cooldown_seconds=COOLDOWN_SECONDS,
            harness_root=str(HARNESS_ROOT),
        )
        if not ctx.get('ok'):
            print('{}')
            return

        state_file = cfg_path('hooks', 'state_file', HARNESS_ROOT / 'logs' / 'hook_state.json')
        all_state = load_state(state_file)
        cid_key = conv_id or ctx.get('conversation_id', 'default')
        cstate = all_state.get(cid_key, {})

        if event == 'PreInvocation':
            out = handle_pre_invocation(payload, ctx, cstate, HARNESS_ROOT)
        elif event == 'Stop':
            out = handle_stop(payload, ctx, cstate, HARNESS_ROOT)
        else:
            out = {}

        all_state[cid_key] = cstate
        save_state(state_file, all_state)
        trace_log(
            HARNESS_ROOT,
            f'event={event} conv={cid_key} tokens={ctx.get("current_tokens")} '
            f'term={payload.get("terminationReason", "")} out={json.dumps(out, ensure_ascii=False)}',
        )
        print(json.dumps(out, ensure_ascii=False))
    except Exception as exc:
        trace_log(HARNESS_ROOT, f'ERROR {type(exc).__name__}: {exc}')
        # Always fail open so hook never blocks Antigravity
        print('{}')


if __name__ == '__main__':
    main()
