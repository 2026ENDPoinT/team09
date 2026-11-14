"""Private K1.2.2 runtime; legacy engine dependencies stay isolated."""
import os
from pathlib import Path
import runpy
import sys

root=Path(__file__).resolve().parent
os.environ.setdefault('SYNESIS_APP_ROOT',str(root.parent))
sys.path.insert(0,str(root/'engines/newest_k1_2_2'))
if __name__=='__main__':
    runpy.run_module('pdf_ai',run_name='__main__',alter_sys=True)
