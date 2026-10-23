"""Owned training child. All writes stay in isolated candidate/job directories."""
import json
import math
import os
from pathlib import Path
import signal
import sys
import resource
import threading
from types import SimpleNamespace

from .store import ROOT,read,write,sha,now,redacted
from . import jobs,registry


class Paused(Exception):pass


def save_torch(path,data):
    import torch
    temp=path.with_suffix('.pending')
    torch.save(data,temp);temp.chmod(0o600)
    with temp.open('rb') as stream:os.fsync(stream.fileno())
    os.replace(temp,path)


def stopped(directory):return (directory/'stop').exists()


def snapshot(job,state,**progress):
    directory=Path(job['directory']);checkpoint=directory/'checkpoints'/'resume.pt'
    save_torch(checkpoint,dict(state,fingerprint=job['fingerprint'],base_sha256=job['base_sha256']))
    registry.checkpoint_manifest(checkpoint.parent)
    jobs.update(job['id'],resume_checkpoint=str(checkpoint),**progress)
    print(json.dumps({'at':now(),**progress}),flush=True)
    if stopped(directory):raise Paused()


def classifier(job,inputs,device):
    import torch
    import model
    directory=Path(job['directory']);task='secret' if job['model']=='secret-classifier' else 'exploit'
    custom=directory/'classifier.jsonl'
    if not custom.exists():
        fd=os.open(custom,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as stream:
            for row in inputs['records']:stream.write(json.dumps({'task':task,'text':row['text'],'label':row['label']})+'\n')
    partition={row['text']:split for split,rows in inputs['parts'].items() for row in rows}
    resume=torch.load(job['resume_checkpoint'],map_location=device,weights_only=True) if job.get('resume_checkpoint') else None
    if resume and resume['fingerprint']!=job['fingerprint']:raise ValueError('Resume fingerprint mismatch')
    def checkpoint(state):
        h=state['history'][-1] if state['history'] else {}
        snapshot(job,state,epoch=state['epoch'],step=state['optimizer_steps'],loss=h.get('training_loss'),
                 validation_loss=h.get('validation_loss'),learning_rate=job['config']['learning_rate'],stage='training',
                 execution_evidence=state.get('execution_evidence'))
    cfg=job['config']
    args=SimpleNamespace(csv=str(directory/'no-implicit-public-data.csv'),custom=[str(custom)],synthetic_count=0,
        out=str(directory/'checkpoints'),epochs=cfg['epochs'],patience=cfg['patience'],per_class=0,
        tasks=[task],device=str(device),partition_map=partition,resume_state=resume,checkpoint_callback=checkpoint)
    args.batch_size=cfg['batch_size']
    args.dataset_metadata={k:inputs['manifest'][k] for k in ['id','source','license','synthetic','approved','reviewer','records_sha256','split']}
    # Existing default remains .003; honor an explicit managed recipe LR via its optimizer hook.
    args.learning_rate=cfg['learning_rate']
    model.train(args)
    return directory/'checkpoints'/(task+'.pt')


def load_slm(job,device):
    import torch
    from transformers import AutoModelForCausalLM,AutoTokenizer
    from . import lora
    path=Path(job['base_checkpoint']).parent
    tokenizer=AutoTokenizer.from_pretrained(path,local_files_only=True,trust_remote_code=False)
    dtype=torch.float32 if device.type=='cpu' else (torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16)
    model=AutoModelForCausalLM.from_pretrained(path,local_files_only=True,trust_remote_code=False,torch_dtype=dtype,use_safetensors=True)
    model.to(device);model.config.use_cache=False
    targets=lora.install(model,job['config']['rank'])
    return model,tokenizer,targets,dtype


def slm(job,inputs,device):
    import torch
    from . import lora
    cfg=job['config'];directory=Path(job['directory']);model,tokenizer,targets,dtype=load_slm(job,device)
    if cfg.get('gradient_checkpointing',True):
        model.gradient_checkpointing_enable();model.enable_input_require_grads()
    opt=torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],lr=cfg['learning_rate'])
    scaler=torch.amp.GradScaler('cuda',enabled=device.type=='cuda' and dtype==torch.float16)
    epoch=0;cursor=0;step=0;history=[]
    if job.get('resume_checkpoint'):
        state=torch.load(job['resume_checkpoint'],map_location=device,weights_only=True)
        if state['fingerprint']!=job['fingerprint']:raise ValueError('Resume fingerprint mismatch')
        lora.load_adapter(model,state['adapter']);opt.load_state_dict(state['optimizer']);scaler.load_state_dict(state['scaler'])
        epoch=state['epoch'];cursor=state['cursor'];step=state['step'];history=state['history'];torch.set_rng_state(state['rng'].cpu())
    def checkpoint():
        state={'adapter':lora.adapter_state(model),'optimizer':opt.state_dict(),'scaler':scaler.state_dict(),
               'epoch':epoch,'cursor':cursor,'step':step,'history':history,'rng':torch.get_rng_state()}
        snapshot(job,state,epoch=epoch,step=step,loss=history[-1]['loss'] if history else None,
                 validation_loss=history[-1].get('validation_loss') if history else None,stage='training',learning_rate=cfg['learning_rate'])
    checkpoint()
    train=inputs['parts']['train'];accum=cfg['gradient_accumulation'];batch_size=cfg['batch_size']
    while epoch<cfg['epochs'] and step<cfg['max_steps']:
        model.train();opt.zero_grad();loss_sum=0.;micro=0
        while cursor<len(train) and micro<accum:
            rows=train[cursor:cursor+batch_size];data=lora.batch(tokenizer,rows,cfg['max_length'],device)
            loss=model(**data).loss
            if not bool(torch.isfinite(loss)):raise ValueError('Nonfinite training loss')
            scaler.scale(loss/accum).backward();loss_sum+=float(loss.item());cursor+=len(rows);micro+=1
        if not micro:raise ValueError('Empty training accumulation')
        if micro<accum:
            # Normalize the final partial accumulation to its actual sample count.
            for p in model.parameters():
                if p.requires_grad and p.grad is not None:p.grad.mul_(accum/micro)
        scaler.unscale_(opt);torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad],1.)
        scaler.step(opt);scaler.update();step+=1
        end=cursor>=len(train)
        if end:epoch+=1;cursor=0
        validation=lora.heldout_loss(model,tokenizer,inputs['parts']['validation'],cfg['max_length'],device)
        history.append({'step':step,'epoch':epoch,'loss':loss_sum/micro,'validation_loss':validation,'learning_rate':cfg['learning_rate']})
        checkpoint()
    output=directory/'checkpoints'/'adapter.pt';save_torch(output,lora.adapter_state(model))
    write(output.parent/'adapter-config.json',{'format':'aztreal-native-lora-v1','rank':cfg['rank'],'scale':2.,'targets':targets,
         'base_sha256':job['base_sha256'],'architecture':model.config.architectures,'dataset':job['dataset'],
         'trainable_parameters':sum(p.numel() for p in model.parameters() if p.requires_grad),'history':history,
         'training':'Adapters only; original model unchanged','peft_compatible_format':False,
         'sequence_policy':'Right-truncate prompt to max_length-2, response to remaining space; response-only supervised loss',
         'precision':str(dtype),'gradient_accumulation':cfg['gradient_accumulation']})
    return output


