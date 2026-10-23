"""Malware literature retrieval and abstract, in-memory propagation simulation."""
from functools import lru_cache
import hashlib
import json
import random
from sklearn.feature_extraction.text import TfidfVectorizer
from model import ROOT
import storage_paths


def spread(bus, steps=5, seed=901):
    if type(steps) is not int or not 1 <= steps <= 20 or type(seed) is not int or not 0 <= seed <= 1000000:
        raise ValueError('Invalid simulation bounds')
    rng = random.Random(seed)
    n = 40
    graph = [(a,b) for a in range(n) for b in range(a+1,n) if rng.random()<.07]
    # Abstract nodes are integers; no addresses, network interfaces, files, or executable payloads.
    infections = {0}; quarantined = set(); timeline=[]
    bus.send('offense_test','defender','challenge',{'mode':'abstract_in_memory_spread','nodes':n,'steps':steps})
    for step in range(steps):
        next_infections=set(infections)
        for a,b in graph:
            if a in quarantined or b in quarantined:
                continue
            if (a in infections) != (b in infections) and rng.random()<.35:
                next_infections.update({a,b})
        infections=next_infections
        for node in sorted(infections-quarantined):
            if rng.random()<.3:
                quarantined.add(node)
        timeline.append({'step':step+1,'ever_infected':len(infections),'contained':len(quarantined)})
        bus.send('defender','offense_test','defense_review',{'mode':'abstract_containment','steps':step+1,'infected':len(infections),'contained':len(quarantined)})
    return {'nodes':n,'timeline':timeline,'limits':'Educational stochastic graph simulation, not a neural prediction or malware implementation. No code replication, networking, filesystem writes, or processes.'}


@lru_cache(maxsize=1)
def malware_index():
    path=storage_paths.data_path(ROOT,'attack-20.0.json')
    source=path.read_bytes()
    docs=[o for o in json.loads(source)['objects'] if o['type']=='malware' and o.get('description') and not o.get('revoked') and not o.get('x_mitre_deprecated')]
    vectorizer=TfidfVectorizer(max_features=40000,ngram_range=(1,2))
    matrix=vectorizer.fit_transform([o.get('name','')+' '+o['description'] for o in docs])
    return docs,vectorizer,matrix,hashlib.sha256(source).hexdigest()


def literature(bus,query):
    if not isinstance(query,str) or not 1<=len(query)<=500:
        raise ValueError('Query must have 1–500 characters')
    docs,v,m,sha=malware_index()
    scores=(m@v.transform([query]).T).toarray().ravel()
    rows=[]
    for i in scores.argsort()[::-1][:5]:
        if scores[i]<=0:
            continue
        doc=docs[i]
        refs=[r.get('url') for r in doc.get('external_references',[]) if r.get('source_name')=='mitre-attack']
        rows.append({'name':doc['name'],'url':refs[0] if refs else 'https://attack.mitre.org/',
                     'description_excerpt':doc['description'][:500],'score':round(float(scores[i]),4)})
    bus.send('offense_test','malware_behavior','research_request',{'query_sha256':hashlib.sha256(query.encode()).hexdigest(),'mode':'public_malware_literature'})
    bus.send('malware_behavior','defender','research_assessment',{'records':[{'name':r['name'],'url':r['url']} for r in rows],
             'reason':'MITRE ATT&CK reference retrieval; no generation or execution'})
    bus.send('defender','controller','defense_review',{'decision':'reference_material_only','reason':'Public malware descriptions, not validated new findings or executable instructions'})
    return {'records':rows,'source_sha256':sha,'method':'Local TF-IDF retrieval from public ATT&CK malware objects; not training or code generation'}
