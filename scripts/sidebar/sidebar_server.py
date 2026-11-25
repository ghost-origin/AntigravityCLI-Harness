import argparse
import ctypes
import http.server
import json
import mimetypes
import os
import pathlib
import queue
import re
import shutil
import socketserver
import subprocess
import sys
import threading
import time
import urllib.parse

CONV_ID_RE = re.compile(r'^[0-9a-fA-F-]{8,64}$')

sys.dont_write_bytecode = True

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
CFG_DIR = REPO_ROOT / 'Config'
if str(CFG_DIR) not in sys.path:
    sys.path.insert(0, str(CFG_DIR))
try:
    import config_loader as _cfg_loader
    HARNESS_CFG = _cfg_loader.load_config(str(REPO_ROOT))
except Exception:
    HARNESS_CFG = {}

WEB_DIR = pathlib.Path(HARNESS_CFG.get('sidebar', {}).get('web_dir') or (SCRIPT_DIR / 'web'))
VENDOR_DIR = pathlib.Path(HARNESS_CFG.get('sidebar', {}).get('vendor_dir') or (SCRIPT_DIR / 'vendor'))
DOCK_REG_DIR = pathlib.Path(HARNESS_CFG.get('sidebar', {}).get('dock_registry_dir') or (REPO_ROOT / 'tmp' / 'sidebar_docks'))
TAB_CONV_RE = re.compile(r'\[([0-9a-fA-F]{8})\]')

sys.path.insert(0, str(SCRIPT_DIR))
import transcript_watcher as tw  # noqa: E402
import window_docker as wd  # noqa: E402

