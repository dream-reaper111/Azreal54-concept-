"""Terminal training and candidate management; no production model replacement."""
import argparse
import json
from pathlib import Path
import sys
import time

from . import datasets,jobs,registry,resources,tui
from .store import read,redacted


def parser():
    p=argparse.ArgumentParser(prog='aztrealcli',description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    models=sub.add_parser('models',help='Discover original models and selected candidates').add_subparsers(dest='action',required=True)
    models.add_parser('list',help='List model paths and training eligibility')
    models.add_parser('inspect',help='Inspect a registered model').add_argument('--model',default='coding-slm')
    ds=sub.add_parser('datasets',help='Local versioned datasets and reviewed admission').add_subparsers(dest='action',required=True)
    ds.add_parser('list',help='List imported dataset versions')
    d=ds.add_parser('validate',help='Validate UTF-8/schema/duplicates/sensitive content; does not admit');d.add_argument('--input',required=True);d.add_argument('--kind',choices=['auto','slm','classifier'],default='auto')
    d=ds.add_parser('import',help='Import local data; --approve records explicit operator admission')
    d.add_argument('--input',required=True);d.add_argument('--kind',choices=['auto','slm','classifier'],default='auto')
    d.add_argument('--source',required=True);d.add_argument('--license',required=True);d.add_argument('--synthetic',choices=['yes','no','model-generated'],required=True)
    d.add_argument('--approve',action='store_true');d.add_argument('--reviewer')
    for name in ['inspect','split']:
        d=ds.add_parser(name,help='Inspect version integrity' if name=='inspect' else 'Freeze stratified disjoint train/validation/test IDs')
        d.add_argument('--dataset',required=True)
        if name=='split':d.add_argument('--seed',type=int,default=42)
    gpu=sub.add_parser('gpu',help='Measured NVIDIA telemetry and framework compatibility').add_subparsers(dest='action',required=True)
    gpu.add_parser('list',help='List UUIDs and current VRAM/utilization')
    g=gpu.add_parser('monitor',help='Refresh measured telemetry; Ctrl-C exits');g.add_argument('--interval',type=float,default=2);g.add_argument('--samples',type=int,default=1)
    t=sub.add_parser('training',help='Interactive manager or explicit managed training actions')
    t.add_argument('--once',action='store_true',help='Render one interactive frame or noninteractive snapshot')
    train=t.add_subparsers(dest='action')
    for name in ['preflight','start']:
        q=train.add_parser(name,help='Check actual prerequisites' if name=='preflight' else 'Start isolated candidate training after preflight/admission')
        q.add_argument('--model',required=True);q.add_argument('--recipe',choices=['classifier','lora','qlora'])
        q.add_argument('--backend',choices=['local','podman','docker','kubernetes'],default='podman')
        q.add_argument('--device',default='cpu',help='cpu, auto, or stable GPU UUID; auto prefers eligible RTX 3080')
        q.add_argument('--image',help='Existing isolated training OCI image for Podman/Docker')
        q.add_argument('--epochs',type=int,default=2);q.add_argument('--max-steps',type=int,default=100,help='LoRA optimizer-step bound')
        q.add_argument('--batch-size',type=int,default=1);q.add_argument('--gradient-accumulation',type=int,help='LoRA microbatches per optimizer step (default 4)')
        q.add_argument('--max-length',type=int,default=128);q.add_argument('--rank',type=int,default=4);q.add_argument('--patience',type=int,default=3,help='Classifier early-stopping patience')
        q.add_argument('--learning-rate',type=float);q.add_argument('--memory-fraction',type=float,default=.75)
        q.add_argument('--confirm-resource-intensive',action='store_true',help='Explicit operator authorization for >3 epochs or >200 LoRA steps')
        if name=='start':q.add_argument('--dataset',required=True);q.add_argument('--wait',action='store_true')
    for name in ['status','logs','stop','resume','evaluate','checkpoints','promote']:
        q=train.add_parser(name,help={'status':'List durable job states','logs':'Show owned job logs','stop':'Request cooperative checkpointed stop',
             'resume':'Resume validated optimizer/adapter checkpoint','evaluate':'Independent held-out candidate evaluation',
             'checkpoints':'List candidate checkpoints and integrity','promote':'Confirm candidate registry selection; does not deploy'}[name])
        q.add_argument('--job',required=name in {'stop','resume','evaluate','promote'})
        if name=='logs':q.add_argument('--lines',type=int,default=50)
        if name in {'resume','stop'}:q.add_argument('--wait',action='store_true')
        if name=='resume':
            q.add_argument('--epochs',type=int);q.add_argument('--max-steps',type=int)
            q.add_argument('--confirm-resource-intensive',action='store_true',help='Authorize a resumed run above the bounded default limits')
        if name=='evaluate':q.add_argument('--code-tests',action='store_true',help='Also generate bounded baseline/candidate answers and score restricted AST fixtures')
        if name=='promote':q.add_argument('--confirm',required=True,help='Exact model ID acknowledging registry selection')
    q=train.add_parser('rollback',help='Restore previous candidate selection; never overwrite production weights')
    q.add_argument('--model',required=True);q.add_argument('--confirm',required=True)
    return p


def main(argv=None):
    args=parser().parse_args(argv)
    try:
        result=dispatch(args)
        if result is not None:print(json.dumps(result,indent=2,allow_nan=False))
        if args.command=='datasets' and args.action=='validate' and not result['valid']:return 2
        if args.command=='training' and args.action=='preflight' and not result['eligible']:return 2
        if args.command=='training' and args.action in {'start','resume'} and isinstance(result,dict) and result.get('state')=='failed':return 1
        return 0
    except KeyboardInterrupt:
        print('Interrupted; owned background training continues unless training stop is requested.',file=sys.stderr);return 130
    except (ValueError,OSError,KeyError,TypeError,RuntimeError,ImportError) as e:
        print(json.dumps({'error':redacted(e)}),file=sys.stderr);return 2


def dispatch(a):
    if a.command=='models':return registry.models() if a.action=='list' else registry.model_info(a.model)
    if a.command=='datasets':
        if a.action=='list':return datasets.list_datasets()
        if a.action=='validate':return datasets.validate(a.input,a.kind)[0]
        if a.action=='import':return datasets.import_data(a.input,a.kind,a.source,a.license,a.synthetic,a.approve,a.reviewer)
        if a.action=='inspect':return datasets.inspect(a.dataset)
        return datasets.split(a.dataset,a.seed)
    if a.command=='gpu':
        if a.action=='list':return {'telemetry':resources.gpus(),'framework':resources.framework()}
        if not .2<=a.interval<=60 or not 1<=a.samples<=100000:raise ValueError('Interval must be 0.2–60 seconds and samples 1–100000')
        for index in range(a.samples):
            print(json.dumps(resources.gpus()),flush=True)
            if index+1<a.samples:time.sleep(a.interval)
        return None
    if not a.action:return tui.launch(a.once)
    if a.action in {'preflight','start'}:
        config={k:v for k,v in vars(a).items() if k not in {'command','action','once','dataset','wait'} and v is not None}
        config=jobs.checked_config(config)
        if a.action=='preflight':return resources.preflight(config)
        result=jobs.start(config,a.dataset)
        return jobs.wait(result['id']) if a.wait else result
    if a.action=='status':return jobs.get(a.job) if a.job else jobs.list_jobs()
    if a.action=='checkpoints':
        rows=[jobs.get(a.job)] if a.job else jobs.list_jobs();out=[]
        for j in rows:
            if not j.get('checkpoint') and not j.get('resume_checkpoint'):continue
            try:integrity=registry.verify(Path(j['directory'])/'checkpoints');error=None
            except ValueError as e:integrity=None;error=str(e)
            out.append({'job':j['id'],'model':j['model'],'state':j['state'],'checkpoint':j['checkpoint'],
                        'resume_checkpoint':j['resume_checkpoint'],'integrity':integrity,'error':error})
        return out
    if a.action=='logs':
        job=jobs.get(a.job) if a.job else (jobs.list_jobs() or [None])[0]
        if not job:raise ValueError('No training jobs')
        if not 1<=a.lines<=10000:raise ValueError('Lines must be 1–10000')
        p=Path(job['directory'])/'logs.txt'
        return {'job':job['id'],'lines':p.read_text(errors='replace').splitlines()[-a.lines:] if p.exists() else []}
    if a.action=='stop':
        result=jobs.stop(a.job);return jobs.wait(a.job) if a.wait else result
    if a.action=='resume':
        result=jobs.resume(a.job,a.epochs,a.max_steps,a.confirm_resource_intensive);return jobs.wait(a.job) if a.wait else result
    if a.action=='evaluate':
        from .evaluation import evaluate
        return evaluate(a.job,a.code_tests)
    if a.action=='promote':return registry.promote(a.job,a.confirm)
    return registry.rollback(a.model,a.confirm)