def run(job_id):
    import torch
    torch.set_num_threads(2);torch.manual_seed(42)
    job=jobs.get(job_id);directory=Path(job['directory'])
    heartbeat_stop=threading.Event()
    def heartbeat():
        while not heartbeat_stop.wait(5):
            try:
                jobs.update(job_id,heartbeat_at=now(),peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                            gpu_memory_allocated_bytes=torch.cuda.memory_allocated() if torch.cuda.is_available() else 0)
            except Exception:pass
    monitor=threading.Thread(target=heartbeat,daemon=True);monitor.start()
    def stopping(*_):
        write(directory/'stop',{'at':now(),'reason':'Owned worker received termination request'})
    signal.signal(signal.SIGTERM,stopping);signal.signal(signal.SIGINT,stopping)
    try:
        if sha(directory/'input.json')!=job['input_sha256']:raise ValueError('Frozen job input changed')
        if sha(job['base_checkpoint'])!=job['base_sha256']:raise ValueError('Original checkpoint changed since admission')
        job=jobs.update(job_id,state='training',stage='loading',started_at=now(),worker_pid=os.getpid())
        device=torch.device('cpu')
        if job['assigned_device']!='cpu':
            if not torch.cuda.is_available():raise ValueError('Assigned GPU unavailable; no silent CPU fallback for training')
            device=torch.device('cuda:0')
            actual_uuid=str(getattr(torch.cuda.get_device_properties(device),'uuid',''))
            if actual_uuid.lower()!=job['assigned_device'].lower():raise ValueError('Worker CUDA UUID differs from its assigned device')
            torch.cuda.set_per_process_memory_fraction(job['config']['memory_fraction'],device)
            torch.cuda.reset_peak_memory_stats(device)
            jobs.update(job_id,actual_cuda_uuid=actual_uuid,actual_cuda_name=torch.cuda.get_device_name(device),
                        actual_compute_capability=list(torch.cuda.get_device_capability(device)))
        output=(slm if job['model']=='coding-slm' else classifier)(job,read(directory/'input.json'),device)
        registry.checkpoint_manifest(output.parent)
        jobs.update(job_id,state='completed',stage='completed',checkpoint=str(output),finished_at=now(),
                    peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                    peak_gpu_memory_bytes=torch.cuda.max_memory_allocated() if device.type=='cuda' else 0,
                    completion_reason='step_limit_or_epochs' if job['model']=='coding-slm' else 'epochs_or_validation_early_stopping')
        print(json.dumps({'state':'completed','checkpoint':str(output)}),flush=True)
    except Paused:
        jobs.update(job_id,state='paused',stage='checkpointed_stop',finished_at=now());print('Paused after durable checkpoint',flush=True)
    except Exception as e:
        jobs.update(job_id,state='failed',stage='failed',error=redacted(e),finished_at=now());print('ERROR: '+redacted(e),flush=True)
    finally:
        heartbeat_stop.set();monitor.join(timeout=1)
        if torch.cuda.is_available():torch.cuda.empty_cache()


if __name__=='__main__':run(sys.argv[1])
