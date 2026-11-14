"""Shared storage contract. Application resources and durable user data are independent."""
from pathlib import Path
import json
import ntpath
import os

SCHEME = 'synesis-data://'
PATH_KEYS = {'path', 'source', 'folder', 'ledgerPath', 'audioFolder', 'walletPath',
             'response', 'responsePath', 'reusedFrom', 'planningReusedFrom'}

def extended_windows_path(value):
    """Use Unicode filesystem paths without requiring a machine-wide registry change."""
    value = ntpath.normpath(os.fspath(value))
    if value.startswith(('\\\\?\\', '\\\\.\\')):
        return value
    value = ntpath.abspath(value)
    if value.startswith('\\\\'):
        return '\\\\?\\UNC\\' + value[2:]
    return '\\\\?\\' + value

def io_path(value):
    # Only Windows I/O needs the extended prefix; portable JSON references
    # still use SCHEME so existing stores and cross-platform backups work.
    return Path(extended_windows_path(value)) if os.name == 'nt' else Path(value)

def app_root():
    return io_path(os.environ.get('SYNESIS_APP_ROOT') or Path(__file__).resolve().parent.parent).resolve()

def data_root():
    return io_path(Path(os.environ.get('SYNESIS_DATA_DIR') or Path.home() / 'SYNESIS Data').expanduser()).resolve()

def root_for(path):
    path = io_path(path).resolve()
    for parent in (path, *path.parents):
        if (parent / 'manifest.json').is_file():
            try:
                if json.loads((parent / 'manifest.json').read_text(encoding='utf-8')).get('format') == 'synesis-user-data':
                    return parent
            except (OSError, ValueError):
                pass
    return None

def resolve_path(value, anchor=None):
    value = str(value)
    if not value.startswith(SCHEME):
        return io_path(value)
    root = root_for(anchor) if anchor is not None else None
    root = root or data_root()
    relative = value[len(SCHEME):]
    path = (root / relative).resolve()
    if not relative or '\\' in relative or not path.is_relative_to(root.resolve()):
        raise ValueError('Invalid user data reference')
    return path

def reference(path, anchor=None):
    path = io_path(path).resolve()
    root = root_for(anchor or path)
    if root is not None and path.is_relative_to(root):
        return SCHEME + path.relative_to(root).as_posix()
    return str(path)

def transform(value, root, encode=False, key=''):
    if isinstance(value, dict):
        return {k: transform(v, root, encode, k) for k, v in value.items()}
    if isinstance(value, list):
        return [transform(v, root, encode, key) for v in value]
    if isinstance(value, str) and key in PATH_KEYS:
        if value.startswith(SCHEME):
            return value if encode else str(resolve_path(value, root))
        if encode and Path(value).is_absolute() and io_path(value).resolve().is_relative_to(root):
            return SCHEME + io_path(value).resolve().relative_to(root).as_posix()
    return value

def portable(value, anchor):
    root = root_for(anchor)
    return transform(value, root, True) if root is not None else value

def hydrate(value, anchor):
    root = root_for(anchor)
    return transform(value, root) if root is not None else value

def account_for_library(library):
    library = Path(library).absolute()
    root = root_for(library)
    return root / 'account' if root is not None else library.parent

def wallet_for_document(folder):
    return account_for_library(Path(folder).parent) / 'credits-wallet.json'

def credentials_file():
    # Credentials deliberately stay outside a portable user-data backup.
    return io_path(os.environ.get('SYNESIS_CREDENTIALS_FILE') or app_root() / '.env')

def runtime_state():
    return data_root() / '.runtime'
