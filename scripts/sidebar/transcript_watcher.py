import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import mimetypes
import os
import pathlib
import re
import struct
import sys
import urllib.parse

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_CFG_DIR = _REPO_ROOT / 'Config'
if str(_CFG_DIR) not in sys.path:
    sys.path.insert(0, str(_CFG_DIR))
try:
    import config_loader as _cfg_loader
    _HARNESS_CFG = _cfg_loader.load_config(str(_REPO_ROOT))
except Exception:
    _HARNESS_CFG = {}

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg'}
USER_REQ_RE = re.compile(r'<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>', re.DOTALL)
STRIP_TAGS_RE = re.compile(
    r'<(ADDITIONAL_METADATA|USER_SETTINGS_CHANGE|SYSTEM_MESSAGE)>.*?</\1>',
    re.DOTALL,
)
UPLOADED_IMG_RE = re.compile(r'^\s*-\s+([A-Za-z]:[^\r\n]+?\.(?:png|jpe?g|gif|webp|bmp|svg))\s*$', re.IGNORECASE | re.MULTILINE)
PBTXT_TITLE_RE = re.compile(r'title\s*:\s*"((?:\\.|[^"\\])*)"')


def _unescape_pbtxt(val: str) -> str:
    try:
        return json.loads('"' + val + '"')
    except Exception:
        return val


def _uri_to_local_dir(uri: str) -> str:
    if not uri:
        return ''
    norm = uri.strip()
    if norm.lower().startswith('file:///'):
        norm = urllib.parse.unquote(norm[8:])
    elif norm.lower().startswith('file://'):
        norm = urllib.parse.unquote(norm[7:])
    return norm.replace('\\', '/').rstrip('/')


def _load_conv_metadata_map(brain_dir: pathlib.Path) -> dict:
    app_dir = brain_dir.parent
    meta_map = {}

    cfg_cache = _HARNESS_CFG.get('antigravity', {}).get('conversation_cache_file', '')
    cache_file = pathlib.Path(cfg_cache) if cfg_cache else (app_dir / 'cache' / 'conversation_metadata.json')
    try:
        if cache_file.is_file():
            raw = json.loads(cache_file.read_text(encoding='utf-8', errors='replace'))
            convs = raw.get('conversations') if isinstance(raw, dict) else {}
            if isinstance(convs, dict):
                for cid, entry in convs.items():
                    if not isinstance(entry, dict):
                        continue
                    summ = entry.get('summary') if isinstance(entry.get('summary'), dict) else {}
                    uris = summ.get('WorkspaceURIs') or []
                    ws = _uri_to_local_dir(str(uris[0])) if uris else ''
                    meta_map[cid] = {
                        'title': str(summ.get('Title') or '').strip(),
                        'preview': str(summ.get('Preview') or '').strip(),
                        'workspace': ws,
                    }
    except Exception:
        pass

    cfg_ann = _HARNESS_CFG.get('antigravity', {}).get('annotations_dir', '')
    ann_dir = pathlib.Path(cfg_ann) if cfg_ann else (app_dir / 'annotations')
    try:
        if ann_dir.is_dir():
            for pb in ann_dir.glob('*.pbtxt'):
                cid = pb.stem
                try:
                    txt = pb.read_text(encoding='utf-8', errors='replace')
                    m = PBTXT_TITLE_RE.search(txt)
                    if m:
                        title = _unescape_pbtxt(m.group(1)).strip()
                        if title:
                            meta_map.setdefault(cid, {})['title'] = title
                except OSError:
                    continue
    except OSError:
        pass

    return meta_map


def _first_user_preview(tpath: pathlib.Path) -> str:
    try:
        with tpath.open('r', encoding='utf-8', errors='replace') as f:
            for _ in range(30):
                line = f.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get('type') == 'USER_INPUT':
                    cleaned = clean_user_content(str(rec.get('content', '')))
                    cleaned = ' '.join(cleaned.split())
                    if cleaned:
                        return cleaned[:60]
    except OSError:
        pass
    return ''


def default_brain_dir() -> pathlib.Path:
    env_dir = os.environ.get('AGY_BRAIN_DIR', '').strip()
    if env_dir:
        return pathlib.Path(env_dir)
    cfg_dir = _HARNESS_CFG.get('antigravity', {}).get('brain_dir', '')
    if cfg_dir:
        return pathlib.Path(cfg_dir)
    return pathlib.Path(os.path.expanduser('~')) / '.gemini' / 'antigravity-cli' / 'brain'


