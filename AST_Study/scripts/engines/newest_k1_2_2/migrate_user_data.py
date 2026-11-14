"""Copy, verify, then atomically publish a user store. Never edits/deletes legacy data."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager
from synesis_paths import PATH_KEYS, SCHEME, app_root, data_root

FORMAT = 'synesis-user-data'
VERSION = 1
DIRECTORIES = ('library', 'recordings/lectures', 'recordings/lecture-notes', 'notes',
               'planner', 'academic', 'account', 'settings/preferences', '.runtime')
DOCUMENT = re.compile(r'[0-9a-f]{64}\Z')

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def assignments(legacy):
    owners = {}
    for file in (legacy / 'recordings/lecture-notes').glob('*.json'):
        if file.name.endswith('.lecture.json'):
            continue
        value = load(file)  # A damaged authoritative manifest must not be silently ignored.
        doc = value.get('documentId')
        for part in value.get('parts', []):
            path = Path(part['folder'])
            if not path.is_absolute():
                path = legacy / path
            owners.setdefault(path.resolve(), set()).add(doc)
    result = {}
    for folder in (legacy / 'recordings/lectures').iterdir() if (legacy / 'recordings/lectures').is_dir() else ():
        if not folder.is_dir():
            continue
        docs = owners.get(folder.resolve())
        if docs is None and (folder / 'lecture.json').is_file():
            docs = {p.get('documentId') for p in load(folder / 'lecture.json').get('pages', [])}
        if docs and len(docs) == 1:
            doc = next(iter(docs))
            if isinstance(doc, str) and DOCUMENT.fullmatch(doc) and (legacy / '.synesis/pdf' / doc / 'source.pdf').is_file():
                result[folder.resolve()] = Path('library') / doc / 'recordings' / folder.name
    return result

def plan(legacy):
    mappings = []
    state = legacy / '.synesis'
    if state.is_dir():
        for child in sorted(state.iterdir()):
            if child.is_symlink():
                raise ValueError('Legacy user data root contains a symbolic link')
            if child.name == 'api-slots' or child.name.endswith('.lock'):
                continue  # Process locks are not durable user content; originals remain intact.
            target = (Path('library') if child.name == 'pdf' else
                      Path('settings/preferences') if child.name == 'preferences' else
                      Path('account') / child.name)
            mappings.append((child.resolve(), target))
    special = assignments(legacy)
    recordings = legacy / 'recordings'
    if recordings.is_dir():
        for child in sorted(recordings.iterdir()):
            if child.is_symlink():
                raise ValueError('Legacy recordings contain a symbolic link')
            if child.name == 'lectures' and child.is_dir():
                for part in sorted(child.iterdir()):
                    if part.is_symlink():
                        raise ValueError('Legacy recording part contains a symbolic link')
                    mappings.append((part.resolve(), special.get(part.resolve(), Path('recordings/lectures') / part.name)))
            else:
                mappings.append((child.resolve(), Path('recordings') / child.name))
    return mappings

def files_for(mappings):
    files = []
    for source, target in mappings:
        candidates = sorted(source.rglob('*')) if source.is_dir() else [source]
        for file in candidates:
            if file.is_symlink():
                raise ValueError('User data contains a symbolic link; resolve it explicitly before migration')
            if file.is_file():
                relative = file.relative_to(source) if source.is_dir() else Path()
                files.append((file, target / relative))
    targets = [str(t) for _, t in files]
    if len(targets) != len(set(targets)):
        raise ValueError('Conflicting migration destinations')
    return files

def remap(value, mappings, legacy, key=''):
    if isinstance(value, dict):
        # Identity keys (especially billing operation IDs) are intentionally untouched.
        return {k: remap(v, mappings, legacy, k) for k, v in value.items()}
    if isinstance(value, list):
        return [remap(v, mappings, legacy, key) for v in value]
    if isinstance(value, str) and key in PATH_KEYS and not value.startswith(SCHEME):
        path = Path(value)
        if not path.is_absolute() and value.startswith(('.synesis/', 'recordings/')):
            path = legacy / path
        if path.is_absolute():
            path = path.resolve()
            for source, target in mappings:
                if path.is_relative_to(source):
                    return SCHEME + (target / path.relative_to(source)).as_posix()
    return value

def legacy_busy():
    """Exclude this bootstrap and its ancestors; refuse to snapshot a live legacy app."""
    try:
        rows = subprocess.check_output(['ps', '-axo', 'pid=,ppid=,command='], text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        raise RuntimeError('Cannot check for active SYNESIS writers; run migration with local process access') from None
    entries = {}
    for row in rows.splitlines():
        fields = row.strip().split(None, 2)
        if len(fields) == 3:
            entries[int(fields[0])] = (int(fields[1]), fields[2])
    ancestors = {os.getpid()}
    pid = os.getpid()
    while pid in entries and entries[pid][0] not in ancestors:
        pid = entries[pid][0]; ancestors.add(pid)
    for pid, (_, command) in entries.items():
        if pid in ancestors:
            continue
        if ('dev.synesis.poc.Main' in command or 'Contents/MacOS/SYNESIS-runtime' in command
                or re.search(r'python[^ ]* .*scripts/(lecture_stream|pdf_ai|soniox_billing)\.py', command)):
            return True
    return False

@contextmanager
def migration_lock(destination):
    lock = destination.with_name('.' + destination.name + '.migration.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            stream.write(b'0'); stream.flush(); stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.lockf(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.lockf(stream.fileno(), fcntl.LOCK_UN)

def migrate(legacy, destination, apply=False, check_busy=True):
    legacy, destination = Path(legacy).resolve(), Path(destination).resolve()
    if destination == legacy or destination.is_relative_to(legacy / '.synesis') or destination.is_relative_to(legacy / 'recordings'):
        raise ValueError('Destination overlaps legacy user data')
    existing = destination / 'manifest.json'
    if existing.is_file():
        manifest = load(existing)
        if manifest.get('format') != FORMAT or manifest.get('version') != VERSION:
            raise ValueError('Unsupported user data store; refusing to overwrite it')
        return {'status': 'already_initialized', 'destination': str(destination), 'storeId': manifest['storeId']}
    mappings = plan(legacy)
    files = files_for(mappings)
    report = {'status': 'planned', 'destination': str(destination), 'files': len(files),
              'bytes': sum(f.stat().st_size for f, _ in files), 'legacyPreserved': True}
    if not apply:
        return report
    if check_busy and files and legacy_busy():
        raise RuntimeError('An existing SYNESIS app or worker is running. Close it before migrating; no data was changed')
    with migration_lock(destination):
        if existing.is_file():
            return migrate(legacy, destination, check_busy=False)
        if destination.exists() and any(destination.iterdir()):
            raise ValueError('Destination is not empty; automatic merging is not allowed')
        stage = Path(tempfile.mkdtemp(prefix='.' + destination.name + '-migration-', dir=destination.parent))
        try:
            for directory in DIRECTORIES:
                (stage / directory).mkdir(parents=True, exist_ok=True)
            for source, target in mappings:
                if source.is_dir():
                    (stage / target).mkdir(parents=True, exist_ok=True)
                    for directory in source.rglob('*'):
                        if directory.is_dir():
                            (stage / target / directory.relative_to(source)).mkdir(parents=True, exist_ok=True)
            manifest = {'format': FORMAT, 'version': VERSION, 'storeId': str(uuid.uuid4()),
                        'createdAtMs': int(time.time() * 1000), 'legacyRoot': str(legacy)}
            hashes, rewritten = [], 0
            ordered = sorted(mappings, key=lambda p: len(str(p[0])), reverse=True)
            for source, relative in files:
                target = stage / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                before = source.stat()
                source_hash = digest(source)
                shutil.copy2(source, target)
                if digest(target) != source_hash or source.stat().st_mtime_ns != before.st_mtime_ns or source.stat().st_size != before.st_size:
                    raise RuntimeError('Source changed while copying; migration was not published')
                transformed = False
                if source.suffix == '.json':
                    try:
                        value = load(target)
                    except (ValueError, UnicodeError):
                        # Preserve unreadable historical artifacts byte for byte.
                        value = None
                    updated = remap(value, ordered, legacy)
                    if value != updated:
                        target.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding='utf-8')
                        transformed = True; rewritten += 1
                hashes.append({'source': str(source), 'target': relative.as_posix(),
                               'sourceSha256': source_hash, 'targetSha256': digest(target), 'pathsUpdated': transformed})
            # Recheck the source set and all bytes after the whole copy, not only each individual file.
            if files_for(plan(legacy)) != files or any(digest(row['source']) != row['sourceSha256'] for row in hashes):
                raise RuntimeError('Legacy data changed during migration; migration was not published')
            report.update(status='migrated', rewrittenJson=rewritten, verifiedFiles=len(hashes))
            (stage / 'migration-report.json').write_text(json.dumps({**report, 'files': hashes}, ensure_ascii=False, indent=2), encoding='utf-8')
            (stage / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
            if destination.exists():
                destination.rmdir()  # Only the verified empty destination, never legacy data.
            os.replace(stage, destination)
            return report
        except BaseException:
            shutil.rmtree(stage)
            raise

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--legacy-root', type=Path, default=app_root())
    parser.add_argument('--destination', type=Path, default=data_root())
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(migrate(args.legacy_root, args.destination, args.apply), ensure_ascii=False))
    except Exception as error:
        parser.exit(1, f'User data migration stopped: {error}\n')

if __name__ == '__main__':
    main()
