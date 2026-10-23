"""Private atomic JSON state and serialized registry/resource transactions."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

ROOT=Path(__file__).resolve().parents[1]


def now():return datetime.now(timezone.utc).isoformat()


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def identifier(value):
    if not isinstance(value,str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,100}',value):
        raise ValueError('Invalid identifier; use letters, digits, dots, underscores or hyphens')
    return value


def state_root():
    configured=os.environ.get('AZTREAL_STATE_DIR')
    preferred=Path('/data/work/azrael54/training')
    path=Path(configured).expanduser() if configured else (preferred/'aztrealcli' if os.access(preferred,os.W_OK) else ROOT/'training-state')
    if not path.is_absolute() or path.is_symlink() or path.resolve().is_relative_to('/tmp'):
        raise ValueError('State must use an absolute persistent directory, outside /tmp, without symlinks')
    if not (path.resolve().is_relative_to(ROOT) or path.resolve().is_relative_to('/data')):
        raise ValueError('Training state must remain inside the project or /data')
    # Existing directories are validated rather than re-owned or made writable.
    path.mkdir(parents=True,exist_ok=True,mode=0o700)
    s=path.stat()
    if s.st_uid!=os.getuid() or s.st_mode&0o077:
        raise ValueError('Training state must be owned by this user and have mode 0700')
    return path.resolve()


def folder(kind):
    p=state_root()/identifier(kind)
    if p.is_symlink():raise ValueError('State directories cannot be symlinks')
    p.mkdir(exist_ok=True,mode=0o700)
    return p


def read(path,default=None):
    p=Path(path)
    if p.is_symlink():raise ValueError('State files cannot be symlinks')
    return json.loads(p.read_text()) if p.exists() else default


def write(path,value):
    p=Path(path)
    if p.is_symlink() or not p.resolve().is_relative_to(state_root()):raise ValueError('Unsafe state destination')
    fd,name=tempfile.mkstemp(prefix='.state-',dir=p.parent)
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump(value,stream,indent=2,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())
        os.replace(name,p)
        dfd=os.open(p.parent,os.O_RDONLY)
        try:os.fsync(dfd)
        finally:os.close(dfd)
    finally:
        if Path(name).exists():Path(name).unlink()


@contextmanager
def locked():
    p=state_root()/'.lock'
    fd=os.open(p,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'r+') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX)
        try:yield
        finally:fcntl.flock(stream,fcntl.LOCK_UN)


def redacted(error):
    text=str(error)
    text=re.sub(r'(?i)(token|password|secret|api_key)(\s*[=:]\s*)\S+',r'\1\2[REDACTED]',text)
    text=re.sub(r'\b(?:hf_|ghp_|sk_live_)[A-Za-z0-9_-]{12,}\b','[REDACTED]',text)
    return text[-2000:]
