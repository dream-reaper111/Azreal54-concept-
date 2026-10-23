"""Shared AZRAEL storage layout, legacy read paths, and fail-closed host preflight."""
import os
from pathlib import Path
import shutil
import tempfile


DEFAULT_STORAGE_ROOT = Path('/data/work/azrael54')
PRIVATE_DIRS = (
    'datasets', 'models/slm', 'checkpoints', 'evidence', 'artifacts',
    'role-research', 'council', 'poc-candidates', 'directives', 'setup',
    'training', 'training/models-public', 'training/models-domains',
    'training/models-automotive', 'training/models-research',
    'training/models-specialists', 'training/models-more',
    'juice-shop-data', 'juice-shop-logs', 'juice-shop-ftp', 'juice-shop-csaf',
    'juice-shop-frontend', 'juice-shop-i18n',
    'cache/huggingface', 'cache/torch', 'cache/pip', 'tmp',
)


def storage_root(project_root=None):
    return Path(os.environ.get('AZRAEL_STORAGE_ROOT', str(DEFAULT_STORAGE_ROOT))).expanduser()


def _configured(variable, relative):
    explicit=os.environ.get(variable)
    if explicit:return Path(explicit).expanduser()
    return storage_root()/relative


def dataset_root(project_root):
    if os.environ.get('AZRAEL_DATASET_DIR') or os.environ.get('AZRAEL_STORAGE_ROOT'):
        return _configured('AZRAEL_DATASET_DIR','datasets')
    return Path(project_root)/'data'


def legacy_dataset_root(project_root):
    return Path(os.environ.get('AZRAEL_LEGACY_DATASET_DIR',str(Path(project_root)/'data'))).expanduser()


def dataset_file(name, project_root):
    if Path(name).is_absolute() or '..' in Path(name).parts:
        raise ValueError('Dataset name must stay within a configured dataset directory')
    primary=dataset_root(project_root)/name
    if primary.is_file():return primary
    legacy=legacy_dataset_root(project_root)/name
    if legacy.is_file():return legacy
    return primary


def data_path(project_root, name):
    """Resolve shared input data, preferring the configured store and retaining legacy reads."""
    if Path(name).is_absolute() or '..' in Path(name).parts:
        raise ValueError('Data name must stay within a configured data directory')
    return dataset_file(name, project_root)


def training_root(project_root, category):
    """One output directory per trainer; no copies per role."""
    if not category or '/' in category or '..' in category:
        raise ValueError('Invalid training output category')
    if os.environ.get('AZRAEL_TRAINING_DIR'):
        base=Path(os.environ['AZRAEL_TRAINING_DIR']).expanduser()
    elif os.environ.get('AZRAEL_STORAGE_ROOT'):
        base=storage_root()/'training'
    else:
        return Path(project_root)/category
    return base/category


def training_file(project_root, category, name):
    if Path(name).is_absolute() or '..' in Path(name).parts:
        raise ValueError('Training output name must stay within its category')
    primary=training_root(project_root,category)/name
    if primary.is_file():return primary
    legacy=Path(project_root)/category/name
    return legacy if legacy.is_file() else primary


def artifact_path(project_root, *parts):
    base=artifacts_root(project_root)
    candidate=base.joinpath(*parts)
    if not candidate.resolve().is_relative_to(base.resolve()):
        raise ValueError('Artifact path escapes configured storage')
    return candidate


def _policy_int(name, default, minimum, maximum):
    raw=os.environ.get(name)
    if raw is None:return default
    try:value=int(raw)
    except ValueError as error:raise ValueError(f'{name} must be an integer') from error
    if not minimum<=value<=maximum:raise ValueError(f'{name} must be between {minimum} and {maximum}')
    return value


def evidence_policy():
    return {'retention_days':_policy_int('AZRAEL_EVIDENCE_RETENTION_DAYS',30,1,3650),
            'max_records':_policy_int('AZRAEL_EVIDENCE_MAX_RECORDS',10000,100,1000000),
            'cleanup':'manual_admin_action_only'}


