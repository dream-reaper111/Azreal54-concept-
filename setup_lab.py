"""Runtime-aware installer for the local AZRAEL-54 research workspace."""
import argparse
import csv
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import pwd
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener

ROOT=Path(os.environ.get('AZRAEL_HOME',Path(__file__).resolve().parent)).expanduser().resolve()
import storage_paths
COMPOSE=ROOT/'compose.yaml'
PODMAN_COMPOSE=ROOT/'compose.podman.yaml'
PODMAN_GPU_COMPOSE=ROOT/'compose.gpu.yaml'
DOCKER_GPU_COMPOSE=ROOT/'compose.docker-gpu.yaml'
PYTHON=ROOT/'.slm-venv/bin/python'
PROJECT='azrael54'
RUNTIMES=('podman','docker')
LOCAL_IMAGES={
    'dashboard':'localhost/azrael54-dashboard:latest',
    'frontend':'localhost/azrael54-frontend:latest',
    'tools':'localhost/azrael54-tools:latest',
    'imports':'localhost/azrael54-imports:latest',
    'external-tools':'localhost/azrael54-external-tools:latest',
    'web-lab':'docker.io/bkimminich/juice-shop:latest',
}
INDEPENDENT_SERVICES=('tools','imports','web-lab','external-tools')
FRONTEND_SERVICES=('frontend',)


class RuntimeUnavailable(RuntimeError):
    pass


def _run(command,timeout=20,env=None):
    try:
        return subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=timeout,env=env)
    except (OSError,subprocess.SubprocessError) as error:
        raise RuntimeUnavailable(f'{Path(command[0]).name} could not run: {type(error).__name__}: {error}') from error


def runtime_probe(name):
    """Require a usable local engine; Podman must be rootless."""
    if name=='podman':
        podman=shutil.which('podman');compose=shutil.which('podman-compose')
        if not podman:raise RuntimeUnavailable('Podman executable not found. Install Podman, enable rootless user namespaces, then retry.')
        if not compose:raise RuntimeUnavailable('podman-compose executable not found. Install podman-compose, then retry.')
        compose_env=dict(os.environ,PODMAN_COMPOSE_PROVIDER=compose)
        compose_check=_run([podman,'compose','version'],env=compose_env)
        if compose_check.returncode:raise RuntimeUnavailable('podman-compose is installed but unavailable: '+(compose_check.stderr or compose_check.stdout).strip()[-1000:])
        observed=_run([podman,'info','--format','json'])
        if observed.returncode:
            detail=(observed.stderr or observed.stdout).strip()[-1000:]
            raise RuntimeUnavailable('Podman is installed but unavailable: '+(detail or 'podman info failed')+'. Check rootless user namespaces, subuid/subgid mappings, writable XDG_RUNTIME_DIR, and slirp4netns or pasta.')
        try:info=json.loads(observed.stdout)
        except json.JSONDecodeError as error:raise RuntimeUnavailable('Podman returned invalid `podman info` JSON') from error
        host=info.get('host') or {};security=host.get('security') or {}
        if security.get('rootless') is not True:
            raise RuntimeUnavailable('Podman is running as root or did not confirm rootless mode. Run this installer as the project user.')
        return {'name':'podman','rootless':True,'version':info.get('version',{}).get('Version'),'compose':compose_check.stdout.strip(),
                'compose_provider':compose,
                'network_backend':host.get('networkBackend'),'storage_driver':(info.get('store') or {}).get('graphDriverName')}
    if name=='docker':
        docker=shutil.which('docker')
        if not docker:raise RuntimeUnavailable('Docker executable not found. Install Docker Compose or select --runtime podman.')
        compose=_run([docker,'compose','version'])
        if compose.returncode:raise RuntimeUnavailable('Docker Compose is unavailable: '+(compose.stderr or compose.stdout).strip()[-1000:])
        observed=_run([docker,'version','--format','{{.Server.Version}}'])
        if observed.returncode:raise RuntimeUnavailable('Docker daemon is unavailable: '+(observed.stderr or observed.stdout).strip()[-1000:]+'. Run from a terminal with access to the existing Docker daemon.')
        return {'name':'docker','rootless':None,'version':observed.stdout.strip(),'compose':compose.stdout.strip()}
    raise ValueError('Runtime must be auto, podman or docker')


def select_runtime(requested='auto',verify=True):
    if requested not in ('auto',*RUNTIMES):raise ValueError('Runtime must be auto, podman or docker')
    candidates=RUNTIMES if requested=='auto' else (requested,)
    failures=[]
    for name in candidates:
        if not verify:
            binary=shutil.which('podman' if name=='podman' else 'docker')
            compose=shutil.which('podman-compose') if name=='podman' else binary
            if binary and compose:return name
            failures.append(f'{name}: required executable(s) not found')
            continue
        try:runtime_probe(name);return name
        except RuntimeUnavailable as error:failures.append(f'{name}: {error}')
    raise RuntimeUnavailable('No usable container runtime. '+' | '.join(failures))


def compose_prefix(runtime,gpu=False):
    if runtime=='podman':
        args=[shutil.which('podman') or 'podman','compose','--file',str(COMPOSE)]
        if PODMAN_COMPOSE.is_file():args.extend(['--file',str(PODMAN_COMPOSE)])
        if gpu:
            if not PODMAN_GPU_COMPOSE.is_file():raise RuntimeError('Podman CDI Compose override is missing')
            args.extend(['--file',str(PODMAN_GPU_COMPOSE)])
        args.extend(['--project-name',PROJECT])
        return args
    if runtime=='docker':
        args=[shutil.which('docker') or 'docker','compose','--project-directory',str(ROOT),'-f',str(COMPOSE)]
        if gpu:
            if not DOCKER_GPU_COMPOSE.is_file():raise RuntimeError('Docker GPU Compose override is missing')
            args.extend(['-f',str(DOCKER_GPU_COMPOSE)])
        args.extend(['--project-name',PROJECT])
        return args
    raise ValueError('A selected runtime is required for Compose commands')


def plan(install=True,build=True,start=False,runtime='auto',port=8765,stop=False,restart=False,status=False,gpu=False,recreate=False):
    """Return exact argv arrays; no command is executed by this function."""
    commands=[]
    compose_needed=build or start or stop or restart or status
    selected=select_runtime(runtime,verify=False) if compose_needed else None
    if install:
        if not PYTHON.is_file():commands.append([sys.executable,'-m','venv',str(PYTHON.parent.parent)])
        commands.extend([[str(PYTHON),'-m','pip','install','--only-binary=:all:','--index-url','https://download.pytorch.org/whl/cpu','torch==2.11.0'],
                         [str(PYTHON),'-m','pip','install','--only-binary=:all:','-r',str(ROOT/'requirements-runtime.txt')]])
        if not any((candidate/'model.safetensors').is_file() for candidate in storage_paths.model_read_roots(ROOT)):
            commands.append([str(PYTHON),str(ROOT/'setup_slm.py')])
    if compose_needed:
        prefix=compose_prefix(selected,gpu)
        if build or start:commands.append(prefix+['config'])
        if build:
            commands.append(prefix+['build'])
            if not os.environ.get('AZRAEL_WEB_LAB_IMAGE','').startswith('localhost/azrael54-web-lab-preserved:'):
                commands.append(prefix+['pull','web-lab'])
        if build or start:
            image_command=['podman','image','exists'] if selected=='podman' else ['docker','image','inspect']
            commands.extend([image_command+[os.environ.get('AZRAEL_WEB_LAB_IMAGE',image) if name=='web-lab' else image]
                             for name,image in LOCAL_IMAGES.items()])
        if start:
            recreate_flag='--force-recreate' if recreate else '--no-recreate'
            commands.append(prefix+['up','-d',recreate_flag,*INDEPENDENT_SERVICES])
            commands.append(prefix+['up','-d',recreate_flag,'dashboard'])
            commands.append(prefix+['up','-d',recreate_flag,*FRONTEND_SERVICES])
        if stop:commands.append(prefix+['stop'])
        if restart:commands.append(prefix+['restart'])
        if status:commands.append(prefix+['ps'])
    return commands


def prepare_secrets():
    directory=ROOT/'.runtime'
    if directory.is_symlink():raise ValueError('Runtime secret directory cannot be a symlink')
    directory.mkdir(mode=0o700,exist_ok=True)
    for name in ('broker-token','admin-token','external-token'):
        path=directory/name
        if path.is_symlink():raise ValueError('Secret files cannot be symlinks')
        if not path.exists():
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'w') as handle:handle.write(__import__('secrets').token_urlsafe(32)+'\n')
        if not path.is_file() or len(path.read_text().strip())<32:raise ValueError('Invalid existing project secret')
        path.chmod(0o600)
    artifacts=storage_paths.artifacts_root(ROOT)
    if artifacts.is_symlink():raise ValueError('Artifacts directory cannot be a symlink')
    artifacts.mkdir(mode=0o700,exist_ok=True)


