"""Local datasets: bounded parsing, provenance, explicit admission and frozen splits."""
from collections import Counter,defaultdict
import csv
import hashlib
import io
import json
from pathlib import Path
import random
import re

from .store import folder,identifier,read,write,sha,now,locked

LIMIT=32*1024*1024


def secret(text):
    return bool(re.search(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\b(?:ghp_|hf_|sk_live_)[A-Za-z0-9_-]{16,}|\bAKIA[A-Z0-9]{16}\b|(?i:password|api_key|access_token)\s*[=:]\s*[\"\']?[^\s\"\']{12,}',text))


def validate(path,kind='auto'):
    path=Path(path).expanduser()
    if not path.is_file() or path.stat().st_size>LIMIT:raise ValueError('Dataset must be a local file of at most 32 MiB')
    raw=path.read_bytes()
    try:text=raw.decode('utf-8-sig',errors='strict')
    except UnicodeError:raise ValueError('Dataset must be valid UTF-8') from None
    if path.suffix.lower()=='.csv':rows=list(csv.DictReader(io.StringIO(text)))
    elif path.suffix.lower()=='.json':
        rows=json.loads(text)
        if isinstance(rows,dict):rows=rows.get('data',rows.get('records'))
    elif path.suffix.lower()=='.jsonl':rows=[json.loads(line) for line in text.splitlines() if line.strip()]
    else:raise ValueError('Supported formats: .jsonl, .json, .csv')
    if not isinstance(rows,list) or not rows or len(rows)>100000:raise ValueError('Expected 1–100000 dataset records')
    normalized=[];seen={};duplicates=0;errors=[];sensitive=0
    for index,row in enumerate(rows,1):
        if not isinstance(row,dict):errors.append({'row':index,'error':'Expected object'});continue
        instruction=row.get('instruction',row.get('prompt'))
        output=row.get('response',row.get('output',row.get('completion')))
        rowkind='slm' if instruction is not None else 'classifier'
        if kind not in {'auto',rowkind}:errors.append({'row':index,'error':'Dataset kind mismatch'});continue
        if rowkind=='slm':
            value={'instruction':instruction,'response':output,'kind':'slm'}
            if isinstance(row.get('input'),str) and row['input']:value['instruction']=str(instruction)+'\n'+row['input']
            values=[value['instruction'],value['response']]
        else:
            value={'text':row.get('text',row.get('description')),'label':row.get('label',row.get('type')),'kind':'classifier'}
            values=[value['text'],value['label']]
        if not all(isinstance(x,str) and 0<len(x.strip())<=16384 for x in values):
            errors.append({'row':index,'error':'Nonempty text fields, at most 16384 characters, required'});continue
        # Secret-detector training may describe placeholders, never real credentials.
        if any(secret(v) for v in values):sensitive+=1;errors.append({'row':index,'error':'Sensitive-looking content requires removal; values withheld'});continue
        identity=value.get('text',value.get('instruction'))
        key=hashlib.sha256(identity.encode()).hexdigest()
        if key in seen:
            if seen[key]!=value:errors.append({'row':index,'error':'Conflicting labels/responses for identical input'})
            else:duplicates+=1
            continue
        seen[key]=dict(value);value['id']=key;normalized.append(value)
    kinds={r['kind'] for r in normalized}
    if len(kinds)!=1:errors.append({'error':'Use a single dataset type per version'})
    report={'valid':not errors,'format':path.suffix.lower(),'input_sha256':hashlib.sha256(raw).hexdigest(),
        'records':len(normalized),'duplicates_removed':duplicates,'sensitive_rows':sensitive,'errors':errors[:30],
        'kind':next(iter(kinds)) if len(kinds)==1 else 'unknown','labels':dict(Counter(r['label'] for r in normalized if 'label' in r))}
    return report,normalized


def import_data(path,kind,source,license_id,synthetic,approve=False,reviewer=None):
    report,rows=validate(path,kind)
    if not report['valid']:raise ValueError('Dataset validation failed: '+json.dumps(report['errors']))
    if not source or not license_id or synthetic not in {'yes','no','model-generated'}:raise ValueError('Source, license and explicit synthetic status required')
    if any(len(str(x))>1024 or secret(str(x)) for x in [source,license_id,reviewer or '']):raise ValueError('Metadata is too long or contains sensitive-looking content')
    if approve and (not reviewer or license_id.lower() in {'unknown','unreviewed','none'}):raise ValueError('Admission requires reviewer and reviewed license metadata')
    data=''.join(json.dumps(r,sort_keys=True)+'\n' for r in rows)
    version=hashlib.sha256((data+source+license_id+synthetic).encode()).hexdigest()[:24]
    directory=folder('datasets')/version
    with locked():
        if directory.exists():
            existing=inspect(version)
            if approve and not existing['approved']:
                existing.update(approved=True,reviewer=reviewer,approved_at=now())
                write(directory/'manifest.json',existing)
            return existing
        directory.mkdir(mode=0o700)
        p=directory/'records.json';write(p,rows)
        manifest={'id':version,'version':1,'created_at':now(),'source':source,'license':license_id,'synthetic':synthetic,
                  'approved':bool(approve),'reviewer':reviewer if approve else None,'approval_scope':'local training admission only',
                  'kind':report['kind'],'records':len(rows),'input_sha256':report['input_sha256'],
                  'records_sha256':sha(p),'validation':report,'split':None}
        write(directory/'manifest.json',manifest)
    return manifest


def inspect(version):
    p=folder('datasets')/identifier(version)
    manifest=read(p/'manifest.json')
    if manifest is None:raise ValueError('Unknown dataset version')
    if sha(p/'records.json')!=manifest['records_sha256']:raise ValueError('Dataset content hash mismatch')
    return manifest


def list_datasets():return [inspect(p.name) for p in sorted(folder('datasets').iterdir()) if p.is_dir()]


def split(version,seed=42):
    with locked():
        manifest=inspect(version)
        if manifest['split']:return manifest
        p=folder('datasets')/version
        rows=read(p/'records.json');groups=defaultdict(list)
        for row in rows:groups[row.get('label','slm')].append(row['id'])
        selections={k:[] for k in ['train','validation','test']}
        for label,ids in sorted(groups.items()):
            if len(ids)<3:raise ValueError('Each label (or instruction dataset) needs at least 3 unique inputs for three disjoint splits')
            ids=sorted(ids);random.Random(seed).shuffle(ids)
            val=max(1,int(len(ids)*.16));test=max(1,int(len(ids)*.2))
            selections['test']+=ids[:test];selections['validation']+=ids[test:test+val];selections['train']+=ids[test+val:]
        write(p/'split.json',selections)
        manifest['split']={'seed':seed,'sha256':sha(p/'split.json'),'counts':{k:len(v) for k,v in selections.items()}}
        write(p/'manifest.json',manifest)
    return manifest


def admitted(version):
    manifest=inspect(version)
    if not manifest['approved']:raise ValueError('Dataset is not admitted; explicit operator review is required')
    if not manifest['split']:raise ValueError('Freeze splits first: datasets split --dataset VERSION')
    p=folder('datasets')/version
    if sha(p/'split.json')!=manifest['split']['sha256']:raise ValueError('Dataset split hash mismatch')
    rows=read(p/'records.json');parts=read(p/'split.json');all_ids=[x for v in parts.values() for x in v]
    if len(all_ids)!=len(set(all_ids)) or set(all_ids)!={r['id'] for r in rows}:raise ValueError('Split overlap or missing records')
    return manifest,rows,{k:[r for r in rows if r['id'] in set(ids)] for k,ids in parts.items()}
