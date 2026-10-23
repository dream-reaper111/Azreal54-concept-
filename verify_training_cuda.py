#!/usr/bin/env python3
"""Run bounded sequential CUDA verification using the prepared CLI interpreter."""
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from aztreal_training.runtime import interpreter
python=interpreter(ROOT)
if Path(sys.executable).absolute()!=python.absolute():
    os.execv(str(python),[str(python),'-B',str(ROOT/'verify_training_cuda.py'),*sys.argv[1:]])
from aztreal_training.verify_cuda import main
raise SystemExit(main())