def _env(port,gpu=False):
    env=dict(os.environ,LAB_UID=str(os.getuid()),LAB_GID=str(os.getgid()),AZRAEL_PORT=str(port),PYTHONUNBUFFERED='1',PIP_DISABLE_PIP_VERSION_CHECK='1')
    root=str(storage_paths.storage_root())
    env.setdefault('AZRAEL_STORAGE_ROOT',root)
    env.setdefault('AZRAEL_DATASET_DIR',str(Path(env['AZRAEL_STORAGE_ROOT'])/'datasets'))
    env.setdefault('AZRAEL_MODEL_DIR',str(Path(env['AZRAEL_STORAGE_ROOT'])/'models'/'slm'))
    env.setdefault('AZRAEL_EVIDENCE_DIR',str(Path(env['AZRAEL_STORAGE_ROOT'])/'evidence'))
    env.setdefault('AZRAEL_ARTIFACTS_DIR',str(Path(env['AZRAEL_STORAGE_ROOT'])/'artifacts'))
    env.setdefault('AZRAEL_CHECKPOINT_DIR',str(Path(env['AZRAEL_STORAGE_ROOT'])/'checkpoints'))
    env.setdefault('AZRAEL_TRAINING_DIR',str(Path(env['AZRAEL_STORAGE_ROOT'])/'training'))
    env.setdefault('AZRAEL_CACHE_DIR',str(Path(env['AZRAEL_STORAGE_ROOT'])/'cache'))
    env.setdefault('AZRAEL_TMP_DIR',str(Path(env['AZRAEL_STORAGE_ROOT'])/'tmp'))
    env.setdefault('AZRAEL_LEGACY_DATASET_DIR',str(ROOT/'data'))
    env.setdefault('AZRAEL_LEGACY_MODEL_DIR',str(ROOT/'.slm-model'))
    env['HF_HOME']=os.environ.get('AZRAEL_HF_HOME',str(Path(env['AZRAEL_CACHE_DIR'])/'huggingface'))
    env['HUGGINGFACE_HUB_CACHE']=str(Path(env['HF_HOME'])/'hub')
    env['TORCH_HOME']=os.environ.get('AZRAEL_TORCH_HOME',str(Path(env['AZRAEL_CACHE_DIR'])/'torch'))
    env['XDG_CACHE_HOME']=str(env['AZRAEL_CACHE_DIR'])
    env['PIP_CACHE_DIR']=os.environ.get('AZRAEL_PIP_CACHE_DIR',str(Path(env['AZRAEL_CACHE_DIR'])/'pip'))
    env['TMPDIR']=env['AZRAEL_TMP_DIR']
    env.setdefault('AZRAEL_GPU_ENABLED','true' if gpu else 'false')
    if shutil.which('podman-compose'):
        env['PODMAN_COMPOSE_PROVIDER']=shutil.which('podman-compose')
    env.setdefault('AZRAEL_TORCH_INDEX_URL',
                   'https://download.pytorch.org/whl/cu128' if gpu else 'https://download.pytorch.org/whl/cpu')
    if gpu:
        selection=select_gpu_device()
        env['AZRAEL_GPU_DEVICE']='all'
        env['AZRAEL_GPU_UUID']=selection['devices'][0]['uuid']
        # CUDA order is pinned by UUID for reproducible single-GPU workload selection.
        ordered=sorted(selection['devices'] if selection['selector']=='all' else host_gpu_inventory(),
                       key=lambda item: (0 if 'rtx 3080' in item['name'].casefold() else 1,
                                         0 if 'rtx 5060' in item['name'].casefold() else 1,
                                         item['uuid']))
        env['AZRAEL_GPU_VISIBLE_DEVICES']=','.join(item['uuid'] for item in ordered)
        env['CUDA_VISIBLE_DEVICES']=env['AZRAEL_GPU_VISIBLE_DEVICES']
        env.setdefault('AZRAEL_GPU_MEMORY_FRACTION',os.environ.get('AZRAEL_GPU_MEMORY_FRACTION','0.85'))
        env['AZRAEL_GPU_NAME']=selection['devices'][0]['name']
        env.setdefault('AZRAEL_GPU_ALLOW_CPU_FALLBACK','true')
    return env


def _http(url,method='GET',body=None,headers=None,timeout=5):
    opener=build_opener(ProxyHandler({}))
    request=Request(url,data=body,headers=headers or {},method=method)
    with opener.open(request,timeout=timeout) as response:return response.status,response.headers, response.read(1_000_000)


def verify_dashboard(port,timeout=120):
    """Verify health, login/session boundary, and the authenticated dashboard API."""
    base=f'http://127.0.0.1:{port}'
    deadline=time.monotonic()+timeout;health=None
    while time.monotonic()<deadline:
        try:
            status,_,raw=_http(base+'/healthz',timeout=3)
            if status==200:health=json.loads(raw);break
        except (OSError,ValueError,HTTPError,URLError):time.sleep(2)
    if health is None:raise RuntimeError(f'Dashboard health endpoint did not become ready at {base}/healthz within {timeout}s')
    token_path=ROOT/'.runtime/admin-token'
    if not token_path.is_file():raise RuntimeError('Admin token is missing; run --install first')
    host=f'127.0.0.1:{port}';headers={'Host':host,'Origin':'http://'+host,'X-Lab-Request':'1','Content-Type':'application/json'}
    try:
        unauthenticated,_,_=_http(base+'/api/state',headers={'Host':host},timeout=5)
    except HTTPError as error:unauthenticated=error.code
    if unauthenticated!=401:raise RuntimeError('Dashboard API did not enforce its login session boundary')
    page_status,_,page=_http(base+'/',headers={'Host':host},timeout=10)
    if page_status!=200 or b'<html' not in page.lower():raise RuntimeError('Dashboard page did not serve HTML')
    status,response_headers,raw=_http(base+'/api/login','POST',json.dumps({'token':token_path.read_text().strip()}).encode(),headers,timeout=10)
    if status!=200:raise RuntimeError('Dashboard login API verification failed with HTTP '+str(status))
    cookie=response_headers.get('Set-Cookie','').split(';',1)[0]
    if not cookie.startswith('lab_session='):raise RuntimeError('Dashboard login did not return a session cookie')
    status,_,raw=_http(base+'/api/state',headers={'Host':host,'Cookie':cookie},timeout=30)
    if status!=200:raise RuntimeError('Authenticated dashboard API verification failed with HTTP '+str(status))
    state=json.loads(raw)
    expected_roles=set(json.loads((ROOT/'learning-paths.json').read_text()))
    if {row.get('id') for row in state.get('roles',[])}!=expected_roles:
        raise RuntimeError('Dashboard API role registry differs from the configured role identities')
    if len(state.get('research_libraries',{}).get('libraries',[]))!=11:raise RuntimeError('Dashboard API did not return all 11 research-library entries')
    provider_queries=sum(len(profile.get('providers',[])) for profile in state.get('role_research',{}).get('profiles',{}).values())
    configured_profiles=json.loads((ROOT/'role-search-profiles.json').read_text())['profiles']
    expected_queries=sum(len(profile.get('providers',[])) for profile in configured_profiles.values())
    if provider_queries!=expected_queries:raise RuntimeError(f'Dashboard API exposed {provider_queries} role search queries; expected {expected_queries}')
    idle=state.get('idle_trainer',{})
    if not idle.get('worker_ready'):
        raise RuntimeError('Authenticated state does not report a live idle-trainer worker')
    ctf_status=state.get('ctf_lab',{})
    if (ctf_status.get('status')!='ready' or ctf_status.get('challenge_count')!=20 or
            ctf_status.get('training_data') is not False or ctf_status.get('operational_evidence') is not False):
        raise RuntimeError('Authenticated state does not report the isolated 20-challenge CTF catalog')
    catalog_status,_,catalog_raw=_http(base+'/api/ctf',headers={'Host':host,'Cookie':cookie},timeout=15)
    if catalog_status!=200:raise RuntimeError('Authenticated CTF practice catalog is unavailable')
    catalog=json.loads(catalog_raw)
    if (catalog.get('answers_disclosed') is not False or len(catalog.get('challenges',[]))!=20 or
            catalog.get('network_targets')!=0 or catalog.get('executable_assets')!=0):
        raise RuntimeError('CTF catalog is not bounded, offline, or answer-safe')
    key_path=ROOT/'ctf_assets'/'organizer-answer-key.json'
    if not key_path.is_file():raise RuntimeError('Local CTF answer-key integrity check is unavailable')
    answer_values=json.loads(key_path.read_text()).get('answers',{}).values()
    serialized=catalog_raw.decode(errors='replace')
    if any(answer and answer in serialized for answer in answer_values):
        raise RuntimeError('Authenticated CTF catalog disclosed an organizer answer')
    return {'health':health,'api_login':'passed','authenticated_api':'passed','role_profiles':len(state['roles']),
            'research_libraries':len(state['research_libraries']['libraries']),
            'role_search_queries':provider_queries,'dashboard_page':'passed','unauthenticated_api':'rejected',
            'ctf_catalog':{'status':'passed','challenge_count':len(catalog['challenges']),
                           'answers_disclosed':False,'network_targets':0,'training_data':False},
            'idle_trainer':{'worker_ready':True,'automatic_training':False},
            'tools_broker_configured':bool(state.get('runtime_tools_configured')),
            'external_broker_configured':bool(state.get('external_runtime_configured'))}


def verify_ctf_model_practice(port,timeout=240):
    """Run one authenticated CTF prompt through the local SLM and record safe metadata."""
    base=f'http://127.0.0.1:{port}';host=f'127.0.0.1:{port}'
    headers={'Host':host,'Origin':'http://'+host,'X-Lab-Request':'1','Content-Type':'application/json'}
    token_path=ROOT/'.runtime/admin-token'
    if not token_path.is_file():raise RuntimeError('Admin token is missing; run bootstrap first')
    status,response_headers,_=_http(base+'/api/login','POST',json.dumps({'token':token_path.read_text().strip()}).encode(),headers,timeout=10)
    if status!=200:raise RuntimeError('Could not authenticate CTF model practice')
    cookie=response_headers.get('Set-Cookie','').split(';',1)[0]
    if not cookie.startswith('lab_session='):raise RuntimeError('CTF practice login returned no session')
    headers['Cookie']=cookie
    status,_,raw=_http(base+'/api/ctf',headers={'Host':host,'Cookie':cookie},timeout=15)
    if status!=200:raise RuntimeError('Authenticated CTF challenge catalog is unavailable')
    challenge=json.loads(raw)['challenges'][0]
    status,_,raw=_http(base+'/api/ctf/practice','POST',json.dumps({'challenge_id':challenge['id'],'role':'analyst'}).encode(),headers,timeout=15)
    if status!=202:raise RuntimeError(f'CTF practice submission failed with HTTP {status}')
    job_id=json.loads(raw).get('job_id')
    if not isinstance(job_id,str):raise RuntimeError('CTF practice did not return a job identifier')
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        status,_,raw=_http(base+'/api/state',headers={'Host':host,'Cookie':cookie},timeout=30)
        if status!=200:raise RuntimeError('Could not read authenticated model-practice job status')
        state=json.loads(raw)
        job=next((item for item in state.get('jobs',[]) if item.get('id')==job_id),None)
        if job and job.get('status') in {'completed','partial','failed'}:
            if job['status']!='completed':
                raise RuntimeError('Local SLM CTF practice job ended with status '+str(job['status']))
            result=job.get('result') or {}
            response=result.get('model_response') or {}
            text=response.get('text')
            if not isinstance(text,str) or not text.strip():
                raise RuntimeError('Local SLM returned no CTF challenge response')
            attempt=result.get('attempt') or {}
            if result.get('training_occurred') is not False or result.get('operational_evidence_written') is not False:
                raise RuntimeError('CTF practice crossed into training or operational evidence')
            return {'status':'passed','challenge_id':challenge['id'],'job_id':job_id,
                    'model_response_length':len(text),'flag_correct':bool(attempt.get('correct')),
                    'device':response.get('device'),'gpu_memory_allocated_bytes':response.get('gpu_memory_allocated_bytes'),
                    'training_occurred':False,'operational_evidence_written':False}
        time.sleep(2)
    raise RuntimeError(f'Local SLM CTF practice did not finish within {timeout}s')


