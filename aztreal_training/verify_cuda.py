"""Sequential host diagnostics; GPU PASS requires actual device/optimizer evidence."""
import argparse
from datetime import datetime,timezone
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

from .store import ROOT,redacted,sha

EXPECTED={'GPU-e6a4de67-74d6-38f7-e185-214a092dd995':'RTX 3080',
          'GPU-5aa46030-9e89-432f-ecfe-90daf9d56e30':'RTX 5060',
          'GPU-ef312e7d-5cf1-e04c-eeff-2f1c1c80ce6e':'RTX 3060 Ti'}
UUID=re.compile(r'GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}')
INIT_PROBE='import json,os,torch; x=torch.ones((8,8),device="cuda:0"); y=x@x; torch.cuda.synchronize(); assert y[0,0].item()==8; p=torch.cuda.get_device_properties(0); assert str(p.uuid)==os.environ["CUDA_VISIBLE_DEVICES"]; print(json.dumps(dict(uuid=str(p.uuid),name=p.name,compute_capability=f"{p.major}.{p.minor}",device=str(x.device),allocated_bytes=torch.cuda.memory_allocated())))'


def now():return datetime.now(timezone.utc).isoformat()


def save(path,value):
    with Path(path).open('w') as stream:json.dump(value,stream,indent=2,allow_nan=False);stream.write('\n')
    Path(path).chmod(0o600)


def command(argv,env=None,timeout=15):
    row={'at':now(),'command':argv};started=time.monotonic()
    try:
        p=subprocess.run(argv,cwd=ROOT,env=env,capture_output=True,text=True,timeout=timeout)
        row.update(exit_code=p.returncode,stdout=redacted(p.stdout),stderr=redacted(p.stderr))
    except (OSError,subprocess.TimeoutExpired) as e:row.update(exit_code=None,error=redacted(e))
    row['elapsed_seconds']=round(time.monotonic()-started,3);return row


def parsed(row):
    try:return json.loads(row.get('stdout',''))
    except ValueError:return None


def inventory():
    query=['nvidia-smi','--query-gpu=index,uuid,name,driver_version,compute_cap,memory.total,memory.free,memory.used,utilization.gpu','--format=csv,noheader,nounits']
    result=command(query);rows={}
    if result['exit_code']==0:
        for line in result['stdout'].splitlines():
            index,device,name,driver,cap,total,free,used,util=[s.strip() for s in line.split(',')]
            if not UUID.fullmatch(device):raise ValueError('Driver returned an invalid GPU UUID')
            rows[device]={'uuid':device,'name':name,'index':int(index),'driver':driver,'compute_capability':cap,
                'total_mib':int(total),'free_mib':int(free),'used_mib':int(used),'utilization_percent':int(util),'source':'live nvidia-smi'}
    # Metadata fallback identifies attempted selectors, never live hardware success.
    for device,name in EXPECTED.items():
        rows.setdefault(device,{'uuid':device,'expected_name':name,'source':'historical CDI expectation; not a live identity'})
    return result,list(rows.values())


def processes():
    result=command(['nvidia-smi','--query-compute-apps=gpu_uuid,pid,used_gpu_memory','--format=csv,noheader,nounits'])
    rows=[]
    if result['exit_code']==0:
        for line in result['stdout'].splitlines():
            parts=[s.strip() for s in line.split(',')]
            if len(parts)==3 and parts[1].isdigit():rows.append({'uuid':parts[0],'pid':int(parts[1]),'used_mib':parts[2]})
    return result,rows


def cuda_execution(job,expected):
    ev=job.get('execution_evidence') or {}
    places=ev.get('parameter_devices',[])+ev.get('gradient_devices',[])+[ev.get(k,'') for k in ['input_device','target_device','loss_device']]
    span=ev.get('cuda_span_ms',0)
    return bool(job.get('state')=='completed' and job.get('assigned_device')==expected and job.get('actual_cuda_uuid')==expected
        and ev.get('parameter_devices') and ev.get('gradient_devices') and all(p.startswith('cuda:') for p in places)
        and ev.get('optimizer_updated_parameters') is True and math.isfinite(span) and span>0
        and job.get('step',0)>0 and job.get('peak_gpu_memory_bytes',0)>0)


