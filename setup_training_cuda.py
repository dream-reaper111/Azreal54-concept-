"""Prepare a small linked training venv from existing CUDA and project packages.

Does not download, replace packages, or alter the application environment.
Run with the host Python that already imports the desired CUDA torch build.
"""
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import subprocess
import sys
import venv
from datetime import datetime,timezone


ROOT=Path(__file__).resolve().parent


def installed_roots(dist):
    if dist.files:
        return {Path(str(f)).parts[0] for f in dist.files if Path(str(f)).parts and Path(str(f)).parts[0]!='..'}
    # Debian egg-info distributions may have no RECORD/SOURCES list.
    names=set()
    for name in (dist.read_text('top_level.txt') or '').splitlines():
        if not name.isidentifier():raise ValueError('Invalid installed top-level package name')
        if Path(dist.locate_file(name)).exists():names.add(name)
        elif Path(dist.locate_file(name+'.py')).exists():names.add(name+'.py')
    info=Path(dist._path)
    if info.parent!=Path(dist.locate_file('')):raise ValueError('Unexpected installed metadata location')
    names.add(info.name)
    if len(names)<2:raise ValueError('Installed distribution has no package file inventory: '+dist.metadata['Name'])
    return names


def main():
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
    import torch
    if not torch.version.cuda:raise ValueError('Run with a Python that already has a CUDA-enabled torch installation')
    target=ROOT/'.training-venv'
    if target.exists():raise ValueError('Training venv already exists; preserving it without changes')
    baseline=ROOT/'.slm-venv/lib'/f'python{sys.version_info.major}.{sys.version_info.minor}'/'site-packages'
    if not baseline.is_dir():raise ValueError('Matching project Python dependencies are unavailable')
    # Resolve installed requirements, including CUDA toolkit extras, before writes.
    selected={};extras={'torch':set()};queue=['torch']
    while queue:
        key=queue.pop();dist=metadata.distribution(key);selected[key]=dist
        for text in dist.requires or []:
            req=Requirement(text)
            if req.marker and not any(req.marker.evaluate({'extra':extra}) for extra in (extras[key] or {''})):continue
            name=canonicalize_name(req.name);dependency=metadata.distribution(name)
            if req.specifier and dependency.version not in req.specifier:
                raise ValueError(f'Existing dependency mismatch: {req.name} {dependency.version} does not satisfy {req.specifier}')
            first=name not in extras;previous=extras.get(name,set());updated=previous|set(req.extras)
            if first or updated!=previous:
                extras[name]=updated;queue.append(name)
    roots={};distributions=[]
    for name,dist in sorted(selected.items()):
        packages=installed_roots(dist)
        for package in packages:
            source=Path(dist.locate_file(package)).absolute()
            if not source.exists():raise ValueError('Missing installed package path: '+str(source))
            if package in roots and roots[package]!=source:raise ValueError('Conflicting namespace providers: '+package)
            roots[package]=source
        distributions.append({'name':name,'version':dist.version,'source':str(dist.locate_file('')),
             'metadata_sha256':hashlib.sha256((dist.read_text('METADATA') or dist.read_text('PKG-INFO') or '').encode()).hexdigest()})
    excluded=set(roots)
    for dist in metadata.distributions(path=[str(baseline)]):
        if canonicalize_name(dist.metadata['Name']) in selected:
            excluded.update(installed_roots(dist))
    venv.EnvBuilder(with_pip=False,symlinks=True).create(target)
    site=target/'lib'/f'python{sys.version_info.major}.{sys.version_info.minor}'/'site-packages'
    links=[]
    for source in sorted(baseline.iterdir()):
        if source.name in excluded or source.name=='__pycache__':continue
        (site/source.name).symlink_to(source,target_is_directory=source.is_dir());links.append({'name':source.name,'source':str(source)})
    for name,source in sorted(roots.items()):
        (site/name).symlink_to(source,target_is_directory=source.is_dir());links.append({'name':name,'source':str(source)})
    probe='import json,sys,torch,transformers,sklearn,importlib.metadata as m; expected=json.loads(sys.argv[1]); assert all(m.version(n)==v for n,v in expected.items()); x=torch.ones(8,8); assert (x@x)[0,0].item()==8; print(json.dumps(dict(python=sys.executable,torch=torch.__version__,cuda_build=torch.version.cuda,cuda_available=torch.cuda.is_available(),transformers=transformers.__version__,sklearn=sklearn.__version__,compiled_targets=torch._C._cuda_getArchFlags())))'
    expected=json.dumps({d['name']:d['version'] for d in distributions})
    process=subprocess.run([str(target/'bin/python'),'-I','-B','-c',probe,expected],capture_output=True,text=True,timeout=60)
    if process.returncode:raise ValueError('Linked environment probe failed; it remains inactive: '+process.stderr[-1500:])
    measured=json.loads(process.stdout)
    if measured['torch']!=torch.__version__ or measured['cuda_build']!=torch.version.cuda:raise ValueError('CUDA build selection mismatch; environment remains inactive')
    manifest={'status':'ready','created_at':datetime.now(timezone.utc).isoformat(),'probe':measured,
        'method':'Read-only symlink reuse of existing installed packages; application venv unchanged',
        'cuda_distributions':distributions,'links':links,'gpu_training_verified':False}
    marker=target/'aztreal-runtime.json';marker.write_text(json.dumps(manifest,indent=2)+'\n');marker.chmod(0o600)
    print(json.dumps(measured,indent=2))


if __name__=='__main__':
    try:main()
    except (ValueError,OSError,metadata.PackageNotFoundError) as error:
        print(str(error),file=sys.stderr);raise SystemExit(2)
