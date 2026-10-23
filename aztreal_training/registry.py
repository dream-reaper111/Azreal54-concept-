"""Candidate references and operator-approved selections; no production replacement."""
import json
from pathlib import Path
import os

from .store import ROOT,folder,read,write,identifier,locked,sha,now


def models():
    import storage_paths
    import ops_api
    base=storage_paths.resolve_model_dir(ROOT)
    existing=ops_api.model_inventory()
    slm_available=any(r.get('available') for r in existing.get('models',[]))
    rows=[{'id':'coding-slm','type':'coding-slm','architecture':'Qwen2ForCausalLM','base_model':'Qwen/Qwen2.5-Coder-1.5B-Instruct',
           'path':str(base),'checkpoint':str(base/'model.safetensors'),'available':slm_available,
           'discovery_source':'existing ops_api.model_inventory',
           'training':'native PyTorch LoRA adapters; QLoRA unavailable until verified','license':'Apache-2.0 (local LICENSE)'}]
    for task in ['secret','exploit']:
        p=ROOT/'models-more'/(task+'.pt')
        rows.append({'id':task+'-classifier','type':'classifier','task':task,'architecture':'HashingVectorizer + 4096/96 MLP',
                     'path':str(p.parent),'checkpoint':str(p),'available':p.is_file(),'training':'supervised classifier'})
    covered={r['checkpoint'] for r in rows}
    for p in sorted(ROOT.glob('models-*/*.pt')):
        if str(p) not in covered:rows.append({'id':p.parent.name+'-'+p.stem,'type':'discovered-classifier','checkpoint':str(p),
                                              'available':True,'training':'Not implemented for this model architecture'})
    selections=read(folder('registry')/'selections.json',{'active':{},'history':[]})
    for r in rows:r['candidate_selection']=selections['active'].get(r['id']);r['deployment_status']='Original production paths unchanged'
    return rows


def model_info(name):
    for r in models():
        if r['id']==name:return r
    raise ValueError('Unknown model identifier')


def checkpoint_manifest(directory):
    p=Path(directory)
    files={}
    for f in sorted(p.glob('*')):
        if f.is_file() and f.name!='integrity.json' and not f.is_symlink():files[f.name]={'sha256':sha(f),'bytes':f.stat().st_size}
    if not files:raise ValueError('Candidate has no checkpoint files')
    write(p/'integrity.json',{'files':files,'created_at':now()})
    return files


def verify(directory):
    p=Path(directory);manifest=read(p/'integrity.json')
    if not manifest:raise ValueError('Candidate checkpoint has no integrity manifest')
    for name,data in manifest['files'].items():
        identifier(name);f=p/name
        if not f.is_file() or f.is_symlink() or sha(f)!=data['sha256']:raise ValueError('Candidate checkpoint integrity failed: '+name)
    return manifest


def promote(job_id,confirmation):
    from .jobs import get
    with locked():
        job=get(job_id)
        if confirmation!=job['model']:raise ValueError('Confirm the model ID explicitly with --confirm MODEL_ID')
        if job['state']!='completed' or not job.get('evaluation'):raise ValueError('Only completed, independently evaluated candidates may be selected')
        if sha(job['base_checkpoint'])!=job['base_sha256']:raise ValueError('Original checkpoint changed after candidate evaluation')
        if job['evaluation'].get('dataset_split')!='test':raise ValueError('Held-out test evaluation is required')
        verify(Path(job['directory'])/'checkpoints')
        p=folder('registry')/'selections.json';data=read(p,{'active':{},'history':[]})
        previous=data['active'].get(job['model'])
        selection={'job':job_id,'checkpoint':job['checkpoint'],'at':now(),'approved_by_uid':os.getuid(),
                   'deployment_status':'selected candidate only; production deployment not changed'}
        data['history'].append({'model':job['model'],'previous':previous,'selected':selection});data['active'][job['model']]=selection
        write(p,data)
        return selection


def rollback(model,confirmation):
    if confirmation!=model:raise ValueError('Confirm the model ID explicitly with --confirm MODEL_ID')
    with locked():
        p=folder('registry')/'selections.json';data=read(p,{'active':{},'history':[]})
        history=next((x for x in reversed(data['history']) if x['model']==model and not x.get('rolled_back')),None)
        if history is None:raise ValueError('No candidate-selection rollback reference')
        previous=history['previous']
        if previous:
            from .jobs import get
            verify(Path(get(previous['job'])['directory'])/'checkpoints')
            data['active'][model]=previous
        else:data['active'].pop(model,None)
        history['rolled_back']=now();write(p,data)
        return {'model':model,'selected':previous,'production_weights_modified':False}