def sample_summary(samples):
    readings=[]
    for sample in samples:
        if sample.get('exit_code')!=0:continue
        try:
            device,used,free,util=[p.strip() for p in sample['stdout'].strip().split(',')]
            if UUID.fullmatch(device):readings.append((int(used),int(free),int(util)))
        except (KeyError,ValueError):continue
    return {'sample_count':len(readings),'peak_sampled_used_mib':max((r[0] for r in readings),default=None),
            'minimum_sampled_free_mib':min((r[1] for r in readings),default=None),
            'peak_sampled_utilization_percent':max((r[2] for r in readings),default=None)}


SUPERVISOR='''
import json,sys
from pathlib import Path
from aztreal_training import jobs
from aztreal_training.verify_cuda import save
job=None
try:
    job=jobs.start(dict(model='secret-classifier',recipe='classifier',backend='local',device=sys.argv[1],epochs=1,batch_size=8),sys.argv[2])
    save(Path(sys.argv[3]),{'id':job['id']})
    print(json.dumps(jobs.wait(job['id'],120)))
except Exception:
    if job and jobs.get(job['id'])['state'] in jobs.ACTIVE:
        jobs.stop(job['id'])
        try:jobs.wait(job['id'],30)
        except Exception:pass
    raise
'''


def train(device,dataset,directory,env):
    reference=directory/'owned-job.json';samples=[];started=time.monotonic()
    with (directory/'supervisor.stdout').open('w') as out,(directory/'supervisor.stderr').open('w') as err:
        child=subprocess.Popen([sys.executable,'-B','-c',SUPERVISOR,device,dataset,str(reference)],cwd=ROOT,env=env,stdout=out,stderr=err)
        while child.poll() is None and time.monotonic()-started<165:
            sample=command(['nvidia-smi','--id='+device,'--query-gpu=uuid,memory.used,memory.free,utilization.gpu','--format=csv,noheader,nounits'],timeout=5)
            samples.append(sample);time.sleep(.2)
        timed_out=child.poll() is None
        if timed_out:
            # This is only the owned diagnostic supervisor, never a deployed service.
            if reference.exists():
                own=json.loads(reference.read_text())['id']
                command([str(ROOT/'aztrealcli'),'training','stop','--job',own],env,timeout=10)
            child.terminate()
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:child.kill();child.wait()
    text=(directory/'supervisor.stdout').read_text();error=(directory/'supervisor.stderr').read_text()
    try:job=json.loads(text)
    except ValueError:job=None
    result={'at':now(),'exit_code':child.returncode,'timed_out':timed_out,'job':job,'error':redacted(error),'samples':samples,
            'sample_summary':sample_summary(samples),'supervisor_pid':child.pid,'elapsed_seconds':round(time.monotonic()-started,3)}
    if not job or not cuda_execution(job,device):result.update(status='FAIL',release_status='NOT TESTED');return result
    from .registry import verify
    verify(Path(job['directory'])/'checkpoints')
    result['checkpoint_sha256']=sha(job['checkpoint'])
    if job.get('driver_namespace')!=os.readlink('/proc/self/ns/pid'):
        result.update(status='PASS',release_status='BLOCKED',release_reason='Worker PID namespace differs; host process IDs cannot be compared safely')
        return result
    # Test PID disappearance, not a global VRAM drop that unrelated apps can change.
    owned={child.pid,job['worker_pid']};deadline=time.monotonic()+8;release_rows=[]
    while time.monotonic()<deadline:
        observation,pids=processes();release_rows.append(observation)
        if observation['exit_code']!=0:break
        if not any(p['uuid']==device and p['pid'] in owned for p in pids):break
        time.sleep(.25)
    released=observation['exit_code']==0 and not any(p['uuid']==device and p['pid'] in owned for p in pids)
    result.update(status='PASS',release_status='PASS' if released else 'BLOCKED',release_observations=release_rows)
    return result


