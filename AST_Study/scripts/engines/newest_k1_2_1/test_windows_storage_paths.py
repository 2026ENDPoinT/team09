"""Reproduce the shipped Windows path failure without paid calls or personal data."""
import errno
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pdf_pipeline import read_json_cache, write_json
from pdf_semantic import read_json
from synesis_paths import extended_windows_path, io_path, portable, hydrate, SCHEME


class WindowsStoragePathsTest(unittest.TestCase):
    def test_drive_unc_unicode_and_existing_prefix(self):
        cases={
            'C:/Users/민서/자료/../자료/file.json':r'\\?\C:\Users\민서\자료\file.json',
            r'\\server\share\folder\file.json':r'\\?\UNC\server\share\folder\file.json',
            r'\\?\C:\data\file.json':r'\\?\C:\data\file.json',
            r'\\?\UNC\server\share\file.json':r'\\?\UNC\server\share\file.json',
        }
        for value,expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(extended_windows_path(value),expected)
                self.assertEqual(extended_windows_path(expected),expected)

    @unittest.skipIf(os.name=='nt','This fixture emulates the unprefixed legacy limit on a POSIX host.')
    def test_shipped_temporary_name_fails_but_atomic_writer_survives_260_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            parent=Path(directory)/('a'*64)/('b'*64)
            parent=parent/('c'*(228-len(str(parent))-1))
            parent.mkdir(parents=True)
            target=parent/'blocks.json'
            old_temp=target.with_name(target.name+'.12345.'+'d'*32+'.tmp')
            self.assertLess(len(str(target)),260)
            self.assertGreaterEqual(len(str(old_temp)),260)
            real_io_open,real_os_open=io.open,os.open
            def check(path):
                if not isinstance(path,int) and len(os.fspath(path))>=260:
                    raise FileNotFoundError(errno.ENOENT,'Simulated Windows MAX_PATH',os.fspath(path))
            def limited_io_open(path,*args,**kwargs):
                check(path);return real_io_open(path,*args,**kwargs)
            def limited_os_open(path,*args,**kwargs):
                check(path);return real_os_open(path,*args,**kwargs)
            with patch('io.open',side_effect=limited_io_open),patch('os.open',side_effect=limited_os_open):
                with self.assertRaises(FileNotFoundError):old_temp.write_text('{}')
                write_json(target,{'body':'원문 보존','revision':1})
                write_json(target,{'body':'원문 보존','revision':2})
                self.assertEqual(read_json_cache(target)['revision'],2)
                self.assertEqual(read_json(target)['body'],'원문 보존')
            self.assertEqual(list(parent.iterdir()),[target])

    def test_failed_replacement_preserves_old_result_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'result.json';write_json(target,{'paid':'existing'})
            with patch('pdf_pipeline.os.replace',side_effect=OSError(errno.EIO,'disk failure')):
                with self.assertRaises(OSError):write_json(target,{'paid':'replacement'})
            self.assertEqual(read_json_cache(target),{'paid':'existing'})
            self.assertEqual(list(Path(directory).iterdir()),[target])

    def test_transient_windows_lock_retries_then_publishes(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'result.json';replace=os.replace;calls=[]
            def locked_once(source,destination):
                calls.append(1)
                if len(calls)==1:raise PermissionError(errno.EACCES,'scanner lock')
                return replace(source,destination)
            with patch('pdf_pipeline.os.replace',side_effect=locked_once),patch('pdf_pipeline.time.sleep'):
                write_json(target,{'done':True})
            self.assertEqual(len(calls),2);self.assertTrue(read_json(target)['done'])

    def test_deep_io_and_portable_references_keep_existing_store_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root=io_path(directory).resolve()
            (root/'manifest.json').write_text(json.dumps({'format':'synesis-user-data','version':1}))
            folder=root/'library'/('a'*64)/'generated'/'new-concept-v99'/('b'*64)
            while len(str(folder))<330:folder=folder/'deep-result'
            source=root/'library'/('a'*64)/'source.pdf'
            target=folder/'result.json';value={'path':str(source),'body':'보존된 설명'}
            write_json(target,value)
            raw=json.loads(target.read_text(encoding='utf-8'))
            self.assertTrue(raw['path'].startswith(SCHEME))
            self.assertEqual(hydrate(raw,target),value)
            self.assertEqual(portable(value,target),raw)
            self.assertEqual(read_json_cache(target),value)


if __name__=='__main__':unittest.main()
