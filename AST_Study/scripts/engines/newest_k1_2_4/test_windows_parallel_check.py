"""No-network concurrency probe and Windows locking-call contract."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pdf_api_slots as slots
from windows_parallel_check import check_parallel_slots


class WindowsParallelCheckTest(unittest.TestCase):
    def test_four_processes_share_two_native_slots(self):
        with tempfile.TemporaryDirectory() as directory:
            result=check_parallel_slots(Path(directory))
            self.assertEqual(result['completed'],4)
            self.assertTrue(result['blockedUntilRelease'])
            self.assertEqual(result['remoteRequests'],0)
            self.assertEqual(list(Path(directory).iterdir()),[])

    def test_windows_locks_one_byte_at_offset_zero_and_handles_contention(self):
        calls=[]
        with tempfile.TemporaryFile('w+b') as handle:
            handle.write(b'0');handle.flush()
            def locking(fd,mode,size):
                calls.append((fd,mode,size,os.lseek(fd,0,os.SEEK_CUR)))
            native=SimpleNamespace(LK_NBLCK=2,LK_UNLCK=0,locking=locking)
            with patch.object(slots,'os',SimpleNamespace(name='nt')),patch.dict('sys.modules',{'msvcrt':native}):
                self.assertTrue(slots._try_lock(handle));slots._unlock(handle)
                self.assertEqual([(row[1],row[2],row[3]) for row in calls],[(2,1,0),(0,1,0)])
                def busy(*args):raise OSError('lock held by another process')
                native.locking=busy
                self.assertFalse(slots._try_lock(handle))


if __name__=='__main__':unittest.main()
