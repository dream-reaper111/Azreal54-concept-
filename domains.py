"""Six independent red/blue research classifiers for web, network and RF data."""
import argparse
import copy
import gzip
import hashlib
import json
import math
from pathlib import Path
import random
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import torch
from torch import nn
from sklearn.metrics import classification_report
from public_training import DATA, datafile, distinct, groupsplit, xml_code, tabular_network
from lab import fit, checkpoint, probabilities
from model import ROOT, network
import storage_paths

OUT=storage_paths.training_root(ROOT,'models-domains')
ROLES={
 'web_red':'Web red · documented flawed-code candidates',
 'web_blue':'Web blue · independent good/flawed-code review',
 'network_red':'Network red · historical labeled attack-category triage',
 'network_blue':'Network blue · historical intrusion/normal classification',
 'rf_red':'RF red · infer source-dataset room from seven RSSI values',
 'rf_blue':'RF blue · independent room estimate and optional claim consistency'}
WEB_LANGUAGES={'PHP','JavaScript','ASP.NET','HTML','JSP'}


def web_rows():
    with zipfile.ZipFile(datafile('cwe.xml.zip')) as z:
        root=ET.fromstring(z.read(z.namelist()[0]))
    rows=[]
    for w in root.findall('.//{*}Weakness'):
        for code in w.findall('.//{*}Demonstrative_Examples//{*}Example_Code'):
            text=xml_code(code);nature=code.get('Nature')
            if code.get('Language') in WEB_LANGUAGES and nature in {'Good','Bad'} and 20<=len(text)<=4096:
                rows.append((text,'documented_flawed_example' if nature=='Bad' else 'documented_good_example','CWE-'+w.attrib['ID']))
    return distinct(rows)


def network_text(values):
    if not isinstance(values,list) or len(values)!=41:
        raise ValueError('Network input requires a JSON array of the 41 KDD source features, without a label')
    fields=[]
    for i,value in enumerate(values):
        if i in {1,2,3}:
            if not isinstance(value,str) or not value or len(value)>40 or not all(c.isalnum() or c in '_-' for c in value):
                raise ValueError('Invalid protocol/service/flag category')
            clean=value
        else:
            if isinstance(value,bool):raise ValueError('Numeric features must be numbers')
            clean=float(value)
            if not math.isfinite(clean) or clean<0 or clean>1e12:raise ValueError('Numeric feature outside supported bounds')
            clean=format(clean,'.8g')
        fields.append(f'f{i:02}={clean}')
    return ' '.join(fields)


def network_rows():
    path=datafile('kdd10.gz')
    actual=hashlib.sha256(path.read_bytes()).hexdigest()
    if actual!='8045aca0d84e70e622d1148d7df782496f6333bf6eb979a1b0837c42a9fd9561':
        raise ValueError('Network benchmark does not match scikit-learn published SHA-256')
    rng=random.Random(191);sample=[];lines=0;expanded=0
    with gzip.open(path,'rt',encoding='ascii') as stream:
        for line in stream:
            lines+=1;expanded+=len(line)
            if lines>500000 or expanded>90_000_000:raise ValueError('Dataset exceeds declared coverage bounds')
            row=line.strip().split(',')
            if len(row)!=42:raise ValueError('Invalid KDD row')
            if len(sample)<20000:sample.append(row)
            else:
                index=rng.randrange(lines)
                if index<len(sample):sample[index]=row
    rows=[(network_text(row[:41]),row[-1].rstrip('.'),hashlib.sha256(','.join(row[:41]).encode()).hexdigest()) for row in sample]
    rows,conflicts=distinct(rows)
    counts={label:sum(r[1]==label for r in rows) for _,label,_ in rows}
    accepted={label for label,count in counts.items() if count>=30}
    return [r for r in rows if r[1] in accepted],{'source_rows_examined':lines,'reservoir_rows':len(sample),'excluded_conflicting_feature_rows':conflicts,'excluded_rare_labels':{label:count for label,count in counts.items() if label not in accepted},'sha256':actual}