def container_probe(engine,image,device,run_id,directory):
    exe=('/snap/docker/current/bin/docker' if engine=='docker' and Path('/snap/docker/current/bin/docker').is_file() else shutil.which(engine))
    if not exe:return {'status':'BLOCKED','reason':engine+' executable missing'}
    engine_check=command([exe,'ps','--format','json' if engine=='podman' else '{{json .}}'])
    if engine_check['exit_code']!=0:return {'status':'BLOCKED','reason':'Engine unavailable','engine_check':engine_check}
    if not device:return {'status':'BLOCKED','reason':'No idle GPU passed local CUDA tensor computation','engine_check':engine_check}
    available,active=processes()
    if available['exit_code']!=0 or any(p['uuid']==device for p in active):
        return {'status':'BLOCKED','reason':'GPU busy or fresh process visibility unavailable; no container launched','process_check':available}
    image=image or 'localhost/azrael54-dashboard:latest'
    inspected=command([exe,'image','inspect',image,'--format','{{.Id}}'])
    if inspected['exit_code']!=0:return {'status':'BLOCKED','reason':'A compatible local image is required; no pulls/builds performed','image_check':inspected}
    name='aztreal-cuda-verify-'+run_id+'-'+engine
    bootstrap='import os,sys,runpy; p="/app/.slm-venv/bin/python"; os.execv(p,[p,"-B","/audit/gpu_probe.py"]) if os.path.isfile(p) and sys.executable!=p else runpy.run_path("/audit/gpu_probe.py",run_name="__main__")'
    argv=[exe,'run','--pull=never','--rm','--name',name,'--label','aztreal.verification='+run_id,
          '--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
          '--memory','2g','--cpus','1','--pids-limit','64','--user',f'{os.getuid()}:{os.getgid()}',
          '--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=64m','-w','/audit',
          '-v',f'{ROOT}/gpu_probe.py:/audit/gpu_probe.py:ro','-v',f'{ROOT}/gpu_runtime.py:/audit/gpu_runtime.py:ro',
          '-e','CUDA_VISIBLE_DEVICES='+device,'-e','AZRAEL_GPU_EXPECTED_UUIDS='+device,'-e','PYTHONDONTWRITEBYTECODE=1']
    argv+=(['--userns=keep-id','--device','nvidia.com/gpu='+device] if engine=='podman' else ['--gpus','device='+device])
    argv+=['--entrypoint','python',inspected['stdout'].strip(),'-B','-c',bootstrap]
    attempt=command(argv,timeout=45)
    proof=parsed(attempt)
    result={'status':'PASS' if attempt['exit_code']==0 and proof and proof.get('status')=='passed' else 'FAIL',
            'image_id':inspected.get('stdout','').strip(),'attempt':attempt}
    if attempt['exit_code'] is None:
        label=command([exe,'inspect',name,'--format','{{index .Config.Labels "aztreal.verification"}}'])
        if label['exit_code']==0 and label.get('stdout','').strip()==run_id:
            result['owned_cleanup']=command([exe,'rm','--force',name])
        else:result['cleanup_status']='BLOCKED: ownership could not be verified; no container removed'
    return result