def storage_status(path=None):
    """Read-only capacity and mount report; never creates files or changes permissions."""
    root=Path(path or storage_root()).expanduser()
    probe=root
    while not probe.exists() and probe!=probe.parent:probe=probe.parent
    try:usage=shutil.disk_usage(probe)
    except OSError:usage=None
    mount=mount_for(root)
    minimum_gb=_policy_int('AZRAEL_STORAGE_MIN_FREE_GB',20,1,100000)
    free=usage.free if usage else None
    writable=bool(root.exists() and os.access(root,os.W_OK|os.X_OK))
    return {'configured_root':str(root),'exists':root.exists(),'writable_for_current_user':writable,
            'mount':mount,'total_bytes':usage.total if usage else None,
            'used_bytes':usage.used if usage else None,'available_bytes':free,
            'minimum_free_gb':minimum_gb,
            'capacity_status':'warning' if free is not None and free < minimum_gb*1024**3 else ('ok' if free is not None else 'unknown'),
            'retention':evidence_policy(),'destructive_cleanup':'disabled_automatically'}


def artifacts_root(project_root=None):
    if os.environ.get('AZRAEL_ARTIFACTS_DIR'):
        return Path(os.environ['AZRAEL_ARTIFACTS_DIR']).expanduser()
    if os.environ.get('AZRAEL_STORAGE_ROOT'):
        return storage_root()/'artifacts'
    return Path(project_root or Path(__file__).resolve().parent)/'artifacts'


def evidence_root(project_root=None):
    if os.environ.get('AZRAEL_EVIDENCE_DIR'):
        return Path(os.environ['AZRAEL_EVIDENCE_DIR']).expanduser()
    if os.environ.get('AZRAEL_STORAGE_ROOT'):
        return storage_root()/'evidence'
    return Path(project_root or Path(__file__).resolve().parent)/'artifacts'/'evidence'


def checkpoint_root(project_root=None, category=None):
    if os.environ.get('AZRAEL_CHECKPOINT_DIR'):
        base=Path(os.environ['AZRAEL_CHECKPOINT_DIR']).expanduser()
    elif os.environ.get('AZRAEL_STORAGE_ROOT'):
        base=storage_root()/'checkpoints'
    else:
        base=Path(project_root or Path(__file__).resolve().parent)
    return base/category if category else base


def checkpoint_file(project_root, category, name):
    if Path(name).is_absolute() or '..' in Path(name).parts:
        raise ValueError('Checkpoint name must stay within its configured category')
    primary=checkpoint_root(project_root,category)/name
    if primary.is_file():return primary
    legacy=training_root(project_root,category)/name
    if legacy.is_file():return legacy
    project_legacy=Path(project_root or Path(__file__).resolve().parent)/category/name
    return project_legacy if project_legacy.is_file() else primary


def model_write_root(project_root=None):
    if os.environ.get('AZRAEL_MODEL_DIR'):
        return Path(os.environ['AZRAEL_MODEL_DIR']).expanduser()
    return storage_root()/'models'/'slm'


def cache_root():
    return Path(os.environ.get('AZRAEL_CACHE_DIR',str(storage_root()/'cache'))).expanduser()


def model_read_roots(project_root):
    roots=[model_write_root(project_root)]
    legacy=Path(os.environ.get('AZRAEL_LEGACY_MODEL_DIR',str(Path(project_root)/'.slm-model'))).expanduser()
    if legacy not in roots:roots.append(legacy)
    return roots


def resolve_model_dir(project_root):
    for candidate in model_read_roots(project_root):
        if (candidate/'config.json').is_file() and (candidate/'model.safetensors').is_file():
            return candidate
    return model_write_root(project_root)


def model_manifest(model_dir, project_root):
    model_dir=Path(model_dir)
    candidate=model_dir/'manifest.json'
    if candidate.is_file():return candidate
    legacy=Path(project_root)/'slm-model-manifest.json'
    return legacy if model_dir in model_read_roots(project_root) and legacy.is_file() else candidate