def verify_research_providers(port,cookie,timeout=210):
    """Exercise one fixed role profile through the authenticated broker path."""
    base=f'http://127.0.0.1:{port}';host=f'127.0.0.1:{port}'
    headers={'Host':host,'Origin':'http://'+host,'X-Lab-Request':'1','Content-Type':'application/json','Cookie':cookie}
    status,_,raw=_http(base+'/api/command','POST',json.dumps({'action':'role_collect','role':'cve_triage'}).encode(),headers,timeout=10)
    if status!=202:raise RuntimeError('Role-scoped research connectivity request was not accepted')
    job_id=json.loads(raw).get('job_id')
    if not isinstance(job_id,str):raise RuntimeError('Role-scoped research job returned no identifier')
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        status,_,raw=_http(base+'/api/state',headers={'Host':host,'Cookie':cookie},timeout=20)
        if status!=200:raise RuntimeError('Could not inspect role-scoped research job')
        jobs=json.loads(raw).get('jobs',[])
        job=next((item for item in jobs if item.get('id')==job_id),None)
        if job and job.get('status')!='running':
            requests=(job.get('result') or {}).get('requests',[])
            return {'role':'cve_triage','job_status':job.get('status'),
                    'providers':[{'provider':item.get('provider'),'status':item.get('status')} for item in requests],
                    'retrieved':sum(item.get('status')=='retrieved' for item in requests),
                    'failed':sum(item.get('status')!='retrieved' for item in requests),
                    'training_occurred':False}
        time.sleep(2)
    raise RuntimeError(f'Role-scoped research request did not finish within {timeout}s')


def _gpu_telemetry_sampler(index,stop,samples):
    smi=shutil.which('nvidia-smi')
    if not smi:return
    while not stop.is_set():
        try:
            result=subprocess.run([smi,'--query-gpu=utilization.gpu,memory.used','--format=csv,noheader,nounits','-i',str(index)],
                                  capture_output=True,text=True,timeout=3)
            if result.returncode==0 and result.stdout.strip():
                values=next(csv.reader([result.stdout.strip()]))
                samples.append({'utilization_gpu_percent':int(values[0].strip()),'memory_used_mb':int(values[1].strip())})
        except (OSError,ValueError,subprocess.SubprocessError):pass
        stop.wait(.2)


def verify_slm(runtime,timeout=300,require_gpu=False,gpu=False):
    prompt=('Write a roughly 100-word explanation of how layered network segmentation reduces lateral movement in an authorized lab.'
            if require_gpu else 'Reply with the single word READY.')
    request={'mode':'admin_chat','text':prompt,'role':'analyst','language':'Python','context':{}}
    payload=json.dumps(request)
    command=compose_prefix(runtime,gpu)+['exec','-T','dashboard','/app/.slm-venv/bin/python','/app/slm_worker.py']
    samples=[];stop=threading.Event();sampler=None;selection=None
    if require_gpu:
        selection=select_gpu_device()
        sampler=threading.Thread(target=_gpu_telemetry_sampler,args=(selection['devices'][0]['index'],stop,samples),daemon=True)
        sampler.start()
    try:result=subprocess.run(command,input=payload,text=True,capture_output=True,timeout=timeout,cwd=ROOT,env=_env(8765,gpu))
    except (OSError,subprocess.SubprocessError) as error:raise RuntimeError('Container SLM inference command failed: '+str(error)) from error
    finally:
        if sampler:
            stop.set();sampler.join(timeout=4)
    if result.returncode:raise RuntimeError('Container SLM inference failed: '+(result.stderr or result.stdout).strip()[-1000:])
    try:answer=json.loads(result.stdout)
    except json.JSONDecodeError as error:raise RuntimeError('Container SLM returned invalid JSON') from error
    if not isinstance(answer,dict) or not isinstance(answer.get('text'),str) or not answer['text'].strip():raise RuntimeError('Container SLM returned no generated text')
    device=answer.get('device','cpu')
    if require_gpu and not str(device).startswith('cuda'):
        raise RuntimeError(f'SLM inference used {device}; GPU verification was requested but no CUDA inference occurred')
    inference={'status':'passed','model':answer.get('model'),'mode':answer.get('mode'),'device':device,
            'device_name':answer.get('device_name'),'torch_cuda_memory_allocated_bytes':answer.get('gpu_memory_allocated_bytes',0),
            'generated_tokens':answer.get('generated_tokens'),'answer_length':len(answer['text']),'answer_text_retained':False}
    if require_gpu:
        peak=max((item['utilization_gpu_percent'] for item in samples),default=0)
        inference['gpu_telemetry']={'host_gpu_index':selection['devices'][0]['index'],'samples':len(samples),
                                    'peak_utilization_percent':peak,
                                    'peak_memory_used_mb':max((item['memory_used_mb'] for item in samples),default=0)}
        if answer.get('device_name')!=selection['devices'][0]['name']:
            raise RuntimeError(f"SLM used {answer.get('device_name')}; expected selected GPU {selection['devices'][0]['name']}")
        if not answer.get('gpu_memory_allocated_bytes'):
            raise RuntimeError('SLM reported CUDA but allocated no GPU model memory')
        if peak<=0:
            raise RuntimeError('CUDA inference completed but host nvidia-smi did not observe GPU utilization; rerun the verification during an idle GPU window')
    return inference


def verify_gpu_container(runtime):
    """Check PyTorch CUDA support and device identity inside the live dashboard container."""
    selection=select_gpu_device()
    probe="""import json,torch
available=torch.cuda.is_available()
result={'torch_cuda_available':available,'pytorch_version':torch.__version__,'pytorch_cuda_version':torch.version.cuda}
if available:
 p=torch.cuda.get_device_properties(0)
 result.update({'gpu_name':p.name,'cuda_capability':list(torch.cuda.get_device_capability(0)),'gpu_total_memory_bytes':p.total_memory})
print(json.dumps(result))
if not available or torch.version.cuda is None:raise SystemExit('CUDA-enabled PyTorch or visible GPU is missing')"""
    command=compose_prefix(runtime,True)+['exec','-T','dashboard','/app/.slm-venv/bin/python','-c',probe]
    result=subprocess.run(command,text=True,capture_output=True,timeout=40,cwd=ROOT,env=_env(8765,True))
    if result.returncode:raise RuntimeError('Dashboard container lacks usable CUDA PyTorch: '+(result.stderr or result.stdout).strip()[-1000:])
    try:report=json.loads(result.stdout)
    except json.JSONDecodeError as error:raise RuntimeError('CUDA verification returned invalid JSON') from error
    report['selected_host_gpu']=selection['devices'][0]
    if report.get('gpu_name')!=selection['devices'][0]['name']:
        raise RuntimeError(f"CUDA container sees {report.get('gpu_name')}; selected host device is {selection['devices'][0]['name']}")
    return report


def verify_internal_services(runtime):
    probe="""import json,urllib.request
targets={'imports':'http://imports:8791/healthz','tools':'http://tools:8790/healthz',
         'external-tools':'http://external-tools:8792/healthz','web-lab':'http://web-lab:3000/'}
health={name:urllib.request.urlopen(url,timeout=5).status for name,url in targets.items()}
token=open('/run/secrets/broker_token').read().strip()
request=urllib.request.Request('http://tools:8790/status',headers={'Authorization':'Bearer '+token})
tools=json.load(urllib.request.urlopen(request,timeout=5))
required=('curl','nmap','whatweb','nikto')
available=all(tools.get('tools',{}).get(name) is True for name in required)
if tools.get('target_scope')!='Owned internal web-lab only' or not available:
 raise SystemExit('Tool broker authorization, fixed target scope, or required tool check failed')
print(json.dumps({'service_health':health,'tools_broker_authenticated':200,
                  'required_tools_available':available}))"""
    command=compose_prefix(runtime)+['exec','-T','dashboard','/app/.slm-venv/bin/python','-c',probe]
    result=subprocess.run(command,text=True,capture_output=True,timeout=30,cwd=ROOT,env=_env(8765))
    if result.returncode:raise RuntimeError('Internal service health probe failed: '+(result.stderr or result.stdout).strip()[-1000:])
    values=json.loads(result.stdout)
    health=values.get('service_health',{})
    if set(health)!={'imports','tools','external-tools','web-lab'} or any(status!=200 for status in health.values()) or values.get('tools_broker_authenticated')!=200 or values.get('required_tools_available') is not True:
        raise RuntimeError('One or more internal services failed health checks: '+json.dumps(values))
    return values


def _container_ids(runtime,service):
    binary='podman' if runtime=='podman' else 'docker'
    command=[shutil.which(binary) or binary,'ps','-aq',
             '--filter',f'label=com.docker.compose.project={PROJECT}',
             '--filter',f'label=com.docker.compose.service={service}']
    result=subprocess.run(command,text=True,capture_output=True,timeout=10,cwd=ROOT)
    if result.returncode:raise RuntimeError(f'Could not inspect {service} containers: {(result.stderr or result.stdout).strip()[-500:]}')
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def wait_for_services_healthy(runtime,services,timeout=240):
    """Wait on Compose healthchecks, failing before dependent services start."""
    binary='podman' if runtime=='podman' else 'docker'
    executable=shutil.which(binary) or binary
    deadline=time.monotonic()+timeout
    last={service:'not_created' for service in services}
    while time.monotonic()<deadline:
        all_healthy=True
        for service in services:
            ids=_container_ids(runtime,service)
            if not ids:
                last[service]='not_created';all_healthy=False;continue
            states=[]
            for container_id in ids:
                if runtime=='podman':
                    # Podman 4.x may store Compose healthcheck metadata without
                    # scheduling the monitor in a rootless user session. Run
                    # the declared in-container check directly so readiness is
                    # based on the real probe result rather than staying
                    # indefinitely at "starting" with an empty health log.
                    subprocess.run([executable,'healthcheck','run',container_id],
                        text=True,capture_output=True,timeout=15,cwd=ROOT)
                inspected=subprocess.run([executable,'inspect','--format',
                    '{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}',container_id],
                    text=True,capture_output=True,timeout=10,cwd=ROOT)
                if inspected.returncode:
                    states.append('inspect_error');continue
                states.append(inspected.stdout.strip())
            last[service]=','.join(states)
            if not states or any(item.split('|')[-1]!='healthy' for item in states):all_healthy=False
            if any(item.startswith(('exited|','dead|','removing|')) for item in states):
                raise RuntimeError(f'{service} container stopped before becoming healthy: {last[service]}')
        if all_healthy:
            print(json.dumps({'stage':'healthy','services':list(services),'states':last}),flush=True)
            return last
        time.sleep(2)
    raise RuntimeError(f'Services did not become healthy within {timeout}s: '+json.dumps(last))


