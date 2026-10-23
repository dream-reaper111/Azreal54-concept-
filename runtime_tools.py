"""Dashboard-side broker client and retained execution evidence."""
import base64
import hashlib
import json
import os
import math
from datetime import datetime
from pathlib import Path
from urllib.request import Request,urlopen
from recipes import RECIPES
from model import ROOT
import storage_paths


def configured(service="tools"):
    return os.environ.get('LAB_CONTAINER')=='1' and Path('/run/secrets/'+('external_token' if service=='external-tools' else 'broker_token')).is_file()


def broker(path,payload=None,service="tools"):
    if service not in {'tools','external-tools'}:raise ValueError('Unknown broker service')
    if not configured(service):raise ValueError('Container broker is not configured; start the container lab')
    token=Path('/run/secrets/'+('external_token' if service=='external-tools' else 'broker_token')).read_text().strip()
    headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'}
    request=Request(('http://external-tools:8792' if service=='external-tools' else 'http://tools:8790')+path,data=None if payload is None else json.dumps(payload).encode(),headers=headers)
    with urlopen(request,timeout=55) as response:
        raw=response.read(524289)
    if len(raw)>524288:raise ValueError('Broker response exceeds contract')
    return json.loads(raw)


def execute(approval):
    identifier=approval['operation'].removeprefix('recipe_')
    if identifier not in RECIPES or approval['target']!=RECIPES[identifier]['target']:raise ValueError('Recipe target mismatch')
    result=broker('/run',{'recipe':identifier})
    return retain_result(result,approval,identifier,RECIPES[identifier])


def retain_result(result,approval,identifier,recipe,extra_fields=frozenset()):
    required={'recipe','argv','target','exit_code','started_at','completed_at','elapsed_seconds',
              'timed_out','output_truncated','output_b64','cleanup_pending','provenance'} | set(extra_fields)
    if not isinstance(result,dict) or set(result)!=required:
        raise ValueError('Invalid broker result fields')
    if result['recipe']!=identifier or result['target']!=recipe['target']:
        raise ValueError('Broker result scope mismatch')
    argv=result['argv']
    if not isinstance(argv,list) or not argv or argv[0] not in ['/usr/bin/'+recipe['tool'],'/bin/'+recipe['tool']] or argv[1:]!=recipe['argv'][1:]:
        raise ValueError('Broker result command mismatch')
    if type(result['exit_code']) is not int or any(type(result[k]) is not bool for k in ('timed_out','output_truncated','cleanup_pending')):
        raise ValueError('Invalid broker result status')
    elapsed=result['elapsed_seconds']
    if type(elapsed) not in {int,float} or not math.isfinite(elapsed) or not 0<=elapsed<=60:
        raise ValueError('Invalid broker timing')
    for key in ('started_at','completed_at'):
        timestamp=datetime.fromisoformat(result[key])
        if timestamp.tzinfo is None:raise ValueError('Missing observation timezone')
    if not isinstance(result['output_b64'],str) or len(result['output_b64'])>349528:
        raise ValueError('Invalid broker output size')
    raw=base64.b64decode(result.pop('output_b64'),validate=True)
    if len(raw)>262144:raise ValueError('Evidence exceeds contract')
    folder=storage_paths.artifact_path(ROOT,approval['request_id']);folder.mkdir(parents=True,exist_ok=False,mode=0o700)
    (folder/'stdout.bin').write_bytes(raw)
    result.update(request_id=approval['request_id'],model=approval['model'],sha256=hashlib.sha256(raw).hexdigest(),
                  output_excerpt=raw.decode('utf-8',errors='replace')[:1800],evidence_path=str(folder/'stdout.bin'),
                  excerpt_truncated=len(raw.decode('utf-8',errors='replace'))>1800,
                  limitation='Observed scanner reports are not automatically verified vulnerabilities or proof of absence.')
    (folder/'manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    return result
