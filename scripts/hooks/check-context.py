import argparse
import datetime
import json
import os
import pathlib
import re
import sys

EOF_RE = re.compile(r'unexpected\s+eof|stream\s+reading\s+error|\beof\b|stream\s+closed', re.IGNORECASE)
DEFAULT_HARNESS_ROOT = str(pathlib.Path(__file__).resolve().parent.parent.parent)
_CONFIG_DIR = pathlib.Path(DEFAULT_HARNESS_ROOT) / 'Config'
if str(_CONFIG_DIR) not in sys.path:
    sys.path.insert(0, str(_CONFIG_DIR))
try:
    import config_loader as _cfg_loader
except Exception:
    _cfg_loader = None


def _load_cfg(harness_root: str = DEFAULT_HARNESS_ROOT) -> dict:
    if _cfg_loader:
        try:
            return _cfg_loader.load_config(harness_root)
        except Exception:
            pass
    return {}


def parse_iso(ts: str):
    if not ts:
        return None
    try:
        if ts.endswith('Z'):
            ts = ts[:-1] + '+00:00'
        return datetime.datetime.fromisoformat(ts)
    except Exception:
        return None


def find_transcript(conversation_id: str, explicit_path: str, harness_root: str = DEFAULT_HARNESS_ROOT):
    if explicit_path:
        p = pathlib.Path(explicit_path)
        return p if p.is_file() else None
    cfg = _load_cfg(harness_root)
    brain_str = cfg.get('antigravity', {}).get('brain_dir', '')
    brain = pathlib.Path(brain_str) if brain_str else (pathlib.Path(os.path.expanduser('~')) / '.gemini' / 'antigravity-cli' / 'brain')
    if conversation_id:
        p = brain / conversation_id / '.system_generated' / 'logs' / 'transcript.jsonl'
        return p if p.is_file() else None
    if not brain.is_dir():
        return None
    candidates = list(brain.glob('*/.system_generated/logs/transcript.jsonl'))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return candidates[0]


def load_json_safe(path: pathlib.Path):
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding='utf-8-sig'))
    except Exception:
        pass
    return {}


def is_eof_record(rec: dict) -> bool:
    if rec.get('type') != 'ERROR_MESSAGE':
        return False
    blob = json.dumps(rec, ensure_ascii=False)
    return bool(EOF_RE.search(blob))