def _diagnostic_command(command,timeout=10):
    try:
        result=subprocess.run(command,capture_output=True,text=True,timeout=timeout,cwd=ROOT)
        return {'returncode':result.returncode,'output':(result.stdout or '').strip()[-2500:],
                'error':(result.stderr or '').strip()[-2500:] or None}
    except (OSError,subprocess.SubprocessError) as error:
        return {'error':f'{type(error).__name__}: {error}'}


def _podman_rootless_diagnostics(podman):
    """Collect read-only mapping, runtime, storage and mount-path evidence."""
    details=[]
    info={};info_error=None
    try:
        raw_info=subprocess.run([podman,'info','--format','json'],capture_output=True,text=True,timeout=10,cwd=ROOT)
        if raw_info.returncode==0:info=json.loads(raw_info.stdout)
        else:info_error=(raw_info.stderr or raw_info.stdout).strip()[-2500:]
    except (OSError,subprocess.SubprocessError,ValueError) as error:info_error=f'{type(error).__name__}: {error}'
    host=info.get('host',{}) if isinstance(info,dict) else {}
    store=info.get('store',{}) if isinstance(info,dict) else {}
    details.append({'diagnostic':'podman_host_and_store','rootless':host.get('security',{}).get('rootless'),
                    'oci_runtime':host.get('ociRuntime'),'store':{key:store.get(key) for key in
                    ('graphRoot','runRoot','graphDriverName','graphOptions','volumePath') if key in store},
                    'info_error':info_error})

    try:username=pwd.getpwuid(os.getuid()).pw_name
    except KeyError:username=str(os.getuid())
    details.append({'diagnostic':'host_identity','username':username,'uid':os.getuid(),'gid':os.getgid(),
                    'supplementary_gids':os.getgroups()})
    id_ranges={'subuid':[],'subgid':[]}
    for label,path in (('subuid','/etc/subuid'),('subgid','/etc/subgid')):
        try:
            rows=[line.strip() for line in Path(path).read_text().splitlines()
                  if line.strip() and not line.lstrip().startswith('#') and line.split(':',1)[0] in {username,str(os.getuid())}]
            for row in rows:
                try:
                    _,start,count=row.split(':',2);id_ranges[label].append((int(start),int(count)))
                except ValueError:continue
            details.append({'diagnostic':label,'user':username,'entries':rows,'error':None})
        except OSError as error:details.append({'diagnostic':label,'user':username,'error':str(error)})
    for kind in ('uid_map','gid_map'):
        details.append({'diagnostic':f'podman_unshare_{kind}',**_diagnostic_command(
            [podman,'unshare','cat',f'/proc/self/{kind}'])})
    for path in ('/proc/sys/user/max_user_namespaces','/proc/sys/kernel/unprivileged_userns_clone'):
        try:value=Path(path).read_text().strip()
        except OSError as error:value=f'unavailable: {error}'
        details.append({'diagnostic':path,'value':value})

    root=store.get('graphRoot') if isinstance(store,dict) else None
    if root:
        ancestors=[]
        for path in reversed((Path(root),*Path(root).parents)):
            try:
                status=path.stat()
                ancestors.append({'path':str(path),'mode':stat.S_IMODE(status.st_mode),
                    'uid':status.st_uid,'gid':status.st_gid,'owner_x':bool(status.st_mode&stat.S_IXUSR),
                    'group_x':bool(status.st_mode&stat.S_IXGRP),'other_x':bool(status.st_mode&stat.S_IXOTH)})
            except OSError as error:ancestors.append({'path':str(path),'error':str(error)})
        details.append({'diagnostic':'graphroot_ancestor_permissions','ancestors':ancestors})
        keep_uid=id_ranges['subuid'][0][0] if id_ranges['subuid'] else None
        keep_gid=id_ranges['subgid'][0][0] if id_ranges['subgid'] else None
        candidates=[]
        if keep_uid is not None and keep_gid is not None:
            for item in ancestors:
                if 'uid' not in item:continue
                owner_access=item['uid']==keep_uid and item['owner_x']
                group_access=item['gid']==keep_gid and item['group_x']
                if not (owner_access or group_access or item['other_x']):
                    candidates.append({'path':item['path'],'mode':item['mode'],'uid':item['uid'],'gid':item['gid'],
                        'reason':f'no execute bit for keep-id container-root host IDs {keep_uid}:{keep_gid}; verify this mapping against podman unshare maps'})
        details.append({'diagnostic':'keep_id_graphroot_traversal_candidates',
                        'container_root_host_uid_candidate':keep_uid,'container_root_host_gid_candidate':keep_gid,
                        'ancestors_without_candidate_traverse_access':candidates})
        if shutil.which('namei'):
            details.append({'diagnostic':'namei_graphroot',**_diagnostic_command(['namei','-l',root])})
        if shutil.which('findmnt'):
            details.append({'diagnostic':'graphroot_mount_propagation',**_diagnostic_command(
                ['findmnt','-T',root,'-o','TARGET,FSTYPE,OPTIONS,PROPAGATION'])})
    storage_root=storage_paths.storage_root()
    try:
        status=storage_root.stat()
        try:storage_owner=pwd.getpwuid(status.st_uid).pw_name
        except KeyError:storage_owner=None
        details.append({'diagnostic':'azrael_storage_root_permissions','path':str(storage_root),
                        'uid':status.st_uid,'gid':status.st_gid,'mode':stat.S_IMODE(status.st_mode),'owner':storage_owner})
    except OSError as error:details.append({'diagnostic':'azrael_storage_root_permissions','path':str(storage_root),'error':str(error)})
    if shutil.which('findmnt'):
        details.append({'diagnostic':'azrael_storage_mount_propagation',**_diagnostic_command(
            ['findmnt','-T',str(storage_root),'-o','TARGET,FSTYPE,OPTIONS,PROPAGATION'])})
    versions={}
    for binary in ('crun','runc','fuse-overlayfs','newuidmap','newgidmap','nvidia-ctk'):
        executable=shutil.which(binary)
        if executable:
            result=_diagnostic_command([executable,'--version'],timeout=5)
            versions[binary]=(result.get('output') or result.get('error') or '').splitlines()[:3]
    details.append({'diagnostic':'oci_and_mapping_tool_versions','versions':versions})
    config_files=('/etc/containers/storage.conf','/etc/containers/containers.conf',
                  str(Path.home()/'.config/containers/storage.conf'),str(Path.home()/'.config/containers/containers.conf'))
    config=[]
    for raw_path in config_files:
        path=Path(raw_path)
        if not path.is_file():continue
        try:
            lines=[line.strip() for line in path.read_text().splitlines()
                   if any(key in line.lower() for key in ('driver','graphroot','runroot','mount_program','runtime','events_logger'))]
            config.append({'path':str(path),'relevant_lines':lines[:40]})
        except OSError as error:config.append({'path':str(path),'error':str(error)})
    details.append({'diagnostic':'container_configuration','files':config})
    return details


def preflight_hypothesis(checks,diagnostics):
    """Summarize probe differentials without claiming an unverified root cause."""
    states={item.get('check'):item.get('status') for item in checks}
    errors=' '.join(str(item.get('error','')) for item in checks).lower()
    failures=[item for item in checks if item.get('status')=='failed']
    if not failures:
        return 'All preflight checks passed.'
    keep_id_failed=any(states.get(name)=='failed' for name in ('keep_id_rootless','keep_id_project_user','keep_id_bind_mount'))
    if states.get('simple_rootless')=='passed' and keep_id_failed:
        path_candidates=next((item.get('ancestors_without_candidate_traverse_access',[]) for item in diagnostics
                              if item.get('diagnostic')=='keep_id_graphroot_traversal_candidates'),[])
        if 'private' in errors and 'permission denied' in errors and path_candidates:
            uid=next((item.get('container_root_host_uid_candidate') for item in diagnostics
                      if item.get('diagnostic')=='keep_id_graphroot_traversal_candidates'),None)
            gid=next((item.get('container_root_host_gid_candidate') for item in diagnostics
                      if item.get('diagnostic')=='keep_id_graphroot_traversal_candidates'),None)
            paths=[item['path'] for item in path_candidates if item.get('path')]
            paths_display=', '.join(paths)
            acl_command=(f"setfacl -m u:{uid}:x "+' '.join(shlex.quote(path) for path in paths)) if uid is not None and paths else None
            chmod_command=('chmod o+x '+' '.join(shlex.quote(path) for path in paths)) if paths else None
            hint=(f'Failure is isolated to keep-id startup. Likely cause: graphroot ancestor traversal is denied for keep-id mapped host IDs {uid}:{gid}; '
                  f'candidate paths: {paths_display}. Advisory only; no permissions were changed. '
                  +(f'The minimal execute/search-only ACL command, after confirming the mapping and paths, is `{acl_command}`. '
                    if acl_command else 'Confirm the mapped host IDs and paths before applying an ACL. ')
                  +(f'The simpler alternative is `{chmod_command}`; it grants traversal to every local user, so it is broader. '
                    if chmod_command else '')
                  +'Execute-only access does not grant directory listing. This program never applies either change.')
            return hint
        return ('Failure is isolated to the keep-id/user-namespace startup path, not basic rootless container execution. '
                'Inspect subordinate ID maps and graphroot ancestor traversal before attributing it to crun or the filesystem.')
    if states.get('simple_rootless')=='passed' and states.get('keep_id_rootless')=='passed' and states.get('keep_id_project_user')=='failed':
        return ('Minimal keep-id works, but the AZRAEL UID/GID variant fails. Investigate the explicit container user mapping and its interaction with the OCI runtime before Compose.')
    if states.get('keep_id_rootless')=='passed' and states.get('keep_id_bind_mount')=='failed':
        return 'keep-id startup works; the failing bind-mount path points to bind-source permissions or filesystem behavior.'
    if states.get('simple_rootless')=='failed' and states.get('overlay_tmpfs_private_mount')=='failed':
        return 'Basic rootless overlay startup and private tmpfs both fail; investigate the OCI runtime, overlay storage, and mount namespace before Compose.'
    return 'One or more preflight checks failed, but the results do not isolate a single cause; use the recorded mappings, runtime, graphroot, and mount-propagation details.'


