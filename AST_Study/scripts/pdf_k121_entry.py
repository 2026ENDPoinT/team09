"""Private K1.2.1 runtime. Existing engines keep their original dependencies."""
import os
from pathlib import Path
import runpy
import sys
root=Path(__file__).resolve().parent
os.environ.setdefault('SYNESIS_APP_ROOT',str(root.parent))
sys.path.insert(0,str(root/'engines/newest_k1_2_1'))
if __name__=='__main__':
    # pdf_ai aliases __main__ for shared Provider/exception identities. Register
    # the executed module, rather than this launcher, for helper imports.
    runpy.run_module('pdf_ai',run_name='__main__',alter_sys=True)
