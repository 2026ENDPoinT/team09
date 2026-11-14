import io,threading,unittest
from unittest.mock import patch
import pdf_worker_control as control
import pdf_pipeline

class WorkerControlTests(unittest.TestCase):
 def setUp(self):
  for name,value in [('_CANCEL',threading.Event()),('_LOCK',threading.Lock()),('_JOBS',{}),('_REQUESTED',set()),('_STARTED',False)]:
   p=patch.object(control,name,value);p.start();self.addCleanup(p.stop)
 def test_cancel_is_local_persistent_and_does_not_depend_on_a_reused_folder_marker(self):
  from tempfile import TemporaryDirectory
  from pathlib import Path
  with TemporaryDirectory()as tmp:
   control.cancel()
   with self.assertRaises(InterruptedError):pdf_pipeline.check_cancel(Path(tmp))
   # A new upload clearing/reusing its folder cannot revive this old process.
   with self.assertRaises(InterruptedError):pdf_pipeline.check_cancel(Path(tmp))
 def test_cancelled_background_jobs_are_stopped_once_without_holding_registry_lock(self):
  done=threading.Event();calls=[]
  def stop():
   calls.append('original');control.unregister('job');done.set()
  control.register('job',stop);control.cancel();control.cancel()
  self.assertTrue(done.wait(2));self.assertEqual(calls,['original'])
 def test_late_acknowledgement_after_cancellation_is_also_stopped(self):
  control.cancel();done=threading.Event();control.register('late',done.set)
  self.assertTrue(done.wait(2))
 def test_desktop_closing_its_pipe_cancels_without_an_explicit_command(self):
  control.start(io.StringIO(''))
  self.assertTrue(control._CANCEL.wait(2))
 def test_stdin_control_requires_the_exact_cancel_command(self):
  control.start(io.StringIO('invalid\n{"command":"continue"}\n{"command":"cancel"}\n'))
  self.assertTrue(control._CANCEL.wait(2))
 def test_completed_job_is_not_cancelled_when_the_desktop_later_exits(self):
  calls=[];control.register('done',lambda:calls.append('wrong'));control.unregister('done');control.cancel()
  self.assertFalse(calls)

if __name__=='__main__':unittest.main()