def podman_rootless_preflight():
    """Run disposable, network-isolated probes; never edit Podman config or project containers."""
    info=runtime_probe('podman')
    podman=shutil.which('podman') or 'podman'
    checks=[];diagnostic_retries=[]
    with tempfile.TemporaryDirectory(prefix='azrael54-preflight-') as temp:
        scratch=Path(temp);probe=scratch/'probe.txt';probe.write_text('AZRAEL_PREFLIGHT_OK\n')
        identity=f'{os.getuid()}:{os.getgid()}'
        cases=[
            ('simple_rootless',[podman,'run','--rm','--network','none','docker.io/library/alpine:3.20','echo','PODMAN_OK']),
            ('network_isolation',[podman,'run','--rm','--network','none','docker.io/library/alpine:3.20','sh','-c',"awk 'NR > 1 {found=1} END {exit found?1:0}' /proc/net/route"]),
            ('read_only_bind_mount',[podman,'run','--rm','--network','none','-v',f'{scratch}:/probe:ro','docker.io/library/alpine:3.20','sh','-ec','test "$(cat /probe/probe.txt)" = AZRAEL_PREFLIGHT_OK']),
            # Keep both cases: the first reproduces the operator's minimal
            # `podman run --userns keep-id ...` test; the second matches the
            # explicit UID/GID configured by AZRAEL Compose.
            ('keep_id_rootless',[podman,'run','--rm','--network','none','--userns=keep-id','docker.io/library/alpine:3.20','sh','-ec','cat /proc/self/uid_map /proc/self/gid_map']),
            ('keep_id_project_user',[podman,'run','--rm','--network','none','--userns=keep-id','--user',identity,'docker.io/library/alpine:3.20','sh','-ec',f'test "$(id -u)" = "{os.getuid()}" && test "$(id -g)" = "{os.getgid()}" && cat /proc/self/uid_map /proc/self/gid_map']),
            ('keep_id_bind_mount',[podman,'run','--rm','--network','none','--userns=keep-id','--user',identity,'-v',f'{scratch}:/probe:ro','docker.io/library/alpine:3.20','sh','-ec','test "$(cat /probe/probe.txt)" = AZRAEL_PREFLIGHT_OK']),
            ('overlay_tmpfs_private_mount',[podman,'run','--rm','--network','none','--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=8m','docker.io/library/alpine:3.20','sh','-ec','echo overlay-ok >/tmp/probe && test "$(cat /tmp/probe)" = overlay-ok']),
        ]
        for name,command in cases:
            try:
                result=subprocess.run(command,capture_output=True,text=True,timeout=60,cwd=ROOT)
                checks.append({'check':name,'status':'passed' if result.returncode==0 else 'failed',
                    'returncode':result.returncode,'output':(result.stdout or '').strip()[-500:],
                    'error':(result.stderr or '').strip()[-1500:] or None})
                if name in {'keep_id_rootless','keep_id_project_user'} and result.returncode:
                    debug=[podman,'--log-level=debug','run','--rm','--network','none','--userns=keep-id']
                    if name=='keep_id_project_user':debug.extend(['--user',identity])
                    debug.extend(['docker.io/library/alpine:3.20','true'])
                    diagnostic_retries.append({'diagnostic':f'{name}_debug_retry',**_diagnostic_command(debug,timeout=60)})
            except (OSError,subprocess.SubprocessError) as error:
                checks.append({'check':name,'status':'failed','error':f'{type(error).__name__}: {error}'})

    storage_root=storage_paths.storage_root()
    storage_result={'status':'skipped','root':str(storage_root),'reason':'storage root is absent; run the separate --storage-check before deployment',
                    'temporary_probe_removed':True}
    if storage_root.is_dir() and os.access(storage_root,os.W_OK|os.X_OK):
        probe_dir=None
        try:
            probe_dir=Path(tempfile.mkdtemp(prefix='.azrael54-keepid-probe-',dir=storage_root))
            (probe_dir/'host-marker').write_text('AZRAEL_RW_MOUNT_OK\n')
            command=[podman,'run','--rm','--network','none','--userns=keep-id','--user',identity,
                     '-v',f'{probe_dir}:/probe:rw','docker.io/library/alpine:3.20','sh','-ec',
                     'test "$(cat /probe/host-marker)" = AZRAEL_RW_MOUNT_OK && printf container > /probe/container-marker && test "$(cat /probe/container-marker)" = container']
            result=subprocess.run(command,capture_output=True,text=True,timeout=60,cwd=ROOT)
            storage_result={'status':'passed' if result.returncode==0 else 'failed','root':str(storage_root),
                'returncode':result.returncode,'output':(result.stdout or '').strip()[-500:],
                'error':(result.stderr or '').strip()[-1500:] or None}
        except (OSError,subprocess.SubprocessError) as error:
            storage_result={'status':'failed','root':str(storage_root),'error':f'{type(error).__name__}: {error}'}
        finally:
            if probe_dir:
                shutil.rmtree(probe_dir,ignore_errors=True)
                storage_result['temporary_probe_removed']=not probe_dir.exists()
    elif storage_root.exists():
        storage_result={'status':'failed','root':str(storage_root),'reason':'storage root is not writable/traversable by the invoking user'}
    checks.append({'check':'azrael_storage_keep_id_rw','status':storage_result['status'],'detail':storage_result})
    diagnostics=_podman_rootless_diagnostics(podman)
    report={'runtime':info,'checks':checks,'diagnostics':diagnostics,
            'likely_cause':preflight_hypothesis(checks,diagnostics),'configuration_changed':False,
            'diagnostic_retries':diagnostic_retries,
            'existing_project_containers_touched':False,'persistent_project_data_changed':False,
            'temporary_probe_paths_removed':storage_result.get('temporary_probe_removed',True)}
    return report


def record_rootless_preflight():
    """Persist host evidence and fail closed before any Podman Compose start."""
    report=podman_rootless_preflight()
    failures=[item['check'] for item in report['checks'] if item.get('status')=='failed']
    result={'schema_version':2,'recorded_at':datetime.now(timezone.utc).isoformat(),
        'project':str(ROOT),'runtime':'podman','status':'failed' if failures else 'preflight_passed',
        'stage':'rootless_preflight','preflight':report,
        'note':'Disposable rootless probes only; no AZRAEL project container is started, stopped, or recreated.'}
    write_verification_report(result)
    print(json.dumps({'preflight':report},indent=2),flush=True)
    if failures:
        raise RuntimeError('Rootless Podman preflight failed for: '+', '.join(failures)+
            '; no AZRAEL build/start/recreation was attempted. Review the recorded mapping, OCI runtime, graphroot, and mount diagnostics.')
    return report


def ensure_dashboard_port_available(port):
    listener=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    try:
        listener.bind(('127.0.0.1',port))
    except OSError as error:
        raise RuntimeError(f'Cannot bind dashboard to 127.0.0.1:{port}: {error}. Check existing services and choose --port.') from error
    finally:listener.close()


def write_verification_report(report):
    """Atomically save runtime facts without recording credentials or model responses."""
    target=ROOT/'DEPLOYMENT-VERIFICATION.json'
    temporary=target.with_name(target.name+'.tmp')
    try:
        previous=json.loads(target.read_text())
        for key in ('host_diagnosis','deployment_history'):
            if key not in report and key in previous:report[key]=previous[key]
    except (OSError,ValueError):pass
    data=json.dumps(report,indent=2,sort_keys=True)+'\n'
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,target)


def host_gpu_inventory():
    smi=shutil.which('nvidia-smi')
    if not smi:return []
    result=subprocess.run([smi,'--query-gpu=index,name,uuid,memory.total,compute_cap','--format=csv,noheader'],
                          capture_output=True,text=True,timeout=8)
    if result.returncode:return []
    devices=[]
    for row in csv.reader(result.stdout.splitlines()):
        if len(row)>=5:
            devices.append({'index':row[0].strip(),'name':row[1].strip(),'uuid':row[2].strip(),
                            'memory_total':row[3].strip(),'compute_capability':row[4].strip()})
    return devices


def select_gpu_device():
    devices=host_gpu_inventory()
    if not devices:raise RuntimeError('nvidia-smi did not report any selectable NVIDIA GPU')
    requested=os.environ.get('AZRAEL_GPU_DEVICE','').strip()
    if not requested:
        selected=next((item for item in devices if 'rtx 3080' in item['name'].casefold()),None)
        if selected is None:raise RuntimeError('Default GPU selection targets the RTX 3080, but it was not found; set AZRAEL_GPU_DEVICE to an available GPU index')
        return {'selector':selected['index'],'devices':[selected]}
    if requested.casefold()=='all':return {'selector':'all','devices':devices}
    match=next((item for item in devices if requested in (item['index'],item['uuid']) or requested.casefold() in item['name'].casefold()),None)
    if not match:raise RuntimeError(f'AZRAEL_GPU_DEVICE={requested!r} does not match an installed GPU index, UUID, or model name')
    return {'selector':match['index'],'devices':[match]}


