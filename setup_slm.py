"""Explicit online setup; inference remains local and offline."""
import hashlib
import json
from pathlib import Path
import os
import storage_paths

ROOT=Path(__file__).resolve().parent
MODEL='Qwen/Qwen2.5-Coder-1.5B-Instruct'

def sha256(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    path=storage_paths.model_write_root(ROOT)
    manifest=path/'manifest.json'
    legacy_manifest=ROOT/'slm-model-manifest.json'
    source=manifest if manifest.is_file() else legacy_manifest
    if not source.is_file():raise ValueError('A pinned local model manifest is required before an explicit download')
    pinned=json.loads(source.read_text())
    revision=pinned['revision']
    if pinned.get('model')!=MODEL:raise ValueError('Pinned manifest identifies a different model')
    if (path/'model.safetensors').is_file():
        expected=pinned.get('files',{})
        if not expected:raise ValueError('Existing model has no integrity hashes')
        for name,expected_sha in expected.items():
            relative=Path(name)
            if relative.is_absolute() or '..' in relative.parts:raise ValueError('Model manifest path escapes checkpoint directory')
            if name=='manifest.json':continue
            candidate=path/relative
            if not candidate.is_file() or sha256(candidate)!=expected_sha:
                raise ValueError('Existing local model failed integrity checks; preserve it before explicit restoration')
        print('Verified existing local SLM:',MODEL,revision,flush=True)
        return
    storage_paths.configure_cache_environment()
    os.environ['HF_HUB_DISABLE_XET']='1'
    from huggingface_hub import snapshot_download
    path.mkdir(parents=True,exist_ok=True,mode=0o700)
    snapshot_download(MODEL,revision=revision,local_dir=path,
        allow_patterns=['*.json','*.safetensors','*.txt','*.jinja','LICENSE','README.md'],max_workers=2)
    files={str(p.relative_to(path)):sha256(p) for p in path.rglob('*')
           if p.is_file() and '.cache' not in p.parts and p!=manifest}
    manifest.write_text(json.dumps({'model':MODEL,'revision':revision,'source':'https://huggingface.co/'+MODEL,
        'files':files,'purpose':'Shared coding/admin/coordination service; specialist role contracts remain distinct'},indent=2)+'\n')
    print('Downloaded and pinned local SLM:',MODEL,revision,flush=True)


if __name__=='__main__':main()
