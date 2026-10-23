"""Measured telemetry and conservative per-device admission; no memory pooling."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .store import ROOT,state_root


def gpus():
    query=['nvidia-smi','--query-gpu=index,uuid,name,memory.total,memory.free,memory.used,utilization.gpu','--format=csv,noheader,nounits']
    try:
        p=subprocess.run(query,capture_output=True,text=True,timeout=5)
        if p.returncode:return {'available':False,'devices':[],'error':(p.stderr or p.stdout).strip()[:400]}
        rows=[]
        for line in p.stdout.splitlines():
            index,uuid,name,total,free,used,util=[s.strip() for s in line.split(',')]
            rows.append({'index':int(index),'uuid':uuid,'name':name,'total_mib':int(total),'free_mib':int(free),
                         'used_mib':int(used),'utilization_percent':int(util)})
        return {'available':bool(rows),'devices':rows}
    except (OSError,ValueError,subprocess.SubprocessError) as e:return {'available':False,'devices':[],'error':str(e)[:400]}


def framework():
    import torch
    return {'python':sys.executable,'torch':torch.__version__,'cuda_build':torch.version.cuda,'cuda_available':torch.cuda.is_available(),
            'compiled_architecture_targets':getattr(torch._C,'_cuda_getArchFlags',lambda:'')().split() if torch.version.cuda else [],
            'cuda_count':torch.cuda.device_count(),'architecture_builds':torch.cuda.get_arch_list() if torch.version.cuda else []}


def memory_available():
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.startswith('MemAvailable:'):return int(line.split()[1])*1024
    return 0


def select_gpu(devices,selector,minimum_mib=512,fraction=.75):
    eligible=[d for d in devices if min(d['free_mib']-512,d['total_mib']*fraction)>=minimum_mib]
    if selector!='auto':eligible=[d for d in eligible if d['uuid']==selector]
    eligible.sort(key=lambda d:('RTX 3080' not in d['name'],-d['free_mib']))
    if not eligible:raise ValueError('No requested GPU UUID has sufficient measured free VRAM under the configured ceiling')
    return eligible[0]


def backend(name,image=None,device=None):
    if name=='local':return {'available':True,'runtime':'owned local Python child'}
    if name=='kubernetes':return {'available':False,'error':'Kubernetes execution is not enabled: a verified cluster, namespace and PVC mapping are required; no cluster is installed by this CLI'}
    exe=shutil.which(name)
    if not exe:return {'available':False,'error':name+' executable unavailable'}
    try:
        p=subprocess.run([exe,'info','--format','json' if name=='podman' else '{{json .}}'],capture_output=True,text=True,timeout=8)
        if p.returncode:return {'available':False,'error':(p.stderr or p.stdout).strip()[:500]}
        if not image:return {'available':False,'error':'Specify --image with an already built isolated training image'}
        p=subprocess.run([exe,'image','inspect',image],capture_output=True,text=True,timeout=8)
        if p.returncode:return {'available':False,'error':'Training image is not present; build container/Dockerfile.training explicitly'}
        # Actually verify imports inside the selected image, isolated from production networks.
        probe=[exe,'run','--rm','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
               '--memory','2g','--pids-limit','64']
        code='import torch,transformers; print(torch.__version__)'
        if device:
            probe+=(['--device','nvidia.com/gpu='+device] if name=='podman' else ['--gpus','device='+device])
            code='import torch,transformers; x=torch.ones((8,8),device="cuda"); y=x@x; torch.cuda.synchronize(); assert y[0,0].item()==8; print(torch.cuda.get_device_name())'
        p=subprocess.run(probe+[image,'python','-c',code],
                         capture_output=True,text=True,timeout=30)
        if p.returncode:return {'available':False,'error':'Image dependency probe failed: '+p.stderr[-500:]}
        return {'available':True,'runtime':name,'image':image,'image_probe':p.stdout.strip()}
    except (OSError,subprocess.SubprocessError) as e:return {'available':False,'error':str(e)[:500]}


def preflight(config):
    from .registry import model_info
    info=model_info(config['model']);fw=framework();devices=gpus();errors=[];selected=None
    recipe=config.get('recipe') or ('lora' if info['type']=='coding-slm' else 'classifier')
    if info['type']=='discovered-classifier':errors.append('This discovered role model has no training recipe; select secret-classifier or exploit-classifier')
    if info['type']=='coding-slm' and recipe not in {'lora','qlora'}:errors.append('Coding SLM supports adapter recipe lora; qlora requires optional compatible dependencies')
    if info['type']!='coding-slm' and recipe!='classifier':errors.append('Classifier models require recipe classifier')
    if not info['available']:errors.append('Original checkpoint is unavailable')
    if recipe=='qlora':
        missing=[x for x in ['peft','bitsandbytes','accelerate'] if importlib.util.find_spec(x) is None]
        errors.append('QLoRA is not enabled/validated in this installation'+('; missing '+', '.join(missing) if missing else '; use verified lora recipe'))
    device=config.get('device','cpu')
    if device!='cpu':
        try:candidates=[select_gpu(devices['devices'],device,4600 if info['type']=='coding-slm' else 512,float(config.get('memory_fraction',.75)))]
        except ValueError as e:
            candidates=[]
            errors.append(str(e) if devices['devices'] else 'No GPU is visible to nvidia-smi: '+devices.get('error','empty inventory'))
        if candidates and not fw['cuda_available']:
            detail=('CPU-only PyTorch '+fw['torch'] if not fw['cuda_build'] else 'PyTorch '+fw['torch']+' cannot initialize a CUDA device')
            errors.append('Training interpreter '+fw['python']+': '+detail+'; check gpu list and host nvidia-smi')
        elif candidates:
            import torch
            selected=candidates[0]
            try:
                # Ordinal mapping validated against actual framework properties/UUID.
                matching=[]
                for i in range(torch.cuda.device_count()):
                    prop=torch.cuda.get_device_properties(i)
                    if str(getattr(prop,'uuid','')).lower()==selected['uuid'].lower():matching.append(i)
                if len(matching)!=1:raise ValueError('Framework cannot uniquely map the selected hardware UUID')
                with torch.cuda.device(matching[0]):
                    x=torch.ones((8,8),device='cuda'); y=x@x;torch.cuda.synchronize()
                    if y[0,0].item()!=8:raise ValueError('CUDA tensor smoke failed')
                    del x,y;torch.cuda.empty_cache()
            except Exception as e:errors.append('CUDA execution preflight failed: '+str(e))
    fraction=float(config.get('memory_fraction',.75))
    if not .1<=fraction<=.9:errors.append('Memory fraction must be between 0.1 and 0.9')
    length=int(config.get('max_length',128));batch=int(config.get('batch_size',1))
    # Upper-bound attention/activation buffers grow with sequence length and
    # microbatch size; accumulation does not multiply their simultaneous size.
    activation=batch*(length*1536*28*96 + 12*length*length*28*8 + length*151936*4)
    required=(int(Path(info['checkpoint']).stat().st_size*2.6)+activation+1024**3) if info['type']=='coding-slm' and info['available'] else 512*1024**2
    if device=='cpu' and memory_available()<required+1024**3:errors.append('Insufficient available host RAM for the conservative estimate')
    if selected:
        estimate=int((Path(info['checkpoint']).stat().st_size+activation+1024**3)/1024**2) if info['type']=='coding-slm' else 512
        if min(selected['free_mib']-512,selected['total_mib']*fraction)<estimate:errors.append('Insufficient unallocated VRAM under the configured memory ceiling')
    minimum=512*1024**2 if info['type']=='coding-slm' else 192*1024**2
    free=shutil.disk_usage(state_root()).free
    reserve_gb=float(os.environ.get('AZTREAL_MIN_FREE_GB','5'))
    if not 0<=reserve_gb<=1024:raise ValueError('AZTREAL_MIN_FREE_GB must be 0–1024')
    reserve=int(reserve_gb*1024**3)
    if free<minimum+reserve:errors.append('Insufficient disk headroom: checkpoint estimate plus configured free-space reserve')
    runtime=backend(config.get('backend','local'),config.get('image'),selected['uuid'] if selected else None)
    if not runtime['available']:errors.append(runtime['error'])
    return {'eligible':not errors,'errors':errors,'model':info,'recipe':recipe,'framework':fw,'gpu_inventory':devices,
        'selected_gpu':selected,'backend':runtime,'output_root':str(state_root()),'disk_free_bytes':free,
        'estimated_checkpoint_optimizer_bytes':minimum,'estimated_host_ram_bytes':required,'minimum_free_reserve_bytes':reserve,'available_host_ram_bytes':memory_available(),
        'recommended_batch_size':1,'gradient_accumulation':config.get('gradient_accumulation',4),
        'distributed_training':False,'estimate_note':'Conservative admission estimate, not a promise against OOM; tensor smoke does not prove model training compatibility.'}