def rf_rows():
    with zipfile.ZipFile(datafile('wireless-localization.zip')) as z:
        info=z.getinfo('wifi_localization.txt')
        if info.file_size>2_000_000:raise ValueError('RF dataset exceeds bound')
        lines=z.read(info).decode().splitlines()
    values={}
    for line in lines:
        fields=[int(v) for v in line.split()]
        if len(fields)!=8:raise ValueError('Invalid RF row')
        values.setdefault(tuple(fields[:7]),set()).add(str(fields[7]))
    rows=[(vector,next(iter(labels))) for vector,labels in values.items() if len(labels)==1]
    return rows


def train_rf(role,out,seed):
    rows=rf_rows();labels=sorted({label for _,label in rows})
    x=np.array([v for v,_ in rows],dtype=np.float32);y=np.array([labels.index(label) for _,label in rows])
    tr,va,te=groupsplit([str(v) for v,_ in rows])
    mean=x[tr].mean(0);std=x[tr].std(0);std[std<1e-6]=1
    x=torch.tensor((x-mean)/std);target=torch.tensor(y)
    torch.manual_seed(seed);m=tabular_network(7,len(labels));opt=torch.optim.AdamW(m.parameters(),lr=.003)
    best,state,stale,history=-1,None,0,[]
    def metrics(ids):
        m.eval()
        with torch.no_grad():p=m(x[ids]).argmax(1).numpy()
        return classification_report(y[ids],p,labels=list(range(len(labels))),target_names=labels,output_dict=True,zero_division=0)
    for epoch in range(1,51):
        m.train()
        for batch in torch.tensor(tr)[torch.randperm(len(tr))].split(128):
            opt.zero_grad();loss=nn.functional.cross_entropy(m(x[batch]),target[batch]);loss.backward();opt.step()
        score=metrics(va)['macro avg']['f1-score'];history.append({'epoch':epoch,'validation_macro_f1':score})
        if score>best+.0001:best,state,stale=score,copy.deepcopy(m.state_dict()),0
        else:stale+=1
        if stale>=6:break
    m.load_state_dict(state);m.eval()
    target=storage_paths.checkpoint_root(ROOT,'models-domains');target.mkdir(parents=True,exist_ok=True,mode=0o700)
    torch.save({'version':1,'kind':'rssi','labels':labels,'state_dict':m.state_dict(),'mean':mean.tolist(),'std':std.tolist()},target/f'{role}.pt')
    return {'metrics':metrics(te),'train_rows':len(tr),'validation_rows':len(va),'test_rows':len(te),'history':history,
            'task':ROLES[role],'dataset':'UCI Wireless Indoor Localization, Bhatt (2017), CC BY 4.0, DOI 10.24432/C51880',
            'source_url':'https://archive.ics.uci.edu/static/public/422/wireless+indoor+localization.zip',
            'source_sha256':hashlib.sha256(datafile('wireless-localization.zip').read_bytes()).hexdigest(),
            'limits':'Four room labels in one collected environment. Not a modulation classifier, RF attack detector, transmission system, or general location model.'}


