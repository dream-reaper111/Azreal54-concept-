"""Non-commercial simulation-only SynCAN classifiers; no CAN device access."""
import argparse
import copy
import csv
import hashlib
import io
import json
from pathlib import Path
from collections import deque
import zipfile
import numpy as np
import torch
from torch import nn
from sklearn.metrics import classification_report
from public_training import datafile,groupsplit,tabular_network
from model import ROOT
import storage_paths

OUT=storage_paths.training_root(ROOT,'models-automotive')
NAMES=[f'id_fraction_{i}' for i in range(1,11)]+['gap_mean','gap_std','gap_max','window_duration']+[f'signal_mean_{i}' for i in range(1,5)]+[f'signal_std_{i}' for i in range(1,5)]
LIMIT='SynCAN ETAS/Bosch non-commercial simulation-only model. Not licensed or validated for field/vehicle use. No CAN interface, injection, ECU control or transmission.'
ROLES={'automotive_red':'Automotive red · locate anomalous synthetic traffic windows','automotive_blue':'Automotive blue · independent synthetic CAN-window intrusion review'}


def dataset():
    path=datafile('syncan-flooding.zip');vectors=[];labels=[];groups=[];window=[];source_rows=0
    with zipfile.ZipFile(path) as z:
        info=z.getinfo('test_flooding.csv')
        if info.file_size>150_000_000:raise ValueError('CAN dataset exceeds 150 MB expansion bound')
        with z.open(info) as raw:
            for row in csv.DictReader(io.TextIOWrapper(raw,encoding='utf-8')):
                source_rows+=1
                if source_rows>3000000:raise ValueError('CAN source row bound exceeded')
                signal=[float(row[f'Signal{i}_of_ID']) if row.get(f'Signal{i}_of_ID') not in {None,''} else np.nan for i in range(1,5)]
                window.append((int(row['ID'][2:]),float(row['Time']),signal,int(row['Label'])))
                if len(window)<64:continue
                ids=np.array([w[0] for w in window]);times=np.array([w[1] for w in window]);gaps=np.diff(times)
                signals=np.array([w[2] for w in window]);valid=np.isfinite(signals)
                means=np.array([signals[valid[:,i],i].mean() if valid[:,i].any() else 0 for i in range(4)])
                stds=np.array([signals[valid[:,i],i].std() if valid[:,i].any() else 0 for i in range(4)])
                vector=[float((ids==i).mean()) for i in range(1,11)]+[float(gaps.mean()),float(gaps.std()),float(gaps.max()),float(times[-1]-times[0])]+means.tolist()+stds.tolist()
                if not all(np.isfinite(vector)):raise ValueError('Nonfinite CAN features')
                vectors.append(vector);labels.append(int(any(w[3] for w in window)));groups.append(int(times[0]//60000))
                window=[]
    return np.array(vectors,dtype='float32'),np.array(labels),groups,source_rows


def train_auto(out=OUT):
    torch.set_num_threads(2);out=Path(out)
    if out.exists():raise ValueError('Choose a fresh model output directory')
    out.mkdir(parents=True)
    checkpoints=storage_paths.checkpoint_root(ROOT,'models-automotive');checkpoints.mkdir(parents=True,exist_ok=True,mode=0o700)
    x,y,groups,source_rows=dataset();tr,va,te=groupsplit(groups)
    if set(y[tr])!={0,1} or set(y[te])!={0,1}:raise ValueError('CAN split lacks normal/attack coverage')
    mean=x[tr].mean(0);std=x[tr].std(0);std[std<1e-6]=1
    x=torch.tensor((x-mean)/std);target=torch.tensor(y)
    counts=np.bincount(y[tr],minlength=2);weights=torch.tensor(np.sqrt(len(tr)/(2*counts)),dtype=torch.float32)
    report={'source_url':'https://github.com/etas/SynCAN','source_file':'test_flooding.zip','source_sha256':hashlib.sha256(datafile('syncan-flooding.zip').read_bytes()).hexdigest(),
            'citation':'Hanselmann, Strauss, Dormann & Ulmer (2020), CANet: An Unsupervised Intrusion Detection System for High Dimensional CAN Bus Data, IEEE Access 8:58194–58205',
            'license_file':'data/syncan-license.txt','limitations':LIMIT,'source_rows_examined':source_rows,'nonoverlapping_windows':len(y),
            'evaluation':'Supervised experimental reuse of the published flooding test set; NOT the upstream unsupervised benchmark protocol. 64-message nonoverlapping windows grouped by one-minute source-time blocks. No independent vehicle/capture or full attack-episode split.', 'models':{}}
    for index,role in enumerate(ROLES):
        torch.manual_seed(229+index);m=tabular_network(len(NAMES),2);opt=torch.optim.AdamW(m.parameters(),lr=.003)
        def metrics(ids):
            m.eval()
            with torch.no_grad():p=m(x[ids]).argmax(1).numpy()
            return classification_report(y[ids],p,labels=[0,1],target_names=['normal_window','attack_window'],output_dict=True,zero_division=0)
        best,state,stale,history=-1,None,0,[]
        for epoch in range(1,31):
            m.train()
            for batch in torch.tensor(tr)[torch.randperm(len(tr))].split(128):
                opt.zero_grad();loss=nn.functional.cross_entropy(m(x[batch]),target[batch],weight=weights);loss.backward();opt.step()
            score=metrics(va)['macro avg']['f1-score'];history.append({'epoch':epoch,'validation_macro_f1':score})
            if score>best+.0001:best,state,stale=score,copy.deepcopy(m.state_dict()),0
            else:stale+=1
            if stale>=5:break
        m.load_state_dict(state);m.eval()
        torch.save({'version':1,'state_dict':m.state_dict(),'labels':['normal_window','attack_window'],'feature_names':NAMES,'mean':mean.tolist(),'std':std.tolist()},checkpoints/f'{role}.pt')
        result=metrics(te)
        report['models'][role]={'metrics':result,'train_rows':len(tr),'validation_rows':len(va),'test_rows':len(te),'history':history,'task':ROLES[role],'limits':LIMIT}
        print(role,'simulation holdout accuracy',round(result['accuracy'],3),flush=True)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    (out/'feature-schema.json').write_text(json.dumps({'features':NAMES,'scope':LIMIT},indent=2)+'\n')
    paths=json.loads((ROOT/'learning-paths.json').read_text())
    for role,task in ROLES.items():paths[role]={'training':task+'; published SynCAN synthetic flooding-window labels','status':'public_synthetic_simulation_only','report':'models-automotive/report.json','missing_coverage':LIMIT+' '+report['evaluation']}
    (ROOT/'learning-paths.json').write_text(json.dumps(paths,indent=2)+'\n')


class AutomotiveModels:
    def __init__(self,bus):
        self.bus=bus;self.models={};self.saved={};self.report=json.loads(storage_paths.training_file(ROOT,'models-automotive','report.json').read_text())
        for role in ROLES:
            s=torch.load(storage_paths.checkpoint_file(ROOT,'models-automotive',f'{role}.pt'),map_location='cpu',weights_only=True);m=tabular_network(len(NAMES),2);m.load_state_dict(s['state_dict']);m.eval();self.models[role]=m;self.saved[role]=s
    def analyze(self,role,text):
        value=json.loads(text)
        if not isinstance(value,dict) or set(value)!=set(NAMES) or any(type(v) not in {float,int} or not np.isfinite(v) for v in value.values()):raise ValueError('Supply all named SynCAN simulation-window features; see models-automotive/feature-schema.json')
        s=self.saved[role];x=(np.array([value[n] for n in NAMES],dtype='float32')-np.array(s['mean']))/np.array(s['std'])
        with torch.no_grad():p=self.models[role](torch.tensor(x,dtype=torch.float32).unsqueeze(0)).softmax(1)[0].numpy()
        result={'input_sha256':hashlib.sha256(text.encode()).hexdigest(),'category':s['labels'][int(p.argmax())],'scores':{label:round(float(score),6) for label,score in zip(s['labels'],p)},'reason':LIMIT}
        self.bus.send('controller',role,'research_request',{'input_sha256':result['input_sha256'],'mode':'noncommercial_simulation_only'})
        self.bus.send(role,'defender','research_assessment',result)
        return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',default=str(OUT));args=parser.parse_args();train_auto(args.out)