def find_transcript_for_conv(conv_dir: pathlib.Path):
    try:
        logs = conv_dir / '.system_generated' / 'logs'
        full_p = logs / 'transcript_full.jsonl'
        if full_p.is_file():
            return full_p
        compact_p = logs / 'transcript.jsonl'
        if compact_p.is_file():
            return compact_p
    except OSError:
        return None
    return None


def list_conversations(brain_dir: pathlib.Path, limit: int = 20) -> list:
    try:
        if not brain_dir.is_dir():
            return []
        entries = list(brain_dir.iterdir())
    except OSError:
        return []
    meta_map = _load_conv_metadata_map(brain_dir)
    items = []
    for child in entries:
        try:
            if not child.is_dir():
                continue
            tpath = find_transcript_for_conv(child)
            if not tpath:
                continue
            st = tpath.stat()
            cid = child.name
            meta = meta_map.get(cid, {})
            title = meta.get('title') or meta.get('preview') or ''
            ws = meta.get('workspace') or ''
            ws_name = pathlib.Path(ws).name if ws else ''
            items.append({
                'id': cid,
                'title': title,
                'workspace': ws,
                'workspace_name': ws_name,
                'path': str(tpath),
                'mtime': st.st_mtime,
                'size': st.st_size,
            })
        except OSError:
            continue
    items.sort(key=lambda x: x['mtime'], reverse=True)
    top = items[:limit]
    for it in top:
        if not it['title']:
            it['title'] = _first_user_preview(pathlib.Path(it['path'])) or it['id'][:8]
    return top


def clean_user_content(raw: str) -> str:
    if not raw:
        return ''
    m = USER_REQ_RE.search(raw)
    if m:
        return m.group(1).strip()
    cleaned = STRIP_TAGS_RE.sub('', raw).strip()
    return cleaned


def extract_media_items(rec: dict, raw_content: str) -> list:
    seen = set()
    out = []

    def add_uri(uri: str, mime: str = ''):
        if not uri:
            return
        norm = uri.replace('\\', '/')
        if norm.lower().startswith('file:///'):
            norm = urllib.parse.unquote(norm[8:])
        key = norm.lower()
        if key in seen:
            return
        ext = pathlib.Path(norm).suffix.lower()
        if ext and ext not in IMAGE_EXTS:
            return
        seen.add(key)
        if not mime:
            mime = mimetypes.guess_type(norm)[0] or 'image/png'
        out.append({
            'uri': norm,
            'name': pathlib.Path(norm).name,
            'mime_type': mime,
            'url': '/api/media?path=' + urllib.parse.quote(norm, safe=''),
        })

    for item in rec.get('media') or []:
        if isinstance(item, dict):
            add_uri(str(item.get('uri', '')), str(item.get('mime_type', '')))

    for m in UPLOADED_IMG_RE.finditer(raw_content or ''):
        add_uri(m.group(1).strip())

    return out


def parse_transcript(tpath: pathlib.Path) -> list:
    if not tpath or not tpath.is_file():
        return []
    messages = []
    try:
        text = tpath.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue

        rtype = rec.get('type', '')
        step = rec.get('step_index', len(messages))
        created = rec.get('created_at', '')

        if rtype == 'USER_INPUT':
            raw = str(rec.get('content', ''))
            media = extract_media_items(rec, raw)
            cleaned = clean_user_content(raw)
            if not cleaned and not media:
                continue
            messages.append({
                'id': f'u-{step}',
                'step_index': step,
                'role': 'user',
                'created_at': created,
                'content': cleaned,
                'media': media,
            })
        elif rtype == 'PLANNER_RESPONSE':
            content = str(rec.get('content', '')).strip()
            if not content:
                continue
            messages.append({
                'id': f'a-{step}',
                'step_index': step,
                'role': 'assistant',
                'created_at': created,
                'model': str(rec.get('model', '')),
                'content': content,
                'media': [],
            })
    return messages