def append_report(report,path):
    lines=['',f'## Sequential CUDA verification attempt — {report["at"]}',
           f'Evidence: `{path.relative_to(ROOT)}/results.json`. Overall: **{report["status"]}**.',
           '','| GPU selector | Identity source | Tensor/optimizer probe | Classifier training | Resource release |',
           '|---|---|---|---|---|']
    for r in report['devices']:
        info=r['identity'];label=info.get('name',info.get('expected_name','unidentified'))
        lines.append(f'| {label} / `{info["uuid"]}` | {info["source"]} | {r["tensor_status"]} | {r["training_status"]} | {r.get("release_status","NOT TESTED")} |')
    lines+=['',f'Podman passthrough: **{report["containers"]["podman"]["status"]}**. Docker passthrough: **{report["containers"]["docker"]["status"]}**.',
            'Live UUID, compute capability, driver, available VRAM, loss, tensor devices, CUDA event span, utilization samples and checkpoint hashes are recorded only when observed in the JSON evidence.',
            'Historical CDI selectors are expectations, not independently verified GPU identities. No CPU fallback is accepted for these GPU tests.',
            'A 0% utilization sample can miss a very short kernel; it is retained as measured and cannot substitute for tensor-device and optimizer-update proof.',
            'No production container, checkpoint or database is used as writable test storage. The fixture must already be approved and explicitly synthetic.',
            '', 'Host command: `./verify_training_cuda.py` (optional existing images: `--podman-image IMAGE --docker-image IMAGE`).',
            'This command creates one-epoch isolated candidates sequentially only after prerequisites pass; it does not download images/model weights or start a deployment stack.','']
    with (ROOT/'recovery/final-verification/AZTREALCLI-CUDA-REPAIR.md').open('a') as stream:stream.write('\n'.join(lines))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',default='2b08ded67d5200c192a6f556')
    parser.add_argument('--podman-image');parser.add_argument('--docker-image')
    args=parser.parse_args(argv)
    os.environ.setdefault('AZTREAL_STATE_DIR',str(ROOT/'training-state'))
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:6]
    directory=ROOT/'recovery/final-verification'/('cuda-runtime-'+run_id);directory.mkdir(mode=0o700)
    context={'at':now(),'uid':os.getuid(),'pid_namespace':os.readlink('/proc/self/ns/pid'),
             'device_nodes':{p:Path(p).exists() for p in ['/dev/nvidia0','/dev/nvidia1','/dev/nvidia2','/dev/nvidiactl','/dev/nvidia-uvm']},
             'cdi_expected_uuid_present':{device:device in Path('/etc/cdi/nvidia.yaml').read_text() for device in EXPECTED} if Path('/etc/cdi/nvidia.yaml').is_file() else None}
    save(directory/'execution-context.json',context)
    env=dict(os.environ,OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    initial,devices=inventory();save(directory/'inventory.json',initial)
    save(directory/'auto-preflight.json',command([str(ROOT/'aztrealcli'),'training','preflight','--model','secret-classifier','--backend','local','--device','auto'],env,30))
    report={'at':now(),'python':sys.executable,'devices':[],'containers':{},'run_id':run_id};can_continue=True;eligible_for_container=[]
    for info in sorted(devices,key=lambda r:('3080' not in r.get('name',r.get('expected_name','')),r['uuid'])):
        device=info['uuid'];folder=directory/device;folder.mkdir(mode=0o700)
        localenv=dict(env,CUDA_VISIBLE_DEVICES=device,AZRAEL_GPU_EXPECTED_UUIDS=device)
        row={'identity':info,'tensor_status':'BLOCKED','training_status':'BLOCKED','release_status':'NOT TESTED'}
        preflight=command([str(ROOT/'aztrealcli'),'training','preflight','--model','secret-classifier','--backend','local','--device',device],localenv,30)
        save(folder/'preflight.json',preflight)
        proc_status,busy=processes();save(folder/'processes-before.json',proc_status)
        from . import jobs,datasets
        active=any(j['assigned_device']==device and (j['state'] in jobs.ACTIVE or jobs.driver_alive(j)) for j in jobs.list_jobs())
        busy_gpu=any(r['uuid']==device for r in busy)
        if not can_continue or active or busy_gpu or info.get('utilization_percent',0)>10:
            row['reason']='GPU already busy/reserved, or prior owned-worker cleanup unconfirmed'
        else:
            initialization=command([sys.executable,'-B','-c',INIT_PROBE],localenv,30)
            save(folder/'cuda-initialization.json',initialization)
            probe=command([sys.executable,'-B',str(ROOT/'gpu_probe.py')],localenv,30);save(folder/'tensor-probe.json',probe)
            proof=parsed(probe)
            passed=initialization['exit_code']==0 and probe['exit_code']==0 and proof and proof.get('status')=='passed'
            row['tensor_status']='PASS' if passed else ('BLOCKED' if initial['exit_code']!=0 else 'FAIL')
            result=parsed(preflight)
            if passed and proc_status['exit_code']==0:eligible_for_container.append(device)
            if passed and result and result.get('eligible') and proc_status['exit_code']==0:
                try:
                    manifest,records,_=datasets.admitted(args.dataset)
                    if manifest['kind']!='classifier' or manifest['synthetic']!='yes' or len(records)>1000:raise ValueError('Verification requires an approved synthetic classifier fixture of at most 1000 records')
                except (ValueError,OSError) as error:row['reason']='Training admission blocked: '+redacted(error)
                else:
                    training=train(device,args.dataset,folder,localenv);save(folder/'training.json',training)
                    row.update(training_status=training['status'],release_status=training['release_status'])
                    can_continue=training['release_status']=='PASS'
            else:row['reason']='CUDA/preflight/process-visibility prerequisite unavailable; no training launched'
        report['devices'].append(row)
    for engine in ['podman','docker']:
        result=container_probe(engine,getattr(args,engine+'_image'),eligible_for_container[0] if eligible_for_container and can_continue else None,run_id,directory)
        report['containers'][engine]=result;save(directory/(engine+'.json'),result)
    statuses=[r[k] for r in report['devices'] for k in ['tensor_status','training_status','release_status']]+[r['status'] for r in report['containers'].values()]
    report['status']='PASS' if statuses and all(s=='PASS' for s in statuses) else ('FAIL' if 'FAIL' in statuses else 'BLOCKED')
    save(directory/'results.json',report);append_report(report,directory)
    print(json.dumps({'status':report['status'],'evidence':str(directory/'results.json'),'devices':report['devices'],'container_status':{k:v['status'] for k,v in report['containers'].items()}},indent=2))
    return 0 if report['status']=='PASS' else 2