def gpu_status():
    smi=shutil.which('nvidia-smi');toolkit=shutil.which('nvidia-ctk')
    cdi={'status':'not_available','devices':[]}
    if toolkit:
        try:
            listed=subprocess.run([toolkit,'cdi','list'],capture_output=True,text=True,timeout=8)
            devices=[line.strip() for line in listed.stdout.splitlines()
                     if 'nvidia.com/gpu' in line]
            status='passed' if listed.returncode==0 and devices else 'failed'
            detail=(listed.stderr or '').strip()[-400:] if listed.returncode else None
            if listed.returncode==0 and not devices:detail='nvidia-ctk cdi list returned no nvidia.com/gpu devices'
            cdi={'status':status,'devices':devices,'error':detail}
        except (OSError,subprocess.SubprocessError) as error:cdi={'status':'failed','devices':[],'error':type(error).__name__}
    if not smi:return {'host_gpu_detected':False,'nvidia_container_toolkit':bool(toolkit),'nvidia_cdi':cdi,'container_gpu_visibility':'not_tested','cpu_fallback':'enabled','reason':'nvidia-smi is unavailable'}
    try:result=subprocess.run([smi,'--query-gpu=index,name,uuid,memory.total,compute_cap','--format=csv,noheader'],capture_output=True,text=True,timeout=8)
    except (OSError,subprocess.SubprocessError) as error:return {'host_gpu_detected':False,'nvidia_container_toolkit':bool(toolkit),'nvidia_cdi':cdi,'container_gpu_visibility':'not_tested','cpu_fallback':'enabled','reason':type(error).__name__}
    if result.returncode:return {'host_gpu_detected':False,'nvidia_container_toolkit':bool(toolkit),'nvidia_cdi':cdi,'container_gpu_visibility':'not_tested','cpu_fallback':'enabled','reason':(result.stderr or result.stdout).strip()[-400:] or 'NVIDIA driver did not respond'}
    gpus=host_gpu_inventory()
    return {'host_gpu_detected':bool(gpus),'devices':gpus,'nvidia_container_toolkit':bool(toolkit),'nvidia_cdi':cdi,'container_gpu_visibility':'not_tested','cpu_fallback':'enabled','reason':'Host detection alone is not container verification'}


def _gpu_remediation(toolkit_missing=False):
    steps=[]
    if toolkit_missing:steps.append('Install nvidia-container-toolkit so nvidia-ctk is available.')
    steps.extend(('Advisory only; no remediation commands were executed. On the host, run: sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml.',
                  'Regenerate the CDI spec after NVIDIA driver updates.'))
    return ' '.join(steps)


def container_graphroot(runtime):
    """Return the selected runtime's image-store root without changing it."""
    if runtime=='podman':
        executable=shutil.which('podman') or 'podman'
        result=subprocess.run([executable,'info','--format','json'],capture_output=True,text=True,timeout=15,cwd=ROOT)
        if result.returncode:raise RuntimeError('Could not read Podman graphroot: '+(result.stderr or result.stdout).strip()[-1000:])
        try:info=json.loads(result.stdout)
        except json.JSONDecodeError as error:raise RuntimeError('Podman info did not return valid JSON for graphroot inspection') from error
        store=info.get('store') or {}
        path=store.get('graphRoot') or store.get('graphroot') or store.get('GraphRoot')
    elif runtime=='docker':
        executable=shutil.which('docker') or 'docker'
        result=subprocess.run([executable,'info','--format','{{.DockerRootDir}}'],capture_output=True,text=True,timeout=15,cwd=ROOT)
        if result.returncode:raise RuntimeError('Could not read Docker graphroot: '+(result.stderr or result.stdout).strip()[-1000:])
        path=result.stdout.strip()
    else:raise ValueError('GPU graphroot check requires Podman or Docker')
    if not path:raise RuntimeError(f'{runtime} did not report its image storage root; GPU preflight fails closed')
    return Path(path).expanduser()


def gpu_disk_space_preflight(runtime,minimum_gb=None):
    """Fail closed if the runtime's graphroot filesystem is below the CUDA build reserve."""
    try:minimum_gb=int(os.environ.get('AZRAEL_GPU_MIN_FREE_GB','60')) if minimum_gb is None else int(minimum_gb)
    except (TypeError,ValueError) as error:raise RuntimeError('AZRAEL_GPU_MIN_FREE_GB must be a positive integer') from error
    if minimum_gb<1:raise RuntimeError('AZRAEL_GPU_MIN_FREE_GB must be a positive integer')
    graphroot=container_graphroot(runtime)
    try:free_bytes=shutil.disk_usage(graphroot).free
    except OSError as error:raise RuntimeError(f'Cannot measure free space for {runtime} graphroot {graphroot}; GPU build refused: {error}') from error
    required_bytes=minimum_gb*1024**3
    result={'runtime':runtime,'graphroot':str(graphroot),'free_bytes':free_bytes,
            'free_gib':round(free_bytes/1024**3,2),'minimum_free_gb':minimum_gb,
            'status':'passed' if free_bytes>=required_bytes else 'failed'}
    if free_bytes<required_bytes:
        message=(f"GPU disk-space gate: {result['free_gib']} GiB free on the {runtime} graphroot filesystem at {graphroot}; "
                 f'{minimum_gb} GiB is required. Moving graphroot to /data/work requires the same mapped-ID ancestor-traversal access as before.')
        print('WARNING: '+message,file=sys.stderr,flush=True)
        raise RuntimeError(message)
    return result


def _podman_cdi_compat_argv(command,env=None):
    """Apply the private compatibility spec when a rootless GPU probe needs CDI."""
    if not command or Path(command[0]).name!='podman':return command
    variables=os.environ if env is None else env
    spec_dir=variables.get('AZRAEL_CDI_COMPAT_SPEC_DIR')
    wrapper=ROOT/'container'/'podman-cdi-compat.sh'
    if not spec_dir:return command
    if not wrapper.is_file() or wrapper.is_symlink():
        raise RuntimeError('AZRAEL rootless CDI compatibility wrapper is missing or unsafe')
    return [shutil.which('podman') or command[0],'unshare',str(wrapper),spec_dir,*command]


def gpu_container_preflight(runtime,device_selector=None):
    """Require graphroot capacity and a real selected-device probe before CUDA work."""
    disk=gpu_disk_space_preflight(runtime)
    host=gpu_status()
    if not host['host_gpu_detected']:
        raise RuntimeError('Host NVIDIA GPU detection failed; use the CPU deployment without --gpu')
    if not host['nvidia_container_toolkit']:
        raise RuntimeError('nvidia-ctk is missing; the rootless CDI GPU preflight is blocked. '+_gpu_remediation(toolkit_missing=True))
    if host['nvidia_cdi']['status']!='passed':
        detail=host['nvidia_cdi'].get('error') or 'nvidia-ctk cdi list did not return an NVIDIA GPU device'
        raise RuntimeError('NVIDIA CDI is missing or unusable: '+detail+'. '+_gpu_remediation())
    if device_selector is None:
        selection=select_gpu_device()
    else:
        selected=next((item for item in host_gpu_inventory()
                       if device_selector in (item['uuid'],item['index'])),None)
        if selected is None:
            raise RuntimeError(f'GPU selector {device_selector!r} does not match a detected UUID or index')
        selection={'selector':selected['uuid'],'devices':[selected]}
    devices=[item for item in host['nvidia_cdi']['devices'] if 'nvidia.com/gpu=' in item]
    selected_device=f"nvidia.com/gpu={selection['selector']}"
    if not any(item==selected_device for item in devices):
        raise RuntimeError(f'nvidia-ctk cdi list does not contain selected device {selected_device}. '+_gpu_remediation())
    command=[shutil.which('podman') or 'podman','run','--rm','--pull=missing','--network=none',
             '--userns','keep-id','--device',selected_device,'docker.io/library/ubuntu:24.04','nvidia-smi']
    if runtime=='podman':command=_podman_cdi_compat_argv(command)
    try:result=subprocess.run(command,capture_output=True,text=True,timeout=180,cwd=ROOT)
    except (OSError,subprocess.SubprocessError) as error:
        raise RuntimeError('NVIDIA container GPU probe failed to run: '+str(error)+'. '+_gpu_remediation()) from error
    if result.returncode:
        raise RuntimeError('NVIDIA container GPU probe failed; keep CPU mode and inspect CDI/Container Toolkit: '+(result.stderr or result.stdout).strip()[-1200:]+'. '+_gpu_remediation())
    visible=[line.strip() for line in result.stdout.splitlines() if selection['devices'][0]['name'] in line]
    if not visible:raise RuntimeError('NVIDIA CDI probe exited successfully but nvidia-smi did not list the selected GPU. '+_gpu_remediation())
    if selection['devices'][0]['name'] not in result.stdout:
        raise RuntimeError('Container GPU probe succeeded but did not expose selected GPU '+selection['devices'][0]['name']+'. '+_gpu_remediation())
    if runtime=='docker':
        docker_command=[shutil.which('docker') or 'docker','run','--rm','--pull=missing','--network=none',
                        '--gpus',f"device={selection['selector']}",'docker.io/nvidia/cuda:12.8.1-base-ubuntu22.04','nvidia-smi']
        try:docker_result=subprocess.run(docker_command,capture_output=True,text=True,timeout=180,cwd=ROOT)
        except (OSError,subprocess.SubprocessError) as error:
            raise RuntimeError('Docker GPU visibility probe failed to run after the required Podman CDI probe: '+str(error)) from error
        if docker_result.returncode or selection['devices'][0]['name'] not in docker_result.stdout:
            raise RuntimeError('Docker GPU visibility probe failed: '+(docker_result.stderr or docker_result.stdout).strip()[-1200:])
    return {'status':'passed','runtime':'rootless-podman' if runtime=='podman' else 'docker','graphroot_disk_space':disk,'cdi_devices':devices,
            'selected_host_device':selection['devices'][0],'container_gpu_visibility':'passed','container_devices':visible,
            'podman_keep_id_probe':'passed','docker_gpu_probe':'passed' if runtime=='docker' else 'not_applicable'}


def _run_timed_phase(report,name,segment,operation):
    timing=report['timings'][name]
    timing['status']='running'
    write_verification_report(report)
    started=time.monotonic()
    try:
        result=operation()
    except Exception as error:
        elapsed=round(time.monotonic()-started,3)
        timing['segments'].append({'name':segment,'status':'failed','elapsed_seconds':elapsed,
                                   'error_type':type(error).__name__,'error':str(error)[:4000]})
        timing['elapsed_seconds']=round(sum(item['elapsed_seconds'] for item in timing['segments']),3)
        timing['status']='failed'
        write_verification_report(report)
        raise
    elapsed=round(time.monotonic()-started,3)
    timing['segments'].append({'name':segment,'status':'passed','elapsed_seconds':elapsed})
    timing['elapsed_seconds']=round(sum(item['elapsed_seconds'] for item in timing['segments']),3)
    timing['status']='passed'
    write_verification_report(report)
    return result