mimetypes.add_type('font/woff2', '.woff2')
mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('text/css', '.css')


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return True
    if os.name == 'nt':
        handle = ctypes.windll.kernel32.OpenProcess(0x100000, False, pid)
        if not handle:
            return False
        try:
            res = ctypes.windll.kernel32.WaitForSingleObject(handle, 0)
            return res == 0x102
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class SidebarState:
    def __init__(self, brain_dir: pathlib.Path, conv_id: str = '', enable_clipboard: bool = True):
        self.brain_dir = brain_dir
        self.auto_follow = not bool(conv_id)
        self.selected_conv = conv_id
        self.default_tab_conv = conv_id or 'auto'
        self.active_conv = ''
        self.active_path = None
        self.last_sig = None
        self.messages = []
        self.conversations = []
        self.clipboard = tw.ClipboardImageWatcher() if enable_clipboard else None
        self.lock = threading.Lock()
        self.clients = set()
        self.stop_event = threading.Event()
        self.refresh(force=True)

    def subscribe(self) -> queue.Queue:
        q = queue.Queue(maxsize=64)
        with self.lock:
            self.clients.add(q)
        return q

    def unsubscribe(self, q: queue.Queue):
        with self.lock:
            self.clients.discard(q)

    def broadcast(self, event: str, data: dict):
        payload = f'event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'.encode('utf-8')
        with self.lock:
            dead = []
            for q in self.clients:
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self.clients.discard(q)

    def select_conversation(self, conv_id: str):
        with self.lock:
            if not conv_id or conv_id == 'auto':
                self.auto_follow = True
                self.selected_conv = ''
            else:
                self.auto_follow = False
                self.selected_conv = conv_id
            self.last_sig = None
        self.refresh(force=True)

    def resolve_conv_by_prefix(self, prefix: str) -> str:
        low = prefix.lower()
        with self.lock:
            for c in self.conversations:
                if str(c.get('id', '')).lower().startswith(low):
                    return str(c['id'])
        try:
            for child in self.brain_dir.iterdir():
                if child.is_dir() and child.name.lower().startswith(low):
                    return child.name
        except OSError:
            pass
        return ''

    def handle_term_title_changed(self, title: str):
        m = TAB_CONV_RE.search(title or '')
        if m:
            full_id = self.resolve_conv_by_prefix(m.group(1))
            if full_id and (self.auto_follow or self.selected_conv != full_id):
                self.select_conversation(full_id)
        else:
            target = self.default_tab_conv or 'auto'
            if target == 'auto':
                if not self.auto_follow:
                    self.select_conversation('auto')
            elif self.auto_follow or self.selected_conv != target:
                self.select_conversation(target)

    def snapshot(self) -> dict:
        with self.lock:
            return {
                'auto_follow': self.auto_follow,
                'active_conv': self.active_conv,
                'conversations': list(self.conversations),
                'messages': list(self.messages),
                'clipboard': self.clipboard.meta() if self.clipboard else {'has_image': False},
            }

    def refresh(self, force: bool = False):
        convs = tw.list_conversations(self.brain_dir)
        target = None
        if self.auto_follow:
            if convs:
                target = convs[0]
        else:
            for c in convs:
                if c['id'] == self.selected_conv:
                    target = c
                    break
            if not target and self.selected_conv:
                tp = tw.find_transcript_for_conv(self.brain_dir / self.selected_conv)
                if tp:
                    st = tp.stat()
                    target = {'id': self.selected_conv, 'path': str(tp), 'mtime': st.st_mtime, 'size': st.st_size}

        changed = False
        if target:
            sig = (target['id'], target['mtime'], target['size'])
            if force or sig != self.last_sig:
                msgs = tw.parse_transcript(pathlib.Path(target['path']))
                with self.lock:
                    self.conversations = convs
                    self.active_conv = target['id']
                    self.active_path = pathlib.Path(target['path'])
                    self.last_sig = sig
                    self.messages = msgs
                changed = True
            else:
                with self.lock:
                    self.conversations = convs
        else:
            with self.lock:
                self.conversations = convs
                if force:
                    self.active_conv = ''
                    self.messages = []

        if changed and not force:
            self.broadcast('update', self.snapshot())
        elif force:
            self.broadcast('update', self.snapshot())

        if self.clipboard and self.clipboard.poll():
            self.broadcast('clipboard', self.clipboard.meta())


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def open_conversation_in_new_tab(conv_id: str, title: str = '', workspace: str = '', docker=None) -> dict:
    if not conv_id or not CONV_ID_RE.match(conv_id):
        return {'ok': False, 'error': 'invalid conversation id'}

    cwd = ''
    if workspace:
        p = pathlib.Path(workspace)
        if p.is_dir():
            cwd = str(p)
    if not cwd:
        cwd = os.path.expanduser('~')

    clean_title = ' '.join((title or '').replace('"', '').replace("'", '').split())[:22]
    id8 = conv_id[:8]
    tab_title = f'agy · {clean_title} [{id8}]' if clean_title else f'agy [{id8}]'

    ps_cmd = f"$env:AGY_SIDEBAR='0'; agy -r {conv_id}"
    cfg_wt = HARNESS_CFG.get('executables', {}).get('wt_exe', '')
    wt_exe = cfg_wt if (cfg_wt and pathlib.Path(cfg_wt).is_file()) else (shutil.which('wt.exe') or shutil.which('wt'))
    flags = 0
    if os.name == 'nt':
        flags = getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)

    try:
        if docker:
            docker.focus_terminal()
            time.sleep(0.06)
        if wt_exe:
            cmd = [
                wt_exe, '-w', '0', 'new-tab',
                '--suppressApplicationTitle',
                '--title', tab_title,
                '-d', cwd,
                'powershell.exe', '-NoExit', '-Command', ps_cmd,
            ]
        else:
            cmd = ['powershell.exe', '-NoExit', '-Command', f"$Host.UI.RawUI.WindowTitle='{tab_title}'; {ps_cmd}"]
        subprocess.Popen(cmd, cwd=cwd, creationflags=flags, close_fds=True)
        return {'ok': True, 'conv_id': conv_id, 'cwd': cwd, 'tab_title': tab_title}
    except Exception as exc:
        return {'ok': False, 'error': str(exc)}


