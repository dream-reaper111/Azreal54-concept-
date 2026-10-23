"""Role-specific public search, quarantined reference datasets and scoped operators."""
from datetime import datetime,timezone
import hashlib
import html
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit,quote
from uuid import uuid4
from evidence_store import packed,utc

ROOT=Path(__file__).resolve().parent
DORK_ROLES=frozenset({'web_red','web_blue','bounty_review','cve_triage','zero_day_forge','bastion',
                      'offense_tools','osint_junior','hephaestus','poc_red','poc_blue'})


def profiles():return json.loads((ROOT/'role-search-profiles.json').read_text())['profiles']


def allowed_url(url):
    return any(url==provider['url'] for profile in profiles().values() for provider in profile['providers'])


def _read(path,bound=4_000_000):
    if path.is_symlink():raise ValueError('Reference state cannot be a symlink')
    raw=path.read_bytes()
    if len(raw)>bound:raise ValueError('Reference state exceeds bound')
    return json.loads(raw)


class RoleResearch:
    def __init__(self,store,root):
        self.store,self.root=store,Path(root)
        if self.root.is_symlink():raise ValueError('Role research root cannot be a symlink')
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.lock=threading.Lock()

    def _save(self,path,value):
        temporary=path.with_name(path.name+'.'+uuid4().hex+'.tmp')
        temporary.write_text(packed(value)+'\n');temporary.chmod(0o600);temporary.replace(path)

    def status(self):
        selected=profiles();pointer=self.root/'datasets-current.json'
        datasets=_read(pointer) if pointer.exists() else {'roles':{},'status':'not_created'}
        policy=self.root/'dork-policy.json'
        return {'profiles':selected,'datasets':datasets,'dork_eligible_roles':sorted(DORK_ROLES),
                'dork_assignments':_read(policy) if policy.exists() else {},
                'dork_templates':_read(ROOT/'dork-templates.json'),
                'repository_pitches':_read(ROOT/'repository-pitches.json'),
                'collection_limits':{'requests_per_role':3,'items_per_provider':5,'response_bytes_total':1500000},
                'training_occurred':False,'reference_assignment_is_ground_truth':False}

    def context(self,role):
        if role not in profiles():raise ValueError('Unknown research role')
        path=self.root/('last-search-'+role+'.json')
        report=_read(path) if path.exists() else None
        records=[]
        for item in (report or {}).get('items',[]):
            if not item.get('evidence'):continue
            reference=item['reference']
            records.append({'source_url':item['source_url'],'title':reference.get('title') or reference.get('name'),
              'excerpt':(reference.get('body_excerpt') or reference.get('description') or '')[:240],
              'status':item['evidence']['status'],'retrieved_at':report['retrieved_at']})
        dork_policy=self.status()['dork_assignments'].get(role)
        dork_context={'enabled':False,'reason':'No exact scope has been assigned by the admin.','outbound_requests':0}
        if role in DORK_ROLES and dork_policy and dork_policy.get('enabled') is True:
            rendered=self.dorks(role)
            dork_context={'enabled':True,'scope_type':dork_policy['scope_type'],'scope':dork_policy['scope'],
                'templates':[{'title':item['title'],'query':item['query'],'source':item['source'],
                              'search_url':item['search_url']} for item in rendered['templates']],
                'execution':'Manual search links only; this context does not fetch results or follow links.',
                'outbound_requests':0}
        return {'topic':profiles()[role]['topic'],'stored_role_references':records[:2],
                'use':'Untrusted reference records; query assignment is not a training label.',
                'scoped_dork_search':dork_context}

    def _normalize(self,provider,item):
        kind=provider['provider']
        if not isinstance(item,dict):raise ValueError('Invalid search record')
        if kind=='github':
            name=item.get('full_name','')
            if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}',name):raise ValueError('Invalid repository identity')
            source='https://github.com/'+name
            if item.get('html_url')!=source:raise ValueError('Repository source identity mismatch')
            license=item.get('license') or {}
            return source,{'kind':'tool_proposal','name':name,'description':str(item.get('description') or '')[:700],
              'updated_at':item.get('updated_at'),'archived':item.get('archived'),'fork':item.get('fork'),
              'declared_spdx':license.get('spdx_id'),'stars':item.get('stargazers_count'),
              'pitch':'Candidate matched the role query. Inspect maintenance, license, dependencies and lab suitability before approval. No code was fetched or installed.'},item.get('created_at')
        identifier=item.get('question_id')
        if type(identifier) is not int or identifier<=0:raise ValueError('Invalid discussion identity')
        host='stackoverflow.com' if kind=='stackoverflow' else 'security.stackexchange.com'
        source=f'https://{host}/questions/{identifier}'
        link=item.get('link','')
        parsed=urlsplit(link)
        if parsed.scheme!='https' or parsed.hostname!=host or not parsed.path.startswith('/questions/'+str(identifier)+'/'):
            raise ValueError('Discussion source identity mismatch')
        from bs4 import BeautifulSoup
        excerpt=BeautifulSoup(str(item.get('body') or ''),'html.parser').get_text(' ',strip=True)
        owner=item.get('owner') or {}
        author_link=owner.get('link')
        if author_link and (not isinstance(author_link,str) or urlsplit(author_link).hostname!=host):author_link=None
        created=item.get('creation_date')
        published=datetime.fromtimestamp(created,timezone.utc).isoformat() if type(created) is int else None
        return source,{'kind':'community_discussion','title':html.unescape(str(item.get('title') or ''))[:400],
           'body_excerpt':excerpt[:1200],'body_truncated':len(excerpt)>1200,'tags':[str(t)[:50] for t in item.get('tags',[])[:10]],
           'declared_license':item.get('content_license'),'attribution':{'name':str(owner.get('display_name') or '')[:150],'url':author_link},
           'answer_count':item.get('answer_count'),'score':item.get('score'),
           'limitation':'Community claims are unverified; an accepted answer or score is not ground truth.'},published

    def collect(self,role,fetch=None):
        selected=profiles()
        if role not in selected:raise ValueError('Unknown role search profile')
        if fetch is None:
            from source_transport import fetch
        backoff_path=self.root/'provider-backoff.json'
        backoff=_read(backoff_path) if backoff_path.exists() else {}
        report={'role':role,'retrieved_at':utc(),'requests':[],'items':[],'training_occurred':False,'admission':'quarantine'}
        for provider in selected[role]['providers']:
            family='github' if provider['provider']=='github' else 'stackexchange'
            if time.time()<backoff.get(family,0):
                report['requests'].append({'provider':provider['provider'],'status':'backoff','retry_after_unix':backoff[family]});continue
            try:
                raw=fetch(provider['url'],500000)
                if not isinstance(raw,bytes) or len(raw)>500000:raise ValueError('Search response exceeds bound')
                response=json.loads(raw)
                if not isinstance(response,dict) or not isinstance(response.get('items'),list) or len(response['items'])>5:raise ValueError('Invalid bounded search response')
                if response.get('error_id'):raise ValueError('Provider rejected the query')
                delay=response.get('backoff',0)
                if type(delay) is int and delay>0:backoff[family]=time.time()+min(delay,86400)
                digest=hashlib.sha256(raw).hexdigest()
                report['requests'].append({'provider':provider['provider'],'url':provider['url'],'query':provider['query'],
                     'status':'retrieved','sha256':digest,'bytes':len(raw),'quota_remaining':response.get('quota_remaining'),
                     'incomplete_results':response.get('incomplete_results'),'has_more':response.get('has_more')})
                for item in response['items']:
                    try:
                        source,normalized,published=self._normalize(provider,item)
                        normalized['query_role_assignment']=role
                        evidence=self.store.ingest({'source_url':source,'source_item_id':source,'retrieved_at':utc(),
                          'publication_at':published,'content_sha256':hashlib.sha256(packed(item).encode()).hexdigest(),
                          'normalized':normalized,'task_routes':[role],'worker':'role_search',
                          'method':'Explicit role query to fixed public API; result links never followed',
                          'license':{'status':'unknown','declaration':normalized.get('declared_license') or normalized.get('declared_spdx')},
                          'synthetic_status':'unknown','privacy_review':'pending',
                          'provenance':{'query_url':provider['url'],'response_sha256':digest,'primary_source':provider['provider']=='github',
                            'hash_basis':'canonical original API item; original response hash recorded separately',
                            'raw_retained':False,'intended_use':'reference_only','role_assignment':'query routing, not a verified training label'}})
                        report['items'].append({'source_url':source,'provider':provider['provider'],'evidence':evidence,'reference':normalized})
                    except (ValueError,TypeError,AttributeError,OverflowError):
                        report['items'].append({'provider':provider['provider'],'status':'rejected_invalid_record'})
            except Exception as error:
                report['requests'].append({'provider':provider['provider'],'status':'failed','error_type':type(error).__name__})
        self._save(backoff_path,backoff)
        self._save(self.root/('last-search-'+role+'.json'),report)
        return report

    def build_datasets(self):
        import knowledge
        identifier=uuid4().hex;directory=self.root/'datasets'/identifier
        directory.mkdir(parents=True,mode=0o700)
        summary={'snapshot':identifier,'created_at':utc(),'roles':{},'training_occurred':False,
                 'kind':'role_specific_reference_corpora','training_eligible':False,
                 'limitation':'Query-assigned source documents are research corpora, not independently labeled reproduction or mitigation observations.'}
        for role,profile in profiles().items():
            records=[];seen=set()
            for item in knowledge.lookup(profile['local_query'],12)['results']:
                key=(item['url'],item['sha256'],item['name'])
                if key in seen:continue
                seen.add(key)
                records.append({'role':role,'lane':profile['lane'],'source_url':item['url'],'retrieval_kind':'stored_documentation_snapshot',
                  'source_sha256':item['sha256'],'source_snapshot_at':item['snapshot_at'],'title':item['name'],
                  'text_excerpt':item['excerpt'],'relevance_score':item['score'],'routing_method':'TF-IDF relevance to authored role query; not a verified class label',
                  'license_status':'unknown','admission':'quarantine','training_eligible':False})
            path=self.root/('last-search-'+role+'.json')
            if path.exists():
                for item in _read(path).get('items',[]):
                    if item.get('evidence'):
                        records.append({'role':role,'lane':profile['lane'],**item,'training_eligible':False})
            lane=directory/profile['lane'];lane.mkdir(exist_ok=True,mode=0o700)
            target=lane/(role+'.jsonl')
            raw=(''.join(packed(record)+'\n' for record in records)).encode()
            target.write_bytes(raw);target.chmod(0o600)
            summary['roles'][role]={'lane':profile['lane'],'records':len(records),'file':str(target.relative_to(self.root)),
                                   'sha256':hashlib.sha256(raw).hexdigest()}
        self._save(directory/'manifest.json',summary);self._save(self.root/'datasets-current.json',summary)
        return summary

    def dork_access(self,data):
        if not isinstance(data,dict) or set(data)!={'role','enabled','scope_type','scope','confirmed'} or data['confirmed'] is not True or type(data['enabled']) is not bool:
            raise ValueError('Explicit per-role dork assignment and scope confirmation required')
        role=data['role'];kind=data['scope_type'];scope=data['scope']
        if role not in DORK_ROLES:raise ValueError('This role is not eligible for vulnerability/web search operators')
        if kind not in ('domain','repository') or not isinstance(scope,str):raise ValueError('Domain or repository scope required')
        pattern=r'(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}' if kind=='domain' else r'[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}'
        if not re.fullmatch(pattern,scope) or '..' in scope:raise ValueError('Invalid exact domain or owner/repository scope')
        with self.lock:
            path=self.root/'dork-policy.json';policy=_read(path) if path.exists() else {}
            policy[role]={'enabled':data['enabled'],'scope_type':kind,'scope':scope,'assigned_at':utc(),'assigned_by':'authenticated_admin'}
            self._save(path,policy)
        return policy[role]

    def dataset(self,role):
        if role not in profiles():raise ValueError('Unknown role')
        summary=_read(self.root/'datasets-current.json')
        entry=summary['roles'].get(role)
        if not entry or not re.fullmatch(r'datasets/[a-f0-9]{32}/(?:red|blue)/'+re.escape(role)+r'\.jsonl',entry['file']):raise ValueError('Invalid role dataset path')
        path=self.root/entry['file']
        if path.is_symlink() or path.parent.is_symlink() or path.parent.parent.is_symlink():raise ValueError('Dataset path cannot be a symlink')
        raw=path.read_bytes()
        if len(raw)>4_000_000 or hashlib.sha256(raw).hexdigest()!=entry['sha256']:raise ValueError('Role dataset integrity check failed')
        return raw

    def dorks(self,role):
        if role not in DORK_ROLES:raise ValueError('Role has no dork entitlement')
        policy=self.status()['dork_assignments'].get(role)
        if not policy or not policy['enabled']:raise ValueError('Admin must assign an exact scope before this role can use dorks')
        templates=_read(ROOT/'dork-templates.json')
        result=[]
        for template in templates['templates']:
            if template['scope_type']!=policy['scope_type']:continue
            query=template['query'].format(scope=policy['scope'])
            base='https://github.com/search?type=code&q=' if policy['scope_type']=='repository' else 'https://www.google.com/search?q='
            result.append({**template,'query':query,'search_url':base+quote(query,safe='')})
        return {'role':role,'scope':policy,'templates':result,'execution':'none','outbound_requests':0}