def _dib_to_bmp(dib: bytes):
    if len(dib) < 40:
        return None
    bi_size = struct.unpack_from('<I', dib, 0)[0]
    if bi_size < 40 or bi_size > len(dib):
        return None
    bit_count = struct.unpack_from('<H', dib, 14)[0]
    compression = struct.unpack_from('<I', dib, 16)[0]
    clr_used = struct.unpack_from('<I', dib, 32)[0]
    palette_entries = clr_used if clr_used > 0 else ((1 << bit_count) if bit_count <= 8 else 0)
    extra_masks = 12 if (bi_size == 40 and compression == 3) else 0
    offset = 14 + bi_size + extra_masks + palette_entries * 4
    file_size = 14 + len(dib)
    header = struct.pack('<2sIHHI', b'BM', file_size, 0, 0, offset)
    return header + dib


class ClipboardImageWatcher:
    """Zero-dependency Windows clipboard image monitor via Win32 ctypes."""

    CF_DIB = 8
    CF_HDROP = 15

    def __init__(self):
        self.enabled = (os.name == 'nt')
        self.last_seq = -1
        self.image_bytes = b''
        self.image_mime = 'image/bmp'
        self.image_name = ''
        self.image_hash = ''
        if self.enabled:
            self._user32 = ctypes.windll.user32
            self._kernel32 = ctypes.windll.kernel32
            self._shell32 = ctypes.windll.shell32
            self._kernel32.GlobalLock.argtypes = [wt.HGLOBAL]
            self._kernel32.GlobalLock.restype = ctypes.c_void_p
            self._kernel32.GlobalUnlock.argtypes = [wt.HGLOBAL]
            self._kernel32.GlobalSize.argtypes = [wt.HGLOBAL]
            self._kernel32.GlobalSize.restype = ctypes.c_size_t
            self._user32.GetClipboardData.argtypes = [wt.UINT]
            self._user32.GetClipboardData.restype = wt.HGLOBAL
            self._shell32.DragQueryFileW.argtypes = [wt.HANDLE, wt.UINT, wt.LPWSTR, wt.UINT]
            self._shell32.DragQueryFileW.restype = wt.UINT
            self.last_seq = int(self._user32.GetClipboardSequenceNumber())

    def poll(self) -> bool:
        if not self.enabled:
            return False
        seq = int(self._user32.GetClipboardSequenceNumber())
        if seq == self.last_seq:
            return False
        self.last_seq = seq
        has_dib = bool(self._user32.IsClipboardFormatAvailable(self.CF_DIB))
        has_drop = bool(self._user32.IsClipboardFormatAvailable(self.CF_HDROP))
        if not has_dib and not has_drop:
            return False
        if not self._user32.OpenClipboard(None):
            return False
        try:
            if has_dib:
                handle = self._user32.GetClipboardData(self.CF_DIB)
                if handle:
                    size = self._kernel32.GlobalSize(handle)
                    ptr = self._kernel32.GlobalLock(handle)
                    if ptr and size > 40:
                        try:
                            dib = ctypes.string_at(ptr, size)
                        finally:
                            self._kernel32.GlobalUnlock(handle)
                        bmp = _dib_to_bmp(dib)
                        if bmp:
                            return self._store(bmp, 'image/bmp', 'clipboard.bmp')
            if has_drop:
                handle = self._user32.GetClipboardData(self.CF_HDROP)
                if handle:
                    count = self._shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0)
                    for i in range(min(count, 5)):
                        buf = ctypes.create_unicode_buffer(1024)
                        self._shell32.DragQueryFileW(handle, i, buf, 1024)
                        fp = pathlib.Path(buf.value)
                        if fp.is_file() and fp.suffix.lower() in IMAGE_EXTS:
                            data = fp.read_bytes()
                            mime = mimetypes.guess_type(str(fp))[0] or 'image/png'
                            return self._store(data, mime, fp.name)
        except Exception:
            return False
        finally:
            self._user32.CloseClipboard()
        return False

    def _store(self, data: bytes, mime: str, name: str) -> bool:
        digest = hashlib.sha1(data).hexdigest()[:12]
        if digest == self.image_hash:
            return False
        self.image_bytes = data
        self.image_mime = mime
        self.image_name = name
        self.image_hash = digest
        return True

    def clear(self):
        self.image_bytes = b''
        self.image_hash = ''
        self.image_name = ''

    def meta(self) -> dict:
        if not self.image_bytes:
            return {'has_image': False, 'hash': ''}
        return {
            'has_image': True,
            'hash': self.image_hash,
            'name': self.image_name,
            'mime': self.image_mime,
            'url': f'/api/clipboard/image?v={self.image_hash}',
        }
