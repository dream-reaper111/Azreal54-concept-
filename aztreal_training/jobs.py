"""Durable jobs; owned subprocesses, immutable inputs, cooperative checkpoints."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

from . import datasets,resources
from .store import ROOT,folder,identifier,read,write,sha,now,locked,redacted,state_root
from .registry import model_info,verify

ACTIVE={'queued','training','evaluating','stopping'}
_CHILDREN={}


def process_namespace():return os.readlink('/proc/self/ns/pid')


def driver_alive(job):
    if job.get('driver_namespace') and job['driver_namespace']!=process_namespace():return None
    return bool(job.get('driver_pid') and process_start(job['driver_pid'])==job.get('driver_start'))


def process_start(pid):
    try:
        parts=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
        return None if parts[0]=='Z' else parts[19]
    except (OSError,IndexError):return None


def get(job_id):
    child=_CHILDREN.get(job_id)
    if child is not None and child.poll() is not None:_CHILDREN.pop(job_id,None)
    p=folder('jobs')/identifier(job_id)/'job.json';job=read(p)
    if job is None:raise ValueError('Unknown job')
    # A stale state must never keep claiming progress after an owned driver dies.
    if job['state'] in ACTIVE and job.get('driver_pid') and driver_alive(job) is False:
        job.update(state='failed',stage='driver_lost',error='Owned job driver exited before a terminal state was recorded',finished_at=now())
        write(p,job)
    return job


def list_jobs():return sorted([get(p.name) for p in folder('jobs').iterdir() if p.is_dir()],key=lambda r:r['created_at'],reverse=True)


def update(job_id,**fields):
    with locked():
        p=folder('jobs')/identifier(job_id)/'job.json';job=read(p)
        job.update(fields,updated_at=now());write(p,job)
    return job


def fingerprint(config,dataset,base_hash):
    values={k:v for k,v in config.items() if k not in {'epochs','max_steps','wait','confirm_resource_intensive'}}
    return hashlib.sha256(json.dumps({'config':values,'dataset':dataset['records_sha256'],
        'split':dataset['split']['sha256'],'base':base_hash},sort_keys=True).encode()).hexdigest()


def checked_config(config):
    config=dict(config)
    if config.get('model') not in {'secret-classifier','exploit-classifier','coding-slm'}:raise ValueError('Select a trainable model from models list')
    config.setdefault('recipe','lora' if config['model']=='coding-slm' else 'classifier')
    for name,default,low,high in [('epochs',2,1,10000),('max_steps',100,1,1000000),('batch_size',1,1,32),
                  ('gradient_accumulation',4 if config['model']=='coding-slm' else 1,1,256),('max_length',128,16,4096),('rank',4,1,64),('patience',3,1,100)]:
        value=config.get(name,default)
        if isinstance(value,bool) or not isinstance(value,int) or not low<=value<=high:raise ValueError(f'{name} must be {low}–{high}')
        config[name]=value
    config.setdefault('learning_rate',.0002 if config['model']=='coding-slm' else .003)
    if not 0<float(config['learning_rate'])<=.1:raise ValueError('Learning rate must be >0 and <=0.1')
    config.setdefault('backend','local');config.setdefault('device','cpu');config.setdefault('memory_fraction',.75)
    if config['backend'] not in {'local','podman','docker','kubernetes'}:raise ValueError('Unsupported backend')
    if config['epochs']>3 or config['max_steps']>200:
        if not config.get('confirm_resource_intensive'):raise ValueError('Longer training requires --confirm-resource-intensive')
    return config


def prepare_dataset(value):
    # Paths do not imply admission; only an already-reviewed matching imported version may resolve.
    p=Path(value)
    if p.is_file():
        report,_=datasets.validate(p)
        candidates=[d for d in datasets.list_datasets() if d['input_sha256']==report['input_sha256'] and d['approved']]
        if len(candidates)!=1:raise ValueError('Dataset path must match exactly one explicitly approved imported version')
        value=candidates[0]['id']
    manifest,rows,parts=datasets.admitted(value)
    return manifest,rows,parts


def start(config,dataset_value,resume_id=None):
    config=checked_config(config);manifest,rows,parts=prepare_dataset(dataset_value)
    if (config['model']=='coding-slm')!=(manifest['kind']=='slm'):raise ValueError('Model and dataset types do not match')
    if manifest['kind']=='classifier':
        from collections import Counter
        labels=Counter(r['label'] for r in rows)
        if len(labels)<2 or min(labels.values())<10:raise ValueError('Classifier dataset needs at least 2 classes and 10 unique examples/class')
        if config['model']=='secret-classifier' and set(labels)-{'benign','potential_secret'}:raise ValueError('Secret labels must be benign or potential_secret')
    preflight=resources.preflight(config)
    if not preflight['eligible']:raise ValueError('Preflight blocked: '+'; '.join(preflight['errors']))
    info=preflight['model'];base_hash=sha(info['checkpoint'])
    if info['type']=='coding-slm':
        model_manifest=read(Path(info['path'])/'manifest.json')
        if not model_manifest or model_manifest.get('files',{}).get('model.safetensors')!=base_hash:raise ValueError('Original coding checkpoint failed manifest integrity')
    selected=preflight['selected_gpu'];device=selected['uuid'] if selected else 'cpu'
    with locked():
        for other in list_jobs():
            alive=driver_alive(other)
            if (other['state'] in ACTIVE or alive) and other.get('assigned_device')==device and other['id']!=resume_id:
                raise ValueError('Managed compute device already reserved by job '+other['id'])
        if resume_id:
            job=get(resume_id)
            if driver_alive(job):
                raise ValueError('Previous owned worker is still exiting; wait before resuming')
            if job['state'] not in {'paused','failed'}:raise ValueError('Resume requires a paused or failed job')
            if device!=job['assigned_device']:raise ValueError('Resume requires the original assigned device UUID; automatic device migration is not allowed')
            if not job.get('resume_checkpoint'):raise ValueError('No valid resumable checkpoint was saved')
            verify(Path(job['directory'])/'checkpoints')
            if fingerprint(config,manifest,base_hash)!=job['fingerprint']:raise ValueError('Resume configuration, dataset or original-checkpoint mismatch')
            directory=Path(job['directory']);job_id=job['id']
            if (directory/'stop').exists():(directory/'stop').unlink()
            job['attempts']+=1;job.update(state='queued',stage='resuming',finished_at=None,error=None)
        else:
            job_id=uuid.uuid4().hex[:20];directory=folder('jobs')/job_id;directory.mkdir(mode=0o700)
            (directory/'checkpoints').mkdir(mode=0o700);(directory/'cache').mkdir(mode=0o700)
            # Frozen job copy prevents later dataset-manager edits from changing a running job.
            write(directory/'input.json',{'manifest':manifest,'records':rows,'parts':parts})
            job={'id':job_id,'directory':str(directory),'model':config['model'],'dataset':manifest['id'],
                 'dataset_hash':manifest['records_sha256'],'recipe':config['recipe'],'backend':config['backend'],
                 'assigned_device':device,'base_checkpoint':info['checkpoint'],'base_sha256':base_hash,
                 'fingerprint':fingerprint(config,manifest,base_hash),'input_sha256':sha(directory/'input.json'),
                 'created_at':now(),'started_at':None,'finished_at':None,'state':'queued','stage':'queued','attempts':1,
                 'epoch':0,'step':0,'loss':None,'validation_loss':None,'learning_rate':config['learning_rate'],
                 'checkpoint':None,'resume_checkpoint':None,'evaluation':None,'error':None}
        job['config']=config;job['preflight']=preflight;job['driver_pid']=None
        write(directory/'job.json',job)
        exe=sys.executable
        job['python_executable']=exe
        env={k:v for k,v in os.environ.items() if not any(s in k.upper() for s in ('TOKEN','PASSWORD','SECRET','API_KEY','AWS_'))}
        env.update(AZTREAL_STATE_DIR=str(state_root()),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
                   PYTHONDONTWRITEBYTECODE='1',OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',
                   XDG_CACHE_HOME=str(directory/'cache'),HF_HOME=str(directory/'cache'),TMPDIR=str(directory/'cache'))
        if device!='cpu':env['CUDA_VISIBLE_DEVICES']=device
        else:env['CUDA_VISIBLE_DEVICES']=''
        cmd=[exe,'-B','-m','aztreal_training.worker',job_id]
        if config['backend']!='local':
            engine=config['backend'];cmd=[engine,'run','--rm','--name','aztreal-train-'+job_id,'--network','none',
                '--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--memory','12g','--cpus','2','--pids-limit','128',
                '--user',f'{os.getuid()}:{os.getgid()}','--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=128m',
                '-v',f'{ROOT}:{ROOT}:ro','-v',f'{state_root()}:{state_root()}:rw','-w',str(ROOT),
                '-e','AZTREAL_STATE_DIR='+str(state_root()),'-e','HF_HUB_OFFLINE=1','-e','TRANSFORMERS_OFFLINE=1',
                '-e','HF_HOME='+str(directory/'cache'),'-e','XDG_CACHE_HOME='+str(directory/'cache'),'-e','TMPDIR='+str(directory/'cache')]
            if info['type']=='coding-slm':cmd+=['-v',f'{Path(info["path"]).resolve()}:{Path(info["path"]).resolve()}:ro']
            if device!='cpu':cmd+=(['--device','nvidia.com/gpu='+device] if engine=='podman' else ['--gpus','device='+device]);cmd+=['-e','CUDA_VISIBLE_DEVICES='+device]
            if engine=='podman':cmd+=['--userns=keep-id']
            cmd+=[config['image'],'python','-B','-m','aztreal_training.worker',job_id]
        fd=os.open(directory/'logs.txt',os.O_WRONLY|os.O_CREAT|os.O_APPEND|os.O_NOFOLLOW,0o600)
        try:
            with os.fdopen(fd,'a') as log:
                process=subprocess.Popen(cmd,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                _CHILDREN[job_id]=process
            job.update(driver_pid=process.pid,driver_start=process_start(process.pid),driver_namespace=process_namespace());write(directory/'job.json',job)
        except OSError as e:
            job.update(state='failed',error=redacted(e),finished_at=now());write(directory/'job.json',job);raise ValueError('Worker could not start: '+redacted(e)) from None
    return job


def stop(job_id):
    with locked():
        job=get(job_id)
        if job['state'] not in ACTIVE:raise ValueError('Job is not active')
        write(Path(job['directory'])/'stop',{'at':now(),'operator_uid':os.getuid()})
        job.update(state='stopping',stage='stop_requested');write(Path(job['directory'])/'job.json',job)
    return job


def resume(job_id,epochs=None,max_steps=None,confirm_resource_intensive=False):
    job=get(job_id);config=job['config'].copy()
    if epochs is not None:config['epochs']=epochs
    if max_steps is not None:config['max_steps']=max_steps
    if confirm_resource_intensive:config['confirm_resource_intensive']=True
    return start(config,job['dataset'],resume_id=job_id)


def wait(job_id,timeout=300):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        job=get(job_id)
        alive=driver_alive(job)
        if job['state'] not in ACTIVE and not alive:
            child=_CHILDREN.get(job_id)
            if child is not None:
                try:child.wait(timeout=1)
                except subprocess.TimeoutExpired:continue
                _CHILDREN.pop(job_id,None)
            return job
        time.sleep(.1)
    raise ValueError('Wait deadline reached; job remains managed; inspect status/logs or stop explicitly')