def make_handler(state: SidebarState, server_ref: dict):
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, fmt, *args):
            return

        def _send_bytes(self, code: int, body: bytes, ctype: str, extra_headers=None):
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-cache')
            if extra_headers:
                for k, v in extra_headers.items():
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, code: int, obj: dict):
            self._send_bytes(code, json.dumps(obj, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8')

        def _serve_file(self, base: pathlib.Path, rel: str, cache: str = 'no-cache'):
            rel_clean = urllib.parse.unquote(rel).lstrip('/')
            target = (base / rel_clean).resolve()
            try:
                target.relative_to(base.resolve())
            except ValueError:
                self._send_json(403, {'error': 'forbidden'})
                return
            if not target.is_file():
                self._send_json(404, {'error': 'not found'})
                return
            ctype = mimetypes.guess_type(str(target))[0] or 'application/octet-stream'
            if ctype.startswith('text/') or ctype in ('application/javascript', 'application/json'):
                ctype += '; charset=utf-8'
            self._send_bytes(200, target.read_bytes(), ctype, {'Cache-Control': cache})

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            path = parsed.path
            qs = urllib.parse.parse_qs(parsed.query)

            if path == '/' or path == '/index.html':
                return self._serve_file(WEB_DIR, 'index.html')
            if path.startswith('/static/'):
                return self._serve_file(WEB_DIR, path[len('/static/'):])
            if path.startswith('/vendor/'):
                return self._serve_file(VENDOR_DIR, path[len('/vendor/'):], cache='public, max-age=86400')
            if path == '/api/health':
                return self._send_json(200, {'ok': True, 'active_conv': state.active_conv})
            if path == '/api/snapshot':
                return self._send_json(200, state.snapshot())
            if path == '/api/clipboard/image':
                if not state.clipboard or not state.clipboard.image_bytes:
                    return self._send_json(404, {'error': 'no clipboard image'})
                return self._send_bytes(200, state.clipboard.image_bytes, state.clipboard.image_mime)
            if path == '/api/media':
                raw_path = (qs.get('path') or [''])[0]
                if not raw_path:
                    return self._send_json(400, {'error': 'missing path'})
                norm = urllib.parse.unquote(raw_path)
                if norm.lower().startswith('file:///'):
                    norm = norm[8:]
                fp = pathlib.Path(norm)
                if not fp.is_file() or fp.suffix.lower() not in tw.IMAGE_EXTS:
                    return self._send_json(404, {'error': 'image not found'})
                ctype = mimetypes.guess_type(str(fp))[0] or 'application/octet-stream'
                return self._send_bytes(200, fp.read_bytes(), ctype, {'Cache-Control': 'private, max-age=3600'})
            if path == '/api/events':
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Connection', 'keep-alive')
                self.end_headers()
                q = state.subscribe()
                try:
                    init_msg = f'event: update\ndata: {json.dumps(state.snapshot(), ensure_ascii=False)}\n\n'.encode('utf-8')
                    self.wfile.write(init_msg)
                    self.wfile.flush()
                    while not state.stop_event.is_set():
                        try:
                            chunk = q.get(timeout=15)
                            self.wfile.write(chunk)
                            self.wfile.flush()
                        except queue.Empty:
                            self.wfile.write(b': ping\n\n')
                            self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    state.unsubscribe(q)
                return

            self._send_json(404, {'error': 'unknown route'})

        def do_POST(self):
            parsed = urllib.parse.urlsplit(self.path)
            length = int(self.headers.get('Content-Length') or '0')
            body = self.rfile.read(length) if length > 0 else b'{}'
            try:
                data = json.loads(body.decode('utf-8')) if body else {}
            except json.JSONDecodeError:
                data = {}

            if parsed.path == '/api/select':
                state.select_conversation(str(data.get('conv_id', 'auto')))
                return self._send_json(200, {'ok': True})
            if parsed.path == '/api/open-terminal':
                cid = str(data.get('conv_id', '')).strip()
                ws = ''
                ctitle = ''
                with state.lock:
                    if state.default_tab_conv == 'auto' and state.active_conv:
                        state.default_tab_conv = state.active_conv
                    for c in state.conversations:
                        if c.get('id') == cid:
                            ws = str(c.get('workspace') or '')
                            ctitle = str(c.get('title') or '')
                            break
                docker = server_ref.get('docker')
                res = open_conversation_in_new_tab(cid, title=ctitle, workspace=ws, docker=docker)
                if res.get('ok'):
                    state.select_conversation(cid)
                return self._send_json(200 if res.get('ok') else 400, res)
            if parsed.path == '/api/clipboard/clear':
                if state.clipboard:
                    state.clipboard.clear()
                    state.broadcast('clipboard', state.clipboard.meta())
                return self._send_json(200, {'ok': True})
            if parsed.path == '/api/dock':
                docker = server_ref.get('docker')
                th = int(data.get('term_hwnd') or 0)
                eh = int(data.get('edge_hwnd') or 0)
                ok = False
                if docker:
                    ok = docker.attach(th, eh, ratio=float(data.get('width_ratio') or 0.38))
                if ok and th:
                    try:
                        DOCK_REG_DIR.mkdir(parents=True, exist_ok=True)
                        reg = DOCK_REG_DIR / f'dock_{th}.json'
                        reg.write_text(json.dumps({
                            'pid': os.getpid(),
                            'url': server_ref.get('url', ''),
                            'term_hwnd': th,
                            'edge_hwnd': eh,
                        }, indent=2), encoding='utf-8')
                        server_ref['dock_reg_file'] = reg
                    except OSError:
                        pass
                return self._send_json(200, {'ok': ok})
            if parsed.path == '/api/shutdown':
                self._send_json(200, {'ok': True})
                trigger_shutdown(state, server_ref)
                return
            self._send_json(404, {'error': 'unknown route'})

    return Handler


def trigger_shutdown(state: SidebarState, server_ref: dict):
    docker = server_ref.get('docker')
    if docker:
        docker.stop()
    reg = server_ref.get('dock_reg_file')
    if reg:
        try:
            pathlib.Path(reg).unlink(missing_ok=True)
        except OSError:
            pass
    state.broadcast('shutdown', {'reason': 'requested'})
    state.stop_event.set()
    srv = server_ref.get('server')
    if srv:
        threading.Thread(target=srv.shutdown, daemon=True).start()


def main():
    ap = argparse.ArgumentParser(description='Antigravity CLI LaTeX & Image Sidebar Server')
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=0)
    ap.add_argument('--brain-dir', default='')
    ap.add_argument('--conversation-id', default='')
    ap.add_argument('--state-file', default='')
    ap.add_argument('--parent-pid', type=int, default=0)
    ap.add_argument('--no-clipboard', action='store_true')
    args = ap.parse_args()

    brain_dir = pathlib.Path(args.brain_dir) if args.brain_dir else tw.default_brain_dir()
    state = SidebarState(brain_dir, conv_id=args.conversation_id, enable_clipboard=not args.no_clipboard)
    server_ref = {}
    server = ThreadingServer((args.host, args.port), make_handler(state, server_ref))
    server_ref['server'] = server
    server_ref['docker'] = wd.WindowDocker(
        on_edge_closed=lambda: trigger_shutdown(state, server_ref),
        on_term_title_changed=state.handle_term_title_changed,
    )
    actual_port = server.server_address[1]
    url = f'http://{args.host}:{actual_port}'
    server_ref['url'] = url

    if args.state_file:
        sf = pathlib.Path(args.state_file)
        sf.parent.mkdir(parents=True, exist_ok=True)
        sf.write_text(json.dumps({
            'pid': os.getpid(),
            'host': args.host,
            'port': actual_port,
            'url': url,
        }, indent=2), encoding='utf-8')

    def poll_loop():
        while not state.stop_event.is_set():
            if args.parent_pid and not process_alive(args.parent_pid):
                trigger_shutdown(state, server_ref)
                break
            try:
                state.refresh(force=False)
            except Exception:
                pass
            time.sleep(0.35)

    threading.Thread(target=poll_loop, daemon=True).start()
    print(f'SIDEBAR_URL={url}', flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        trigger_shutdown(state, server_ref)
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
