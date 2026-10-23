"""Choose a prepared training interpreter without changing the application venv."""
import json
import os
from pathlib import Path


def interpreter(root):
    override=os.environ.get('AZTREAL_PYTHON')
    if override:
        python=Path(override).expanduser()
        if not python.is_absolute() or not python.is_file() or not os.access(python,os.X_OK):
            raise ValueError('AZTREAL_PYTHON must be an absolute executable Python path')
        return python
    candidate=Path(root)/'.training-venv'
    marker=candidate/'aztreal-runtime.json'
    if marker.is_file():
        try:ready=json.loads(marker.read_text()).get('status')=='ready'
        except (ValueError,OSError):ready=False
        if ready and (candidate/'bin/python').is_file():return candidate/'bin/python'
    return Path(root)/'.slm-venv/bin/python'
