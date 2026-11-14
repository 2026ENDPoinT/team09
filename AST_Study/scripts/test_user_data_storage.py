"""Storage/migration integration tests use disposable data and never call a provider."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from migrate_user_data import migrate, digest
from synesis_paths import resolve_path, portable, hydrate, wallet_for_document, SCHEME

class StorageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='synesis-storage-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.old = self.base / 'old app 한글'
        self.new = self.base / 'user data 한글'
        self.doc = 'a' * 64
        self.pdf = self.old / '.synesis/pdf' / self.doc
        self.part = self.old / 'recordings/lectures/session-1'
        self.pdf.mkdir(parents=True); self.part.mkdir(parents=True)
        self.write(self.pdf / 'source.pdf', b'%PDF-preserve-exact-bytes')
        self.write(self.pdf / 'document.json', {'documentId': self.doc, 'fingerprint': 'unchanged-fingerprint', 'source': str(self.pdf / 'source.pdf'), 'pages': []})
        self.write(self.pdf / 'generated/paid.json', {'body': '유료 생성 결과 보존', 'reusedFrom': str(self.pdf / 'generated')})
        self.write(self.pdf / 'requests/attachments/one/image.png', b'original-image')
        self.write(self.part / 'audio.wav', b'RIFF-original-audio')
        self.write(self.part / 'lecture.json', {'pages': [{'documentId': self.doc}], 'segments': []})
        self.write(self.old / 'recordings/lecture-notes/lecture-1.json', {'id': 'lecture-1', 'documentId': self.doc, 'finished': True, 'parts': [{'folder': str(self.part)}]})
        self.ledger = self.pdf / 'usage/request.json'
        self.write(self.ledger, {'requests': [{'requestId': 'charge-1', 'state': 'settled', 'estimatedUsd': .001}]})
        self.operation = 'voice-' + str(self.part)
        self.write(self.old / '.synesis/credits-wallet.json', {'version': 1, 'purchases': [], 'baselineCredits': 0, 'highWaterCredits': 1,
            'liveBilling': True, 'creditHolds': {'charge-1': {'ledgerPath': str(self.ledger), 'operationId': self.operation}},
            'creditOperations': {self.operation: {'credits': '1'}}, 'creditCharges': {'existing': {'operationId': self.operation}}})
        self.write(self.old / '.synesis/voice-billing/voice.json', {'walletPath': str(self.old / '.synesis/credits-wallet.json'),
            'audioFolder': str(self.part), 'operationId': self.operation, 'settledUsd': '.001'})
        self.write(self.old / '.synesis/pdf/library-organization.json', {'folders': [], 'documents': {self.doc: 'folder-1'}})
        self.write(self.old / '.env', b'not-a-real-secret-do-not-copy')

    def write(self, file, value):
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode())

    def run_migration(self):
        return migrate(self.old, self.new, True, check_busy=False)

    def test_copy_preserves_all_originals_and_paid_artifacts(self):
        before = {p: digest(p) for p in self.old.rglob('*') if p.is_file()}
        report = self.run_migration()
        self.assertEqual(report['files'], report['verifiedFiles'])
        self.assertEqual(before, {p: digest(p) for p in before})
        self.assertEqual((self.new / 'library' / self.doc / 'source.pdf').read_bytes(), (self.pdf / 'source.pdf').read_bytes())
        self.assertTrue((self.new / 'library' / self.doc / 'requests/attachments/one/image.png').is_file())
        self.assertFalse((self.new / '.env').exists())
        self.assertFalse((self.new / 'scripts').exists())
        self.assertTrue((self.new / 'library/library-organization.json').is_file())

    def test_document_audio_and_billing_keep_identity(self):
        self.run_migration()
        part = self.new / 'library' / self.doc / 'recordings/session-1'
        self.assertTrue((part / 'audio.wav').is_file())
        lecture = json.loads((self.new / 'recordings/lecture-notes/lecture-1.json').read_text())
        self.assertEqual(resolve_path(lecture['parts'][0]['folder'], self.new), part)
        wallet = json.loads((self.new / 'account/credits-wallet.json').read_text())
        self.assertIn(self.operation, wallet['creditOperations'])
        self.assertEqual(wallet['creditCharges']['existing']['operationId'], self.operation)
        self.assertEqual(resolve_path(wallet['creditHolds']['charge-1']['ledgerPath'], self.new), self.new / 'library' / self.doc / 'usage/request.json')
        self.assertEqual(wallet_for_document(self.new / 'library' / self.doc), self.new / 'account/credits-wallet.json')

    def test_moved_store_resolves_audio_and_reusable_paid_cache(self):
        self.run_migration()
        moved = self.base / 'another disk'
        shutil.move(self.new, moved)
        lecture = json.loads((moved / 'recordings/lecture-notes/lecture-1.json').read_text())
        self.assertTrue(resolve_path(lecture['parts'][0]['folder'], moved).is_dir())
        from pdf_semantic import read_json
        result = read_json(moved / 'library' / self.doc / 'generated/paid.json')
        self.assertEqual(Path(result['reusedFrom']), moved / 'library' / self.doc / 'generated')

    def test_repeat_does_not_merge_or_recopy_newer_legacy_data(self):
        self.run_migration()
        self.write(self.new / 'planner/tasks.json', {'title': 'new task'})
        self.write(self.pdf / 'source.pdf', b'changed old copy')
        self.assertEqual(migrate(self.old, self.new, True)['status'], 'already_initialized')
        self.assertEqual((self.new / 'library' / self.doc / 'source.pdf').read_bytes(), b'%PDF-preserve-exact-bytes')
        self.assertTrue((self.new / 'planner/tasks.json').exists())

    def test_conflicting_destination_never_overwritten(self):
        self.write(self.new / 'notes/important.json', {'body': 'preserve'})
        with self.assertRaises(ValueError): self.run_migration()
        self.assertTrue((self.new / 'notes/important.json').exists())

    def test_copy_failure_does_not_publish_partial_store(self):
        with patch('migrate_user_data.shutil.copy2', side_effect=OSError('injected disk failure')):
            with self.assertRaises(OSError): self.run_migration()
        self.assertFalse((self.new / 'manifest.json').exists())
        self.assertTrue((self.pdf / 'source.pdf').exists())

    def test_active_writer_prevents_migration(self):
        with patch('migrate_user_data.legacy_busy', return_value=True):
            with self.assertRaises(RuntimeError): migrate(self.old, self.new, True)
        self.assertFalse(self.new.exists())

    def test_shared_audio_is_not_owned_by_one_document(self):
        note = json.loads((self.old / 'recordings/lecture-notes/lecture-1.json').read_text())
        note.update(id='lecture-2', documentId=None)
        self.write(self.old / 'recordings/lecture-notes/lecture-2.json', note)
        self.run_migration()
        self.assertTrue((self.new / 'recordings/lectures/session-1/audio.wav').exists())

    def test_invalid_authoritative_lecture_manifest_stops_before_copy(self):
        self.write(self.old / 'recordings/lecture-notes/lecture-1.json', b'{broken')
        with self.assertRaises(ValueError): self.run_migration()
        self.assertFalse(self.new.exists())

    def test_reference_escape_is_rejected_and_identity_strings_not_encoded(self):
        self.run_migration()
        for value in ('../outside', '/outside', '..\\outside'):
            with self.assertRaises(ValueError): resolve_path(SCHEME + value, self.new)
        obj = {'operationId': str(self.new / 'recordings'), 'folder': str(self.new / 'recordings')}
        encoded = portable(obj, self.new)
        self.assertEqual(encoded['operationId'], obj['operationId'])
        self.assertEqual(hydrate(encoded, self.new), obj)

    def test_unknown_json_and_unlinked_recordings_are_preserved(self):
        self.write(self.old / '.synesis/unknown/archive.json', b'not valid json')
        (self.old / '.synesis/unknown/empty').mkdir()
        self.write(self.old / 'recordings/unlinked.wav', b'original-wav')
        self.run_migration()
        self.assertEqual((self.new / 'account/unknown/archive.json').read_bytes(), b'not valid json')
        self.assertTrue((self.new / 'account/unknown/empty').is_dir())
        self.assertEqual((self.new / 'recordings/unlinked.wav').read_bytes(), b'original-wav')

    def test_new_store_has_shared_notes_planner_academic_and_settings(self):
        empty = self.base / 'fresh app'; empty.mkdir()
        migrate(empty, self.new, True, check_busy=False)
        for name in ('notes', 'planner', 'academic', 'settings', 'library', 'account'):
            self.assertTrue((self.new / name).is_dir())

if __name__ == '__main__': unittest.main()