def _deployment_run_summary(report):
    return {key:report.get(key) for key in ('deployment_run_id','deployment_profile','recorded_at','status',
            'timings','verification','steps','failure')}


def _append_deployment_history(report):
    history=report.setdefault('deployment_history',[])
    run_id=report.get('deployment_run_id')
    if run_id and not any(item.get('deployment_run_id')==run_id for item in history):
        history.append(_deployment_run_summary(report))


def execute(commands,runtime,port=8765,verify=False,verify_model=False,verify_providers=False,non_interactive=False,gpu=False,rootless_preflight=None):
    if os.getuid()==0:raise ValueError('Run the installer as your ordinary project user')
    prior_report={}
    try:prior_report=json.loads((ROOT/'DEPLOYMENT-VERIFICATION.json').read_text())
    except (OSError,ValueError):pass
    history=list(prior_report.get('deployment_history',[]))
    prior_run=_deployment_run_summary(prior_report) if prior_report.get('deployment_run_id') else None
    if prior_run and not any(item.get('deployment_run_id')==prior_run.get('deployment_run_id') for item in history):
        history.append(prior_run)
    run_id=datetime.now(timezone.utc).isoformat()
    report={'schema_version':2,'recorded_at':datetime.now(timezone.utc).isoformat(),'project':str(ROOT),
            'runtime':runtime,'port_binding':f'127.0.0.1:{port}->frontend:8080','status':'running',
            'expected_local_images':LOCAL_IMAGES,'steps':[],'verification':{},
            'deployment_run_id':run_id,'deployment_profile':'cuda' if gpu else 'cpu','deployment_history':history,
            'timings':{
                'pull':{'status':'not_run','elapsed_seconds':None,'segments':[],
                        'scope':'Explicit Compose pull commands; base-image downloads performed during build are counted under build.'},
                'build':{'status':'not_run','elapsed_seconds':None,'segments':[],
                         'scope':'Compose image build command, including any base-image downloads it performs.'},
                'startup':{'status':'not_run','elapsed_seconds':None,'segments':[],
                           'scope':'Compose up and health wait for each staged service group.'},
                'inference':{'status':'not_run','elapsed_seconds':None,'segments':[],
                             'scope':'One actual SLM inference request inside the running dashboard container.'}},
            'rootless_preflight':rootless_preflight,
            'training_claim':'No training is inferred from service startup or research collection.'}
    write_verification_report(report)
    try:
        if runtime:report['runtime_probe']=runtime_probe(runtime)
        if gpu:
            gpu_report=gpu_container_preflight(runtime)
            report['steps'].append({'name':'gpu_cdi_container_visibility','status':'passed','result':gpu_report})
            print(json.dumps({'stage':'gpu_preflight',**gpu_report}),flush=True)
        needs_storage=any(any(part in {'build','up','restart'} for part in command[1:]) or
                      (Path(command[0]).name=='python' and any(str(ROOT/name) in command for name in ('setup_slm.py',))) or
                      ('pip' in command and 'install' in command) for command in commands)
        if needs_storage:
            storage_report=storage_paths.prepare_storage()
            minimum_gb=int(os.environ.get('AZRAEL_STORAGE_MIN_FREE_GB','20'))
            if storage_report['available_bytes']<minimum_gb*1024**3:
                raise RuntimeError(f"AZRAEL storage has {storage_report['available_bytes']//1024**3} GiB free; configured minimum is {minimum_gb} GiB")
            report['steps'].append({'name':'host_storage_preflight','status':'passed','result':storage_report})
            print(json.dumps({'stage':'storage_preflight','status':'passed','root':storage_report['root'],
                              'available_bytes':storage_report['available_bytes'],'write_readback':storage_report['write_readback']}),flush=True)
        if needs_storage:prepare_secrets()
        env=_env(port,gpu)
        if any('up' in command for command in commands):ensure_dashboard_port_available(port)
        for command in commands:
            display={'runtime':runtime,'program':Path(command[0]).name,'arguments':command[1:]}
            print(json.dumps({'stage':'running',**display}),flush=True)
            up_services=([service for service in (*INDEPENDENT_SERVICES,'dashboard',*FRONTEND_SERVICES) if service in command[command.index('-d')+1:]]
                         if 'up' in command and '-d' in command else [])
            def run_command():
                subprocess.run(command,cwd=ROOT,env=env,check=True,timeout=3600)
                if up_services:
                    return wait_for_services_healthy(runtime,up_services,timeout=300 if 'dashboard' in up_services else 180)
                return None
            if 'pull' in command:
                phase_result=_run_timed_phase(report,'pull','images: '+', '.join(command[command.index('pull')+1:]),run_command)
            elif 'build' in command:
                phase_result=_run_timed_phase(report,'build','Compose build',run_command)
            elif up_services:
                phase_result=_run_timed_phase(report,'startup','services: '+', '.join(up_services),run_command)
            else:
                phase_result=run_command()
            if up_services:
                states=phase_result or {}
                report['steps'].append({'name':'compose_up','services':up_services,'status':'passed','health':states})
            elif 'restart' in command:
                states=wait_for_services_healthy(runtime,(*INDEPENDENT_SERVICES,'dashboard',*FRONTEND_SERVICES),timeout=300)
                report['steps'].append({'name':'compose_restart','status':'passed','health':states})
            elif 'build' in command:
                report['steps'].append({'name':'image_build','status':'passed','runtime':runtime})
            elif 'config' in command:
                report['steps'].append({'name':'compose_config_validation','status':'passed','runtime':runtime})
            elif 'exists' in command or 'inspect' in command:
                report['steps'].append({'name':'local_image_present','status':'passed','image':command[-1]})
        results={}
        if verify:
            results={'dashboard':verify_dashboard(port),'internal_services':verify_internal_services(runtime),'gpu':gpu_status()}
            if gpu:results['cuda_runtime']=verify_gpu_container(runtime)
            if verify_model:
                results['slm_inference']=_run_timed_phase(report,'inference','SLM inference request',
                    lambda:verify_slm(runtime,require_gpu=gpu,gpu=gpu))
            if verify_providers:
                try:
                    host=f'127.0.0.1:{port}';headers={'Host':host,'Origin':'http://'+host,'X-Lab-Request':'1','Content-Type':'application/json'}
                    _,response_headers,_=_http(f'http://127.0.0.1:{port}/api/login','POST',json.dumps({'token':(ROOT/'.runtime/admin-token').read_text().strip()}).encode(),headers,timeout=10)
                    cookie=response_headers.get('Set-Cookie','').split(';',1)[0]
                    provider_result=verify_research_providers(port,cookie)
                    provider_result['status']='passed' if provider_result['retrieved']==len(provider_result['providers']) and provider_result['providers'] else 'partial'
                    results['research_provider_connectivity']=provider_result
                except (OSError,RuntimeError,ValueError,HTTPError,URLError) as error:
                    results['research_provider_connectivity']={'status':'failed','error_type':type(error).__name__}
        elif verify_model:
            results['slm_inference']=_run_timed_phase(report,'inference','SLM inference request',
                lambda:verify_slm(runtime,require_gpu=gpu,gpu=gpu))
        report['verification']=results
        required_checks=('dashboard','internal_services') if verify else ()
        passed=all(key in results for key in required_checks) and (not verify_model or results.get('slm_inference',{}).get('status')=='passed')
        if verify_providers and results.get('research_provider_connectivity',{}).get('status')!='passed':passed=False
        report['status']='passed' if passed and (verify or verify_model) else ('failed' if verify or verify_model else 'started_unverified')
        _append_deployment_history(report)
        write_verification_report(report)
        if verify:print(json.dumps({'verification':results},indent=2),flush=True)
        elif verify_model:print(json.dumps({'slm_inference':results['slm_inference']},indent=2),flush=True)
    except Exception as error:
        report['status']='failed'
        report['failure']={'type':type(error).__name__,'message':str(error)[:2000]}
        _append_deployment_history(report)
        write_verification_report(report)
        raise
    if commands and any(arg in ('up','restart') for command in commands for arg in command):
        print(f'Dashboard: http://127.0.0.1:{port}',flush=True)
        print('Admin login uses the protected .runtime/admin-token file; credential contents are not logged.',flush=True)
    print('Completed requested setup operation. No Compose down, volume prune or unrelated-container action was issued.',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',choices=('auto','podman','docker'),default='auto',help='auto prefers functional rootless Podman, then Docker Compose')
    parser.add_argument('--port',type=int,default=8765,help='Loopback dashboard host port (default: 8765)')
    parser.add_argument('--install',action='store_true',help='Install pinned Python libraries and prepare missing SLM weights')
    parser.add_argument('--build',action='store_true',help='Validate Compose, build project images and pull the owned lab image')
    parser.add_argument('--start',action='store_true',help='Start this project stack without replacing existing containers')
    parser.add_argument('--recreate-project-containers',action='store_true',help='Explicitly replace only this AZRAEL Compose project containers to apply changed images/config; volumes and unrelated containers are preserved')
    parser.add_argument('--stop',action='store_true',help='Stop only this project stack; preserve containers, images and volumes')
    parser.add_argument('--restart',action='store_true',help='Restart only this project stack')
    parser.add_argument('--status',action='store_true',help='Show selected runtime and this project Compose status')
    parser.add_argument('--preflight',action='store_true',help='Safely test rootless Podman, network isolation, bind mounts, and keep-id')
    parser.add_argument('--gpu-preflight',action='store_true',help='Test rootless NVIDIA CDI visibility on the selected GPU without changing the AZRAEL service stack')
    parser.add_argument('--storage-check',action='store_true',help='Create only missing private AZRAEL storage directories and verify mount, capacity and write/read persistence')
    parser.add_argument('--verify',action='store_true',help='Check dashboard auth/API and internal service health after startup')
    parser.add_argument('--verify-providers',action='store_true',help='Run one role-scoped public API retrieval connectivity check')
    parser.add_argument('--verify-slm',action='store_true',help='Run one real, offline inference inside the dashboard container')
    parser.add_argument('--verify-gpu',action='store_true',help='Verify CUDA PyTorch/device details in the dashboard and run measured inference on the selected GPU; requires --start or --status')
    parser.add_argument('--gpu',action='store_true',help='Opt in to NVIDIA CDI for dashboard SLM inference; requires a passing rootless Podman GPU container probe')
    parser.add_argument('--serve',action='store_true',help='After selected stages, watch for authenticated dashboard install requests')
    parser.add_argument('--non-interactive',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--plan',action='store_true',help='Print exact commands without installing or building')
    args=parser.parse_args()
    if not 1024<=args.port<=65535:parser.error('Port must be 1024–65535')
    lifecycle=sum((args.start,args.stop,args.restart,args.status))
    if lifecycle>1:parser.error('Choose at most one of --start, --stop, --restart or --status')
    if args.preflight and args.gpu_preflight:parser.error('Choose either --preflight or --gpu-preflight')
    if args.storage_check and any((args.install,args.build,args.start,args.stop,args.restart,args.status,args.preflight,args.gpu_preflight,args.verify,args.verify_slm,args.verify_gpu,args.verify_providers,args.serve)):
        parser.error('--storage-check runs by itself; use --plan to preview deployment stages')
    if args.storage_check:
        if args.plan:
            print(json.dumps({'storage_root':str(storage_paths.storage_root()),'creates_only_missing_private_directories':True,
                              'write_readback_probe':'temporary file under <root>/tmp, removed after success','execution':'none'},indent=2));return
        try:
            storage_report=storage_paths.prepare_storage()
            storage_report['capacity_status']='warning' if storage_report['available_bytes']<int(os.environ.get('AZRAEL_STORAGE_MIN_FREE_GB','20'))*1024**3 else 'ok'
            write_verification_report({'schema_version':2,'recorded_at':datetime.now(timezone.utc).isoformat(),
                'project':str(ROOT),'status':'storage_only','host_storage':storage_report,
                'note':'This is a storage preflight result, not a deployment health result.'})
            print(json.dumps({'storage_check':storage_report},indent=2));return
        except Exception as error:
            write_verification_report({'schema_version':2,'recorded_at':datetime.now(timezone.utc).isoformat(),
                'project':str(ROOT),'status':'failed','stage':'host_storage_preflight',
                'failure':{'type':type(error).__name__,'message':str(error)[:2000]}})
            raise
    if (args.preflight or args.gpu_preflight) and any((args.install,args.build,args.start,args.stop,args.restart,args.status,args.verify,args.verify_slm,args.verify_gpu,args.verify_providers,args.serve,args.gpu,args.recreate_project_containers)):
        parser.error('--preflight and --gpu-preflight run by themselves; use --plan to preview them')
    if (args.stop or args.restart or args.status) and (args.install or args.build):parser.error('--stop/--restart/--status cannot be combined with --install or --build')
    if args.recreate_project_containers and not args.start:parser.error('--recreate-project-containers requires --start')
    if args.verify_gpu:
        args.gpu=args.verify=True
        args.verify_slm=True
        if not (args.start or args.status):parser.error('--verify-gpu requires --start or --status so the live dashboard container can be checked')
    if (args.verify_slm or args.verify_providers) and not (args.verify or args.status):parser.error('--verify-slm and --verify-providers require --verify or --status')
    if args.status and args.verify:pass
    if args.gpu and any((args.stop,args.restart)):
        parser.error('--gpu applies only to build/start/status/verification')
    requested=any((args.install,args.build,args.start,args.stop,args.restart,args.status,args.verify,args.verify_gpu,args.serve,args.preflight,args.gpu_preflight,args.gpu,args.recreate_project_containers))
    if not requested:args.install=args.build=True
    runtime_needed=bool(args.build or args.start or args.stop or args.restart or args.status or args.verify or args.verify_slm or args.verify_providers or args.verify_gpu or args.preflight or args.gpu_preflight or args.gpu or args.recreate_project_containers)
    selected=select_runtime(args.runtime,verify=not args.plan) if runtime_needed else None
    if args.preflight:
        if selected!='podman':raise RuntimeUnavailable('--preflight requires functional rootless Podman; select it with --runtime podman')
        if args.plan:
            print(json.dumps({'runtime':selected,'preflight_checks':['simple rootless container','network=none isolation','read-only bind mount','minimal --userns=keep-id launch','AZRAEL UID/GID with keep-id','keep-id plus bind mount','read-write AZRAEL storage bind with keep-id','tmpfs/overlay mount'],'configuration_changed':False,'execution':'none'},indent=2));return
        try:report=podman_rootless_preflight()
        except Exception as error:
            write_verification_report({'schema_version':2,'recorded_at':datetime.now(timezone.utc).isoformat(),
                'project':str(ROOT),'runtime':'podman','status':'failed','stage':'rootless_preflight',
                'failure':{'type':type(error).__name__,'message':str(error)[:2000]}})
            raise
        print(json.dumps({'preflight':report},indent=2),flush=True)
        failures=[item['check'] for item in report['checks'] if item['status']!='passed']
        write_verification_report({'schema_version':2,'recorded_at':datetime.now(timezone.utc).isoformat(),
            'project':str(ROOT),'runtime':'podman','status':'failed' if failures else 'preflight_passed',
            'stage':'rootless_preflight','preflight':report,
            'note':'Preflight checks are not dashboard or inference verification.'})
        if failures:raise RuntimeError('Rootless Podman preflight failed for: '+', '.join(failures)+'; inspect the emitted diagnostics and host paths before changing permissions or storage settings')
        return
    if args.gpu_preflight:
        if selected!='podman':raise RuntimeUnavailable('--gpu-preflight currently verifies NVIDIA CDI through rootless Podman; select it with --runtime podman')
        if args.plan:
            print(json.dumps({'runtime':selected,'selected_gpu':os.environ.get('AZRAEL_GPU_DEVICE','RTX 3080 (default)'),
                              'container_probe':'isolated selected-device nvidia-smi','configuration_changed':False,'execution':'none'},indent=2));return
        try:
            result=gpu_container_preflight(selected)
            write_verification_report({'schema_version':2,'recorded_at':datetime.now(timezone.utc).isoformat(),
                'project':str(ROOT),'runtime':selected,'status':'gpu_preflight_passed','gpu_preflight':result,
                'note':'This verifies a disposable GPU probe, not application inference.'})
            print(json.dumps({'gpu_preflight':result},indent=2),flush=True)
        except Exception as error:
            write_verification_report({'schema_version':2,'recorded_at':datetime.now(timezone.utc).isoformat(),
                'project':str(ROOT),'runtime':selected,'status':'failed','stage':'gpu_preflight',
                'failure':{'type':type(error).__name__,'message':str(error)[:2000]}})
            raise
        return
    if args.status:
        command=compose_prefix(selected,args.gpu)+['ps']
        if args.plan:
            print(json.dumps({'runtime':selected,'commands':[command],'gpu':gpu_status(),
                              'gpu_container_preflight':'required_before_start' if args.gpu else 'not_requested','execution':'none'},indent=2));return
        info=runtime_probe(selected)
        print(json.dumps({'runtime':info,'gpu':gpu_status()},indent=2),flush=True)
        subprocess.run(command,cwd=ROOT,env=_env(args.port,args.gpu),check=True,timeout=60)
        if args.verify or args.verify_slm or args.verify_providers:
            result={'dashboard':verify_dashboard(args.port),'internal_services':verify_internal_services(selected),'gpu':gpu_status()}
            if args.verify_slm:result['slm_inference']=verify_slm(selected,require_gpu=args.gpu,gpu=args.gpu)
            if args.verify_providers:
                try:
                    host=f'127.0.0.1:{args.port}';headers={'Host':host,'Origin':'http://'+host,'X-Lab-Request':'1','Content-Type':'application/json'}
                    _,response_headers,_=_http(f'http://127.0.0.1:{args.port}/api/login','POST',json.dumps({'token':(ROOT/'.runtime/admin-token').read_text().strip()}).encode(),headers,timeout=10)
                    provider_result=verify_research_providers(args.port,response_headers.get('Set-Cookie','').split(';',1)[0])
                    provider_result['status']='passed' if provider_result['retrieved']==len(provider_result['providers']) and provider_result['providers'] else 'partial'
                    result['research_provider_connectivity']=provider_result
                except (OSError,RuntimeError,ValueError,HTTPError,URLError) as error:
                    result['research_provider_connectivity']={'status':'failed','error_type':type(error).__name__}
            print(json.dumps({'verification':result},indent=2),flush=True)
        return
    commands=plan(args.install,args.build,args.start,selected or args.runtime,args.port,args.stop,args.restart,False,args.gpu,args.recreate_project_containers)
    if args.plan:
        print(json.dumps({'runtime':selected,'port_binding':f'127.0.0.1:{args.port}->container:8765','commands':commands,
                          'post_start_verification':['dashboard health and authenticated API','internal imports/tools/external broker health'] if args.verify else [],
                          'slm_inference_verification':bool(args.verify_slm),
                          'recreate_project_containers':bool(args.recreate_project_containers),
                          'gpu_runtime_preflight_required':bool(args.gpu),
                          'gpu_inference_verification':bool(args.verify_gpu),
                          'research_provider_connectivity_verification':bool(args.verify_providers),'execution':'none'},indent=2));return
    if runtime_needed and selected is None:raise RuntimeUnavailable('A container runtime is needed for this operation')
    rootless_report=record_rootless_preflight() if selected=='podman' and args.start else None
    execute(commands,selected,args.port,args.verify,args.verify_slm,args.verify_providers,gpu=args.gpu,rootless_preflight=rootless_report)
    if args.serve:
        from installation import Installation
        report=storage_paths.prepare_storage()
        print(json.dumps({'stage':'storage_preflight','status':'passed','root':report['root'],'available_bytes':report['available_bytes']}),flush=True)
        Installation(ROOT,storage_paths.storage_root()/'setup').serve()


if __name__=='__main__':
    try:main()
    except (ValueError,RuntimeUnavailable,subprocess.SubprocessError,OSError,RuntimeError) as error:
        try:
            path=ROOT/'DEPLOYMENT-VERIFICATION.json'
            existing=json.loads(path.read_text()) if path.is_file() else {}
            if existing.get('status')!='failed':
                existing.update({'schema_version':2,'recorded_at':datetime.now(timezone.utc).isoformat(),
                    'project':str(ROOT),'status':'failed','stage':existing.get('stage','setup_command'),
                    'failure':{'type':type(error).__name__,'message':str(error)[:2000]}})
                write_verification_report(existing)
        except (OSError,ValueError):pass
        print('Setup failed: '+str(error),file=sys.stderr);sys.exit(1)
