"""Independent held-out evaluation. Generated code never executes arbitrary Python."""
import os
from pathlib import Path

from .store import read,write,sha,now,locked,redacted
from . import jobs,registry


def evaluate(job_id,code_tests=False):
    import torch
    torch.set_num_threads(2)
    with locked():
        job=jobs.get(job_id)
        if job['state']!='completed':raise ValueError('Evaluation requires a completed candidate')
        for other in jobs.list_jobs():
            if other['id']!=job_id and other['state'] in jobs.ACTIVE and other['assigned_device']==job['assigned_device']:
                raise ValueError('Compute device is reserved by another managed job')
        directory=Path(job['directory']);registry.verify(directory/'checkpoints')
        if sha(directory/'input.json')!=job['input_sha256']:raise ValueError('Frozen job inputs changed')
        if sha(job['base_checkpoint'])!=job['base_sha256']:raise ValueError('Original checkpoint changed')
        inputs=read(directory/'input.json')
        job.update(state='evaluating',stage='heldout_evaluation',driver_pid=os.getpid(),driver_start=jobs.process_start(os.getpid()),driver_namespace=jobs.process_namespace())
        write(directory/'job.json',job)
    try:
        if job['model']!='coding-slm':
            import model
            import numpy as np
            from sklearn.metrics import accuracy_score,classification_report,confusion_matrix
            task='secret' if job['model']=='secret-classifier' else 'exploit'
            net,labels=model.load(task,directory/'checkpoints');rows=inputs['parts']['test']
            values=model.predict(net,labels,[r['text'] for r in rows])
            truth=[r['label'] for r in rows];predictions=[max(r,key=r.get) for r in values]
            if set(truth)-set(labels):raise ValueError('Held-out labels do not match candidate')
            cm=confusion_matrix(truth,predictions,labels=labels);total=int(cm.sum());rates={}
            for i,label in enumerate(labels):
                tp=int(cm[i,i]);fn=int(cm[i,:].sum())-tp;fp=int(cm[:,i].sum())-tp;tn=total-tp-fn-fp
                rates[label]={'false_positive_rate':fp/(fp+tn) if fp+tn else None,'false_negative_rate':fn/(fn+tp) if fn+tp else None}
            report={'dataset_split':'test','examples':len(rows),'accuracy':float(accuracy_score(truth,predictions)),
                'classification_report':classification_report(truth,predictions,labels=labels,output_dict=True,zero_division=0),
                'labels':labels,'confusion_matrix':cm.tolist(),'rates':rates,'synthetic_status':inputs['manifest']['synthetic']}
        else:
            from .worker import load_slm
            from . import lora
            if job['assigned_device']!='cpu':
                os.environ['CUDA_VISIBLE_DEVICES']=job['assigned_device']
                if not torch.cuda.is_available():raise ValueError('Assigned CUDA device unavailable for evaluation')
            device=torch.device('cpu' if job['assigned_device']=='cpu' else 'cuda:0')
            net,tokenizer,_,_=load_slm(job,device);net.eval()
            state=torch.load(job['checkpoint'],map_location='cpu',weights_only=True);lora.load_adapter(net,state)
            rows=inputs['parts']['test'];length=job['config']['max_length']
            candidate_loss=lora.heldout_loss(net,tokenizer,rows,length,device)
            assessment=lora.generated_assessment(net,tokenizer,device) if code_tests else None
            lora.set_adapters(net,False)
            baseline_loss=lora.heldout_loss(net,tokenizer,rows,length,device)
            baseline_assessment=lora.generated_assessment(net,tokenizer,device) if code_tests else None
            report={'dataset_split':'test','examples':len(rows),'validation_loss':candidate_loss,'heldout_test_loss':candidate_loss,
                 'pretrained_baseline_loss':baseline_loss,'loss_delta':candidate_loss-baseline_loss,
                 'candidate_code_assessment':assessment,'baseline_code_assessment':baseline_assessment,
                 'code_tests_status':'executed' if code_tests else 'NOT TESTED; enable --code-tests',
                 'synthetic_status':inputs['manifest']['synthetic'],'generated_code_executed':False}
        report.update(at=now(),job=job_id,dataset_hash=job['dataset_hash'],checkpoint=job['checkpoint'],
                      approval_status='candidate evaluation only; human selection still required')
        write(directory/'evaluation.json',report)
        jobs.update(job_id,state='completed',stage='evaluated',evaluation=report,driver_pid=None,driver_start=None)
        return report
    except Exception as error:
        jobs.update(job_id,state='completed',stage='evaluation_failed',evaluation=None,evaluation_error=redacted(error),driver_pid=None,driver_start=None)
        raise