def analyze_context(
    conversation_id: str = '',
    transcript: str = '',
    warn_tokens: int = 300000,
    trigger_tokens: int = 400000,
    eof_compact_tokens: int = 150000,
    cooldown_seconds: int = 180,
    harness_root: str = DEFAULT_HARNESS_ROOT,
    milestone: bool = False,
):
    tpath = find_transcript(conversation_id, transcript, harness_root=harness_root)
    if not tpath:
        return {'ok': False, 'error': 'transcript.jsonl not found'}

    conv_id = conversation_id or tpath.parent.parent.parent.name
    now = datetime.datetime.now(datetime.timezone.utc)

    total_steps = 0
    checkpoint_count = 0
    last_cp_at = None
    last_planner = None
    steps_since_cp = 0
    errors_since_cp = 0
    eof_errors_since_cp = 0
    last_eof_step_idx = -1
    last_eof_at = ''

    with tpath.open('r', encoding='utf-8', errors='replace') as f:
        for idx, raw in enumerate(f):
            raw = raw.strip()
            if not raw:
                continue
            try:
                d = json.loads(raw)
            except Exception:
                continue
            total_steps += 1
            stype = d.get('type', '')
            if stype == 'CHECKPOINT':
                checkpoint_count += 1
                last_cp_at = d.get('created_at', '')
                last_planner = None
                steps_since_cp = 0
                errors_since_cp = 0
                eof_errors_since_cp = 0
                last_eof_step_idx = -1
                last_eof_at = ''
            else:
                steps_since_cp += 1
                if stype == 'ERROR_MESSAGE':
                    errors_since_cp += 1
                    if is_eof_record(d):
                        eof_errors_since_cp += 1
                        last_eof_step_idx = idx
                        last_eof_at = d.get('created_at', '')
                elif stype == 'PLANNER_RESPONSE':
                    last_planner = d

    inp = int(last_planner.get('input_tokens', 0)) if last_planner else 0
    cache = int(last_planner.get('cache_read_tokens', 0)) if last_planner else 0
    out_tok = int(last_planner.get('output_tokens', 0)) if last_planner else 0
    current_tokens = inp + cache

    secs_since_cp = None
    dt_cp = parse_iso(last_cp_at)
    if dt_cp:
        secs_since_cp = int((now - dt_cp.astimezone(datetime.timezone.utc)).total_seconds())

    hroot = pathlib.Path(harness_root)
    cfg = _load_cfg(harness_root)
    state_p = pathlib.Path(cfg.get('compact', {}).get('state_file', '') or (hroot / 'logs' / 'auto_compact_state.json'))
    pid_p = pathlib.Path(cfg.get('watchdog', {}).get('pid_file', '') or (hroot / 'logs' / 'watchdog.pid'))
    eof_sig_path = pathlib.Path(cfg.get('watchdog', {}).get('eof_signal_file', '') or (hroot / 'tmp' / 'eof_signal.json'))

    state = load_json_safe(state_p)
    last_req_dt = parse_iso(state.get('last_compact_at', ''))
    cooldown_rem = 0
    if last_req_dt:
        elapsed = int((now - last_req_dt.astimezone(datetime.timezone.utc)).total_seconds())
        if elapsed < cooldown_seconds:
            cooldown_rem = cooldown_seconds - elapsed
    if secs_since_cp is not None and secs_since_cp < cooldown_seconds:
        cooldown_rem = max(cooldown_rem, cooldown_seconds - secs_since_cp)

    pid_info = load_json_safe(pid_p)
    watchdog_present = bool(pid_info.get('pid'))

    # Check watchdog-written transient EOF signal
    eof_sig = load_json_safe(eof_sig_path)
    watchdog_eof_active = False
    watchdog_eof_id = ''
    if eof_sig:
        sig_conv = eof_sig.get('conversation_id', '')
        sig_dt = parse_iso(eof_sig.get('detected_at', ''))
        if (not sig_conv or sig_conv == conv_id) and sig_dt:
            is_after_cp = (dt_cp is None) or (sig_dt.astimezone(datetime.timezone.utc) > dt_cp.astimezone(datetime.timezone.utc))
            age_sec = (now - sig_dt.astimezone(datetime.timezone.utc)).total_seconds()
            if is_after_cp and age_sec <= 600:
                watchdog_eof_active = True
                watchdog_eof_id = str(eof_sig.get('signal_id') or eof_sig.get('detected_at'))

    eof_detected = (eof_errors_since_cp > 0) or watchdog_eof_active
    eof_action = 'none'
    reasons = []
    severity = 'ok'
    should_compact = False
    action = 'continue'

    if eof_detected:
        if current_tokens >= eof_compact_tokens:
            eof_action = 'compact_then_breakdown'
            severity = 'urgent'
            should_compact = True
            action = 'eof_compact_then_breakdown'
            reasons.append(
                f'EOF detected with current_tokens={current_tokens} >= {eof_compact_tokens}: compact first, then break down task & write plan'
            )
        else:
            eof_action = 'breakdown_only'
            severity = 'warn'
            should_compact = False
            action = 'eof_breakdown_only'
            reasons.append(
                f'EOF detected with current_tokens={current_tokens} < {eof_compact_tokens}: skip compact, break down task & write plan'
            )

    if current_tokens >= trigger_tokens:
        severity = 'urgent'
        should_compact = True
        if action not in ('eof_compact_then_breakdown',):
            action = 'compact_now'
        reasons.append(f'current_tokens={current_tokens} >= trigger_tokens={trigger_tokens}')
    elif current_tokens >= warn_tokens and not eof_detected:
        severity = 'warn'
        if milestone:
            should_compact = True
            action = 'compact_now'
            reasons.append(f'milestone reached with current_tokens={current_tokens} >= warn_tokens={warn_tokens}')
        else:
            action = 'compact_at_milestone'
            reasons.append(f'current_tokens={current_tokens} >= warn_tokens={warn_tokens}; compact at milestone')

    if should_compact and cooldown_rem > 0:
        should_compact = False
        action = 'cooldown_wait'
        reasons.append(f'cooldown active ({cooldown_rem}s remaining)')

    return {
        'ok': True,
        'conversation_id': conv_id,
        'transcript_path': str(tpath),
        'current_tokens': current_tokens,
        'last_input_tokens': inp,
        'last_cache_read_tokens': cache,
        'last_output_tokens': out_tok,
        'total_steps': total_steps,
        'checkpoint_count': checkpoint_count,
        'last_checkpoint_at': last_cp_at,
        'seconds_since_last_checkpoint': secs_since_cp,
        'steps_since_compact': steps_since_cp,
        'errors_since_compact': errors_since_cp,
        'eof_errors_since_compact': eof_errors_since_cp,
        'last_eof_step_idx': last_eof_step_idx,
        'last_eof_at': last_eof_at,
        'watchdog_eof_active': watchdog_eof_active,
        'watchdog_eof_id': watchdog_eof_id,
        'eof_detected': eof_detected,
        'eof_action': eof_action,
        'cooldown_remaining_seconds': cooldown_rem,
        'watchdog_heartbeat_present': watchdog_present,
        'thresholds': {
            'warn_tokens': warn_tokens,
            'trigger_tokens': trigger_tokens,
            'eof_compact_tokens': eof_compact_tokens,
        },
        'severity': severity,
        'should_compact': should_compact,
        'recommended_action': action,
        'reasons': reasons,
    }


def main():
    ap = argparse.ArgumentParser(description='Measure Antigravity context usage from transcript.jsonl')
    ap.add_argument('--conversation-id', default='')
    ap.add_argument('--transcript', default='')
    ap.add_argument('--warn-tokens', type=int, default=300000)
    ap.add_argument('--trigger-tokens', type=int, default=400000)
    ap.add_argument('--eof-compact-tokens', type=int, default=150000)
    ap.add_argument('--cooldown-seconds', type=int, default=180)
    ap.add_argument('--harness-root', default=DEFAULT_HARNESS_ROOT)
    ap.add_argument('--milestone', action='store_true', help='Hint that a pipeline stage/milestone just finished')
    args = ap.parse_args()

    result = analyze_context(
        conversation_id=args.conversation_id,
        transcript=args.transcript,
        warn_tokens=args.warn_tokens,
        trigger_tokens=args.trigger_tokens,
        eof_compact_tokens=args.eof_compact_tokens,
        cooldown_seconds=args.cooldown_seconds,
        harness_root=args.harness_root,
        milestone=args.milestone,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get('ok'):
        sys.exit(1)


if __name__ == '__main__':
    main()