def train_domains(out=OUT):
    torch.set_num_threads(2);out=Path(out)
    if out.exists():raise ValueError('Choose a fresh model output directory')
    out.mkdir(parents=True)
    checkpoints=storage_paths.checkpoint_root(ROOT,'models-domains');checkpoints.mkdir(parents=True,exist_ok=True,mode=0o700)
    web,conflicts=web_rows();net,coverage=network_rows()
    report={'models':{},'network_coverage':coverage,'limits':'Independent classifiers with red/blue responsibilities; no attack generation or execution. Historical/small datasets do not establish current operational performance. CPU and peak memory not measured.'}
    for index,role in enumerate(ROLES):
        if role.startswith('rf_'):
            metrics=train_rf(role,out,191+index)
        else:
            rows=web if role.startswith('web_') else net
            if role=='network_blue':rows=[(text,'normal' if label=='normal' else 'attack',group) for text,label,group in rows]
            labels=sorted({label for _,label,_ in rows});texts=[text for text,_,_ in rows];targets=[labels.index(label) for _,label,_ in rows]
            tr,va,te=groupsplit([group for _,_,group in rows])
            m,metrics=fit(texts,targets,tr,va,te,labels,seed=191+index)
            checkpoint(m,labels,checkpoints/f'{role}.pt')
            metrics.update(task=ROLES[role],dataset='MITRE CWE 4.20 demonstrative web-language code examples' if role.startswith('web_') else 'KDD Cup 1999 10% subset; deterministic 20k reservoir followed by deduplication and minimum 30/class',
                source_url='https://cwe.mitre.org/data/xml/cwec_latest.xml.zip' if role.startswith('web_') else 'https://ndownloader.figshare.com/files/5976042',
                source_sha256=hashlib.sha256(datafile('cwe.xml.zip' if role.startswith('web_') else 'kdd10.gz').read_bytes()).hexdigest(),
                limits='CWE-group held-out code examples, web-language filter only; not repository data-flow or verified vulnerability analysis' if role.startswith('web_') else 'Legacy 1999 connection-feature benchmark, random unique-vector holdout; not modern traffic validation or packet capture support')
        report['models'][role]=metrics
        print(f'{role}: public holdout accuracy={metrics["metrics"]["accuracy"]:.3f}, macro F1={metrics["metrics"]["macro avg"]["f1-score"]:.3f}',flush=True)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    paths=json.loads((ROOT/'learning-paths.json').read_text())
    for role,v in report['models'].items():paths[role]={'training':v['task']+'; '+v['dataset'],'status':'public_data_trained','report':'models-domains/report.json','missing_coverage':v['limits']}
    (ROOT/'learning-paths.json').write_text(json.dumps(paths,indent=2)+'\n')
    return report


class DomainModels:
    def __init__(self,bus):
        self.bus=bus;self.models={};self.saved={}
        self.report=json.loads(storage_paths.training_file(ROOT,'models-domains','report.json').read_text())
        for role in ROLES:
            saved=torch.load(storage_paths.checkpoint_file(ROOT,'models-domains',f'{role}.pt'),map_location='cpu',weights_only=True)
            m=tabular_network(7,len(saved['labels'])) if saved.get('kind')=='rssi' else network(len(saved['labels']))
            m.load_state_dict(saved['state_dict']);m.eval();self.saved[role]=saved;self.models[role]=m

    def analyze(self,role,text):
        if role not in self.models or not isinstance(text,str) or not 1<=len(text)<=4096:raise ValueError('Invalid domain input')
        saved=self.saved[role];claimed=None;input_digest=hashlib.sha256(text.encode()).hexdigest()
        if role.startswith('rf_'):
            value=json.loads(text)
            if isinstance(value,dict):claimed=value.get('claimed_room');value=value.get('rssi')
            if not isinstance(value,list) or len(value)!=7 or any(type(v) not in {int,float} or not math.isfinite(v) or not -150<=v<=0 for v in value):raise ValueError('RF input requires seven RSSI values in dBm (-150 to 0)')
            x=(np.array(value,dtype='float32')-np.array(saved['mean']))/np.array(saved['std'])
            with torch.no_grad():p=self.models[role](torch.tensor(x,dtype=torch.float32).unsqueeze(0)).softmax(1)[0].numpy()
        else:
            if role.startswith('network_'):text=network_text(json.loads(text))
            p=probabilities(self.models[role],[text])[0]
        result={'input_sha256':input_digest,'category':saved['labels'][int(p.argmax())],
                'scores':{label:round(float(score),6) for label,score in zip(saved['labels'],p)},'reason':self.report['models'][role]['limits']}
        self.bus.send('controller',role,'research_request',{'input_sha256':result['input_sha256'],'mode':'public_domain_classifier'})
        self.bus.send(role,'defender','research_assessment',result)
        if role=='rf_blue' and claimed is not None:
            result['claimed_room_consistent']=str(claimed)==result['category']
        self.bus.send('defender','controller','defense_review',{'decision':'unverified_candidate','reason':result['reason']})
        return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',default=str(OUT));a=p.parse_args();train_domains(a.out)