def mount_for(path):
    """Return the longest matching Linux mountpoint and its mount options."""
    target=Path(path).absolute()
    best=None
    try:lines=Path('/proc/self/mountinfo').read_text().splitlines()
    except OSError:return None
    for line in lines:
        fields=line.split()
        if len(fields)<6:continue
        mountpoint=Path(fields[4].replace('\\040',' ').replace('\\011','\t').replace('\\134','\\'))
        try:target.relative_to(mountpoint)
        except ValueError:continue
        if best is None or len(str(mountpoint))>len(str(best['target'])):
            separator=fields.index('-') if '-' in fields else len(fields)
            options=set(fields[5].split(','))
            filesystem_options=set(fields[separator+3].split(',')) if separator+3<len(fields) else set()
            best={'target':str(mountpoint),'options':sorted(options),
                  'filesystem_options':sorted(filesystem_options),'read_only':'ro' in options}
    return best


def prepare_storage(path=None):
    """Create only new AZRAEL directories, enforce private ownership, and test real writes."""
    root=Path(path or storage_root()).expanduser()
    if not root.is_absolute():raise ValueError('AZRAEL_STORAGE_ROOT must be an absolute path')
    if root.is_symlink():raise ValueError('AZRAEL storage root cannot be a symlink')
    mount=mount_for(root)
    if mount and mount['read_only']:
        raise PermissionError(f"AZRAEL storage is on read-only mount {mount['target']} ({','.join(mount['options'])})")
    parent=root.parent
    if not root.exists():
        if not parent.is_dir() or not os.access(parent,os.W_OK|os.X_OK):
            raise PermissionError(f'Cannot create AZRAEL storage directory beneath {parent}; verify the host mount and user permissions')
        root.mkdir(mode=0o700)
    status=root.lstat()
    if not root.is_dir() or status.st_uid!=os.getuid():
        raise PermissionError(f'AZRAEL storage root must be a directory owned by uid {os.getuid()}: {root}')
    if status.st_mode&0o077:
        raise PermissionError(f'AZRAEL storage root permissions must be private (0700): {root}')
    for relative in PRIVATE_DIRS:
        current=root
        for part in Path(relative).parts:
            current=current/part
            if current.is_symlink():raise ValueError(f'AZRAEL storage path cannot contain symlinks: {current}')
            if not current.exists():current.mkdir(mode=0o700)
            info=current.lstat()
            if not current.is_dir() or info.st_uid!=os.getuid() or info.st_mode&0o077:
                raise PermissionError(f'AZRAEL storage directory must be owned by uid {os.getuid()} and private (0700): {current}')
    test_dir=root/'tmp'
    fd,name=tempfile.mkstemp(prefix='.write-test-',dir=test_dir)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(b'AZRAEL_STORAGE_WRITE_TEST\n');stream.flush();os.fsync(stream.fileno())
        if Path(name).read_bytes()!=b'AZRAEL_STORAGE_WRITE_TEST\n':
            raise OSError('AZRAEL storage write verification did not read back the test bytes')
    finally:
        try:Path(name).unlink()
        except FileNotFoundError:pass
    usage=shutil.disk_usage(root)
    return {'root':str(root),'owner_uid':status.st_uid,'mode':oct(status.st_mode&0o777),
            'mount':mount,'write_readback':'passed','temporary_probe_removed':True,
            'available_bytes':usage.free,'required_directories':[str(root/path) for path in PRIVATE_DIRS]}


def configure_cache_environment(root=None):
    base=Path(root or storage_root())
    cache=Path(os.environ.get('AZRAEL_CACHE_DIR',str(base/'cache')))
    os.environ['HF_HOME']=os.environ.get('AZRAEL_HF_HOME',str(cache/'huggingface'))
    os.environ['HUGGINGFACE_HUB_CACHE']=str(Path(os.environ['HF_HOME'])/'hub')
    os.environ['TORCH_HOME']=os.environ.get('AZRAEL_TORCH_HOME',str(cache/'torch'))
    os.environ['XDG_CACHE_HOME']=str(cache)
    os.environ['PIP_CACHE_DIR']=os.environ.get('AZRAEL_PIP_CACHE_DIR',str(cache/'pip'))
    os.environ['TMPDIR']=os.environ.get('AZRAEL_TMP_DIR',str(base/'tmp'))
