import configparser
import os
import pathlib


def _default_repo_root() -> pathlib.Path:
    env_root = os.environ.get('GEMINI_HARNESS_ROOT', '').strip()
    if env_root:
        return pathlib.Path(env_root).resolve()
    return pathlib.Path(__file__).resolve().parent.parent


def _expand(val: str, repo_root: pathlib.Path, user_home: str) -> str:
    if not val:
        return ''
    out = val.replace('${REPO_ROOT}', str(repo_root)).replace('${USERPROFILE}', user_home)
    return os.path.normpath(out) if ('/' in out or '\\' in out) else out


def load_config(repo_root: str = '') -> dict:
    root = pathlib.Path(repo_root).resolve() if repo_root else _default_repo_root()
    user_home = os.path.expanduser('~')
    cfg_dir = root / 'Config'

    parser = configparser.ConfigParser(interpolation=None)
    for fname in ('harness.config', 'harness.local.config'):
        fp = cfg_dir / fname
        if fp.is_file():
            try:
                parser.read(fp, encoding='utf-8-sig')
            except Exception:
                pass

    result = {}
    for section in parser.sections():
        sec_map = {}
        for key, raw_val in parser.items(section):
            sec_map[key] = _expand(raw_val.strip(), root, user_home)
        result[section] = sec_map
    return result


def get_path(cfg: dict, section: str, key: str, fallback: str = '') -> pathlib.Path:
    val = cfg.get(section, {}).get(key, '') or fallback
    return pathlib.Path(val) if val else pathlib.Path()
