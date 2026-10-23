"""Authenticated local control panel for classifier benchmarks and registered research roles."""
import argparse
import copy
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
from pathlib import Path
import secrets
import subprocess
import threading
import time
from urllib.parse import urlsplit, parse_qs

from lab import Team, ACTORS, digest
from research import ResearchWorkspace
from public_training import PublicModels
from domains import DomainModels, ROLES as DOMAIN_ROLES
from automotive import AutomotiveModels, ROLES as AUTO_ROLES
from simulation import spread, literature
import slm
import ops_api
import permissions
import artifacts
import runtime_tools
import readiness
import live_data
import collection
import exploit_references
from evidence_store import EvidenceStore
import external_runtime
import tempfile
import hak5_catalog
import storage_paths
from council import Council
import hierarchy
import branding
from poc_training import PocTraining
from installation import Installation
from role_research import RoleResearch
from directives import Directives
from training_coordinator import TrainingCoordinator
from ctf_lab import CtfLab
from idle_trainer import IdleTrainer
from roster import ROLES as ADDITIONAL_ROLES, CONTRACTS as ROLE_CONTRACTS, SHARED_MODES
from recipes import RECIPES
from model import ROOT

WEB = ROOT / 'web'
OPERATIONS = set(permissions.OPERATIONS)
ROLES = [
 ('analyst', 'Analyst', 'Original secret and exploit classifiers; evidence baseline', 'baseline'),
 ('defender', 'Defender', 'Detection, independent critique and synthetic adversarial checks', 'defense'),
 ('offense_test', 'Adversarial tests', 'Neural selection of synthetic test representations', 'research'),
 ('offense_tools', 'Tool research', 'Neural category prediction; Kali, Parrot and BlackArch reference search', 'research'),
 ('malware_static', 'Malware · static', 'Android permission/API features → public dataset malware label', 'analysis'),
 ('malware_behavior', 'Malware · behavior', 'Technique descriptions → public ATT&CK tactic', 'analysis'),
 ('bounty_review', 'Bounty review', 'CWE code examples → documented flawed/good label', 'analysis'),
 ('cve_triage', 'Crash / CVE triage', 'Known vulnerability text → published CVSS severity', 'analysis')] + [(role, role.replace('_',' ').title(), description, 'research' if role.endswith('_red') else 'defense') for role,description in {**DOMAIN_ROLES,**AUTO_ROLES}.items()]

ROLES += ADDITIONAL_ROLES

def fields(value, allowed, required):
    if not isinstance(value, dict) or set(value) - allowed or not required <= set(value):
        raise ValueError('Invalid command fields')


class App:
    def __init__(self, token=None, test_fixtures=False, evidence_root=None):
        self.test_fixtures=test_fixtures
        self.evidence_temp=tempfile.TemporaryDirectory(prefix="node-evidence-test-") if test_fixtures and evidence_root is None else None
        self.collection_policy=collection.policy()
        retention=storage_paths.evidence_policy()
        self.evidence=EvidenceStore(Path(self.evidence_temp.name) if self.evidence_temp else
                                    (evidence_root or storage_paths.evidence_root(ROOT)),
                                    max_records=retention['max_records'],retention_days=retention['retention_days'])
        self.token = token or secrets.token_urlsafe(32)
        self.session = secrets.token_urlsafe(32)
        self.session_expires_at = time.monotonic() + 3600
        self.team = Team()
        self.research = PublicModels(self.team.bus)
        self.domains = DomainModels(self.team.bus)
        self.automotive = AutomotiveModels(self.team.bus)
        self.workspace=ResearchWorkspace(self.evidence.root)
        shared_root=storage_paths.storage_root() if not self.evidence_temp else self.evidence.root
        self.council=Council(shared_root/'council')
        self.checkpoint_info=hierarchy.checkpoints(self)
        self.poc_training=PocTraining(self.evidence,self.council.root.parent/'poc-candidates')
        ctf_root=(self.evidence.root/'ctf-practice' if self.evidence_temp else
                  storage_paths.training_root(ROOT,'ctf'))
        self.ctf_lab=CtfLab(ctf_root)
        self.installation=Installation(ROOT,shared_root/'setup')
        self.role_research=RoleResearch(self.evidence,shared_root/'role-research')
        self.directives=Directives(self.evidence.root/'directives',ACTORS-{'controller'})
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='lab-command')
        self.busy = False
        self.last_collection_at=None
        self.jobs = deque(maxlen=30)
        self.approvals = deque(maxlen=50)
        self.login_attempts = deque(maxlen=20)
        self.downloads = deque(maxlen=50)
        self.idle_trainer=IdleTrainer(self,self.poc_training)
        self.training_coordinator = TrainingCoordinator(self)

    def snapshot(self):
        with self.lock:
            jobs = copy.deepcopy(list(self.jobs))
            approvals = copy.deepcopy(list(self.approvals))
            downloads = copy.deepcopy(list(self.downloads))
            busy = self.busy
        return {'role_research':self.role_research.status(), 'installation':self.installation.status(), 'research_libraries':self.workspace.libraries(), 'poc_training':self.poc_training.status(), 'brand':branding.public(), 'hierarchy':hierarchy.build(ROLES), 'checkpoints':self.checkpoint_info, 'storage':storage_paths.storage_status(), 'council_reviews':self.council.snapshot(), 'directives':self.directives.snapshot(), 'collection_policy':copy.deepcopy(self.collection_policy), 'evidence_summary':self.evidence.summary(),
                'evidence_records':self.evidence.list_records(20,include_normalized=False),
                'external_runtime_configured':runtime_tools.configured('external-tools'), 'shared_modes':SHARED_MODES, 'role_contracts': ROLE_CONTRACTS, 'roles': [{'id': k, 'name': n, 'description': d, 'group': g, 'collection_policy_version':self.collection_policy['version']} for k,n,d,g in ROLES],
                'slm': {'available': slm.available(), 'backend': 'Qwen2.5-Coder-1.5B-Instruct', 'contexts': sorted(slm.MODES)},
                'busy': busy, 'jobs': jobs, 'messages': self.team.bus.snapshot()[-200:], 'approvals': approvals, 'downloads': downloads, 'curated_tools': artifacts.TOOLS,
                'readiness':readiness.audit(), 'tool_recipes':RECIPES, 'runtime_tools_configured':runtime_tools.configured(),
                'training_coordinator':self.training_coordinator.status(),
                'idle_trainer':self.idle_trainer.status(), 'ctf_lab':self.ctf_lab.status(),
                'learning_paths': json.loads((ROOT / 'learning-paths.json').read_text()),
                'public_metrics': {role: {'accuracy': entry['metrics']['accuracy'], 'macro_f1': entry['metrics']['macro avg']['f1-score'], 'test_rows': entry['test_rows']} for role, entry in {**self.research.report['models'], **self.domains.report['models'], **self.automotive.report['models']}.items()},
                'security': {'bind': '127.0.0.1', 'privileged_execution': False, 'sections': permissions.SECTIONS, 'local_demo_execution': self.test_fixtures, 'tool_execution_requires_approval': True,
                             'container_runtime_verified': False, 'message_transport': 'bounded local in-process bus',
                             'notice': 'Role readiness varies. Public evidence retrieval and exact admin-approved implemented recipes only; container deployment is not yet verified.'}}

    def submit(self, command):
        fields(command, {'action', 'role', 'text', 'rounds', 'seed', 'language'}, {'action'})
        action = command['action']
        if action not in {'exercise', 'tools', 'analyze', 'simulate', 'literature', 'admin_chat', 'team_brief', 'code_draft', 'tool_plan', 'tool_status', 'collect_sources', 'hak5_repos', 'council_review', 'topology', 'train_poc', 'poc_predict', 'spread_model', 'research_inspect', 'role_collect', 'role_datasets', 'role_hive_review', 'online_brief', 'published_exploits', 'live_intel', 'wireless', 'radio', 'purple_team', 'incident_review', 'ctf_practice'}:
            raise ValueError('Unknown action')
        if action=='tool_plan' and not runtime_tools.configured():
            raise ValueError('Start the container lab before proposing executable tool steps')
        if action=='role_collect':
            fields(command,{'action','role'},{'action','role'})
        elif action in {'tool_status','collect_sources','hak5_repos','role_datasets'}:
            fields(command,{'action'},{'action'})
        elif action == 'ctf_practice':
            fields(command, {'action','role','text'}, {'action','text'})
            try:
                request = json.loads(command['text'])
            except (TypeError, json.JSONDecodeError) as error:
                raise ValueError('CTF practice request must be valid JSON') from error
            fields(request, {'challenge_id'}, {'challenge_id'})
            self.ctf_lab.challenge(request['challenge_id'])
        if action in {'exercise','simulate','purple_team'} and not self.test_fixtures:
            raise ValueError('Synthetic workflows are disabled under the real-data requirement')
        if action=='analyze' and not self.test_fixtures:
            readiness.require_classifier(command.get('role'))
        if action in {'tool_status','collect_sources','hak5_repos','role_collect','role_datasets'}:
            pass
        elif action in {'exercise', 'simulate', 'purple_team'}:
            fields(command, {'action', 'rounds', 'seed'}, {'action'})
            rounds, seed = command.get('rounds', 5), command.get('seed', 901)
            if type(rounds) is not int or not 1 <= rounds <= 20 or type(seed) is not int or not 0 <= seed <= 1000000:
                raise ValueError('Rounds 1–20 and seed 0–1000000 required')
        else:
            fields(command, {'action', 'role', 'text', 'language'} if action=='code_draft' else {'action', 'role', 'text'}, {'action', 'text'})
            text = command['text']
            maximum = 24000 if action in {'topology','spread_model','research_inspect'} else 3000 if action in {'council_review','role_hive_review'} else 500 if action in {'published_exploits', 'live_intel', 'tools', 'literature', 'wireless', 'radio', 'incident_review'} else (16384 if command.get('role') == 'malware_static' else 4096)
            if not isinstance(text, str) or not 1 <= len(text) <= maximum:
                raise ValueError(f'Text must have 1–{maximum} characters')
            if action == 'analyze' and command.get('role') not in ACTORS - {'controller', 'offense_test', 'offense_tools'}:
                raise ValueError('Select an analysis role')
        if command.get('role','analyst') not in ACTORS-{'controller'}:raise ValueError('Unknown role')
        if action=='code_draft' and (command.get('language') not in {'Python','C#','Java','C++'} or command.get('role') not in ACTORS-{'controller'}):
            raise ValueError('Choose a supported language and model role')
        with self.lock:
            if self.busy:
                raise RuntimeError('A command is already running')
            if action in {'collect_sources','online_brief','hak5_repos','role_collect','role_hive_review'}:
                if self.last_collection_at is not None and time.monotonic()-self.last_collection_at<60:
                    raise ValueError('Collection runs are limited to one per minute')
                self.last_collection_at=time.monotonic()
            job = {'id': secrets.token_hex(8), 'action': action, 'status': 'running',
                   'started_at': datetime.now(timezone.utc).isoformat()}
            self.jobs.append(job)
            self.busy = True
        self.executor.submit(self._run, job, dict(command))
        return {'job_id': job['id']}

    def _run(self, job, command):
        try:
            completion='completed'
            action = command['action']
            if action=='role_hive_review':
                receipt=self.role_research.collect(command.get('role','analyst'))
                review=self.council.review(self,command['text'],command.get('role','analyst'),research_receipt=receipt)
                result={'research':receipt,'review':review,'training_occurred':False,'changes_applied':False}
                if review['completion']!='complete' or any(row['status']!='retrieved' for row in receipt['requests']):completion='partial'
            elif action=='role_collect':
                result=self.role_research.collect(command['role'])
                if any(item['status']!='retrieved' for item in result['requests']):completion='partial'
            elif action=='role_datasets':
                result=self.role_research.build_datasets()
            elif action=='hak5_repos':
                result=hak5_catalog.refresh(self.evidence.root)
            elif action=='train_poc':
                result=self.idle_trainer.enqueue(json.loads(command['text']))
            elif action=='ctf_practice':
                request=json.loads(command['text'])
                challenge_id=request['challenge_id']
                role=command.get('role','analyst')
                answer=slm.ask(self,'admin_chat',self.ctf_lab.practice_prompt(challenge_id),role)
                result={'challenge_id':challenge_id,'title':self.ctf_lab.challenge(challenge_id)['title'],
                        'model_response':answer,
                        'attempt':self.ctf_lab.attempt(challenge_id,answer.get('text',''),method='model',role=role),
                        'training_occurred':False,'operational_evidence_written':False,
                        'limitation':'One shared local SLM with a role prompt; CTF practice stays outside evidence and training datasets.'}
            elif action=='poc_predict':
                result=self.poc_training.predict(json.loads(command['text']))
            elif action=='research_inspect':
                result=self.workspace.inspect(json.loads(command['text']))
            elif action=='spread_model':
                from research import model_spread
                result=model_spread(json.loads(command['text']))
            elif action=='topology':
                result=self.workspace.analyze_topology(json.loads(command['text']))
            elif action=='council_review':
                result=self.council.review(self,command['text'],command.get('role','analyst'))
                if result['completion']=='partial':completion='partial'
            elif action=='online_brief':
                collected=collection.run(self.evidence.root)
                result={'collection':collected,'shared_slm_plan':None,'training_occurred':False,
                        'testing_permissions_changed':False,
                        'limitation':'One bounded collection followed by one shared local SLM request. Role messages are not independent model inferences.'}
                if collected.get('rejected',0):completion='partial'
                if not collected.get('retrieved'):
                    completion='partial'
                    result['planning_error']={'type':'NoCurrentEvidence',
                        'reason':'No source was retrieved in this run. Planning was skipped; inspect the failed collection receipt.'}
                else:
                    try:
                        result['shared_slm_plan']=slm.ask(self,'team_brief',command['text'],command.get('role','analyst'))
                    except Exception as error:
                        completion='partial'
                        result['planning_error']={'type':type(error).__name__,
                            'reason':'SLM planning did not complete. The collection receipt and staged records are retained.'}
            elif action=='published_exploits':
                result=exploit_references.search(command['text'])
            elif action=='collect_sources':
                result=collection.run(self.evidence.root)
            elif action=='live_intel':
                result=live_data.collect(command['text'],command.get('role','analyst'),self.team.bus)
            elif action=='tool_status':
                result=runtime_tools.broker('/status')
            elif action in {'exercise','purple_team'}:
                result = self.team.exercise(command.get('rounds', 5), command.get('seed', 901))
            elif action == 'simulate':
                result = spread(self.team.bus, command.get('rounds', 5), command.get('seed', 901))
            elif action == 'literature':
                result = literature(self.team.bus, command['text'])
            elif action in slm.MODES:
                result = slm.ask(self, action, command['text'], command.get('role','analyst'), command.get('language','Python'))
                if action=='tool_plan':
                    plan=result['plan']
                    proposals=[]
                    for step in plan['steps']:
                        recipe=RECIPES[step['recipe']]
                        proposals.append(self.approval({'operation':'recipe_'+step['recipe'],'target':recipe['target'],'model':command.get('role','offense_test'),'section':recipe['section']}))
                    result['pending_approvals']=proposals
            elif action in {'tools', 'wireless', 'radio', 'incident_review'}:
                prefix = {'wireless': 'wireless 802.11 analysis ', 'radio': 'software defined radio spectrum analysis ', 'incident_review': 'incident response forensics '}.get(action, '')
                result = self.team.tools((prefix + command['text'])[:500], command.get('role','offense_test'),
                                         reference_root=self.evidence.root.parent)
                result['mode'] = action
                result['execution'] = 'documentation and planning only; no network attacks or RF transmission'
            elif command['role'] in AUTO_ROLES:
                result = self.automotive.analyze(command['role'], command['text'])
            elif command['role'] in DOMAIN_ROLES:
                result = self.domains.analyze(command['role'], command['text'])
            elif command['role'] in self.research.models:
                result = self.research.analyze(command['role'], command['text'])
            else:
                result = self.team.review(command['text'])
            with self.lock:
                job.update(status=completion, result=result)
        except Exception as error:
            with self.lock:
                job.update(status='failed', error=str(error) if isinstance(error,ValueError) else type(error).__name__)
        finally:
            with self.lock:
                job['finished_at'] = datetime.now(timezone.utc).isoformat()
                self.busy = False

    def approval(self, data):
        if data.get('model','offense_test') not in ACTORS-{'controller'}:raise ValueError('Unknown model')
        request = permissions.proposal(data,allow_demo=self.test_fixtures,allow_runtime=runtime_tools.configured('external-tools' if data.get('operation')=='external_http_headers' else 'tools'))
        with self.lock:
            self.approvals.append(request)
        self.team.bus.send(request['model'], 'defender', 'approval_request', request)
        return dict(request)

    def decide(self, data):
        fields(data, {'request_id', 'decision','authorized'}, {'request_id', 'decision'})
        if data['decision'] not in {'approve_plan', 'reject', 'revoke'}:
            raise ValueError('Invalid decision')
        with self.lock:
            request = next((r for r in self.approvals if r['request_id'] == data['request_id']), None)
            if request is None or request['status'] not in {'pending','approved','approved_plan_only'}:
                raise ValueError('Request is missing or already consumed/decided')
            if permissions.expired(request):
                request['status']='expired'
                raise ValueError('Request expired')
            if data['decision']=='approve_plan':
                if request['operation']=='external_http_headers' and data.get('authorized') is not True:
                    raise ValueError('Confirm authorization for this exact external target and method')
                if request['status']!='pending':
                    raise ValueError('Already approved')
                request['status']='approved' if request['executable'] else 'approved_plan_only'
                request['approved_at']=datetime.now(timezone.utc).isoformat()
                request['approved_by']='authenticated_admin'
                request['authorization_confirmed']=data.get('authorized') is True
            else:
                request['status']='rejected' if data['decision']=='reject' else 'revoked'
            result=dict(request)
        self.team.bus.send('controller','defender','approval_decision',{k:v for k,v in result.items() if k not in {'approved_at','approved_by','authorization_confirmed'}})
        return result

    def execute_approval(self, data):
        fields(data, {'request_id','model','section'}, {'request_id','model','section'})
        with self.lock:
            request=next((r for r in self.approvals if r['request_id']==data['request_id']),None)
            if request is None or request['status']!='approved' or request['uses_left']!=1 or not request['executable']:
                raise ValueError('No executable one-use approval')
            if (request['model'],request['section'])!=(data['model'],data['section']):
                raise ValueError('Approval belongs to another model or section')
            if permissions.expired(request):
                request['status']='expired'
                raise ValueError('Approval expired')
            if self.busy:
                raise RuntimeError('A command is running')
            request['status']='executing';request['uses_left']=0;self.busy=True
            snapshot=dict(request)
        try:
            self.team.bus.send(snapshot['model'],'defender','approved_test',{k:v for k,v in snapshot.items() if k not in {'approved_at','approved_by','authorization_confirmed'}})
            result=external_runtime.execute(snapshot) if snapshot['operation']=='external_http_headers' else runtime_tools.execute(snapshot) if snapshot['operation'].startswith('recipe_') else permissions.demo(snapshot)
            self.team.bus.send('defender','controller','defense_review',{'decision':'tool_run_completed' if snapshot['operation']!='demo_sql_injection' else 'local_fixture_completed','reason':result.get('observed','Real tool run retained with exit status, timing and evidence hash')})
            with self.lock:
                request['status']='consumed'
                self.jobs.append({'id':snapshot['request_id'],'action':'admin_approved_tool' if snapshot['operation']!='demo_sql_injection' else 'admin_approved_demo','status':'completed','result':result})
            return result
        except Exception:
            with self.lock:
                request['status']='failed_consumed'
            raise
        finally:
            with self.lock:
                self.busy=False

    def artifact_request(self,data):
        fields(data,{'tool','model','stage','parent_id'},{'tool','model','stage'})
        if data['model'] not in ACTORS-{'controller'}:raise ValueError('Unknown model')
        with self.lock:
            parent=next((dict(r) for r in self.downloads if r['request_id']==data.get('parent_id')),None)
        value=artifacts.request(data['tool'],data['model'],data['stage'],parent)
        with self.lock:self.downloads.append(value)
        self.team.bus.send(data['model'],'controller','artifact_request',{k:v for k,v in value.items() if k in {'request_id','tool','model','stage','revision','url','sha256','status','section','expires_at','reason'}})
        return dict(value)

    def artifact_decide(self,data):
        fields(data,{'request_id','decision'},{'request_id','decision'})
        if data['decision'] not in {'approve','reject','revoke'}:raise ValueError('Invalid decision')
        with self.lock:
            r=next((v for v in self.downloads if v['request_id']==data['request_id']),None)
            if r is None or r['status'] not in {'pending','approved','approved_plan_only'}:raise ValueError('No pending/approved request')
            if permissions.expired(r):r['status']='expired';raise ValueError('Request expired')
            if data['decision']=='approve':
                if r['status']!='pending':raise ValueError('Already approved')
                r['status']='approved' if r['executable'] else 'approved_plan_only'
            else:r['status']='revoked' if data['decision']=='revoke' else 'rejected'
            result=dict(r)
        self.team.bus.send('controller',r['model'],'approval_decision',{'request_id':r['request_id'],'status':r['status'],'model':r['model'],'section':r['section'],'reason':r['reason']})
        return result

    def artifact_execute(self,data):
        fields(data,{'request_id','model'},{'request_id','model'})
        with self.lock:
            r=next((v for v in self.downloads if v['request_id']==data['request_id']),None)
            if r is None or r['status']!='approved' or r['uses_left']!=1 or r['model']!=data['model'] or not r['executable']:raise ValueError('No exact one-use artifact approval')
            if permissions.expired(r):r['status']='expired';raise ValueError('Request expired')
            if self.busy:raise RuntimeError('A command is running')
            self.busy=True;r['uses_left']=0;r['status']='running';value=dict(r)
            parent=next((dict(v) for v in self.downloads if v['request_id']==r.get('parent_id')),None)
        def perform():
            try:
                result=artifacts.download(value) if value['stage']=='download' else artifacts.extract(value,parent)
                with self.lock:r.update(status='consumed',sha256=result['sha256'],result=result)
                self.team.bus.send(value['model'],'defender','artifact_result',{'request_id':value['request_id'],'model':value['model'],'stage':value['stage'],'sha256':result['sha256'],'reason':result['limits']})
            except Exception as error:
                with self.lock:r.update(status='failed_consumed',error=str(error) if isinstance(error,ValueError) else type(error).__name__)
            finally:
                with self.lock:self.busy=False
        self.executor.submit(perform)
        return {'request_id':r['request_id'],'status':'running'}

    def evidence_action(self, action, data):
        if action=='review':
            fields(data,{'record_id','version_id','decision','note','checks'},{'record_id','version_id','decision','note','checks'})
            if not isinstance(data['note'],str) or not 1<=len(data['note'])<=1000:raise ValueError('Review note required')
            return self.evidence.review(data['record_id'],data['version_id'],data['decision'],'authenticated_admin',data['note'],data['checks'])
        if action=='freeze':
            fields(data,{'name','kind','members','approved'},{'name','kind','members','approved'})
            if data['approved'] is not True or not isinstance(data['name'],str) or not 1<=len(data['name'])<=100 or not isinstance(data['members'],list) or not 1<=len(data['members'])<=100:raise ValueError('Explicit bounded dataset approval required')
            return self.evidence.freeze_dataset(data['name'],data['kind'],data['members'],'authenticated_admin')
        if action=='delete':
            fields(data,{'record_id','reason','confirmed'},{'record_id','reason','confirmed'})
            if data['confirmed'] is not True or not isinstance(data['reason'],str) or not 1<=len(data['reason'])<=1000:raise ValueError('Explicit deletion confirmation and reason required')
            return self.evidence.delete_record(data['record_id'],data['reason'])
        if action=='expire':
            fields(data,{'confirmed'},{'confirmed'})
            if data['confirmed'] is not True:raise ValueError('Explicit retention confirmation required')
            return self.evidence.expire_retention(datetime.now(timezone.utc).isoformat())
        raise ValueError('Unknown evidence action')

    def close(self):
        self.idle_trainer.close()
        self.training_coordinator.close()
        self.executor.shutdown(wait=True, cancel_futures=True)
        if self.evidence_temp:self.evidence_temp.cleanup()


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8

    def __init__(self, address, app):
        self.app = app
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    server_version = 'LocalResearchLab'
    sys_version = ''

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *_):
        pass  # No credentials, cookies, submitted text, or request bodies in access logs.

    def respond(self, status, body, content_type='application/json', cookie=None, download_name=None):
        data = json.dumps(body).encode() if content_type == 'application/json' else body
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.send_header('X-Frame-Options', 'DENY')
        if download_name:
            self.send_header('Content-Disposition', 'attachment; filename="'+download_name+'"')
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def boundary(self, mutate=False):
        port = int(__import__('os').environ.get('AZRAEL_PORT', self.server.server_port))
        allowed = {f'127.0.0.1:{port}', f'localhost:{port}'}
        host = self.headers.get('Host')
        if host not in allowed:
            self.respond(403, {'error': 'Unexpected Host header'})
            return False
        origin = self.headers.get('Origin')
        if origin and origin != f'http://{host}':
            self.respond(403, {'error': 'Cross-origin requests are forbidden'})
            return False
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            self.respond(403, {'error': 'Cross-site requests are forbidden'})
            return False
        if mutate and self.headers.get('X-Lab-Request') != '1':
            self.respond(403, {'error': 'Missing request protection header'})
            return False
        return True

    def authenticated(self):
        try:
            cookies = SimpleCookie(self.headers.get('Cookie', ''))
            value = cookies['lab_session'].value if 'lab_session' in cookies else ''
        except CookieError:
            value = ''
        try:
            with self.server.app.lock:
                return time.monotonic() < self.server.app.session_expires_at and hmac.compare_digest(value, self.server.app.session)
        except TypeError:
            return False

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/healthz':
            self.respond(200, {'status':'ok','slm_weights_available':slm.available()})
            return
        if not self.boundary():
            return
        static = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                  '/style.css': ('style.css', 'text/css; charset=utf-8'), '/ops.js': ('ops.js', 'text/javascript; charset=utf-8'),
                  '/training.js': ('training.js', 'text/javascript; charset=utf-8')}
        static.update(branding.static_art())
        static['/azrael.css']=('azrael.css','text/css; charset=utf-8')
        static['/scene.js']=('scene.js','text/javascript; charset=utf-8')
        static['/poc.js']=('poc.js','text/javascript; charset=utf-8')
        static['/setup.js']=('setup.js','text/javascript; charset=utf-8')
        static['/role-research.js']=('role-research.js','text/javascript; charset=utf-8')
        for artwork in ('signal','crimson','cipher','atlas'):
            static['/art/'+artwork+'.png']=('art/'+artwork+'.png','image/png')
        if path in static:
            name, mime = static[path]
            self.respond(200, (WEB / name).read_bytes(), mime)
        elif path == '/api/artifact/file':
            if not self.authenticated():
                self.respond(401, {'error':'Authentication required'}); return
            identifier=parse_qs(urlsplit(self.path).query).get('id',[''])[0]
            with self.server.app.lock:
                artifact=next((dict(r) for r in self.server.app.downloads if r['request_id']==identifier and r['stage']=='download' and r['status']=='consumed'),None)
            if artifact is None:
                self.respond(404, {'error':'Artifact not found'}); return
            data=storage_paths.artifact_path(ROOT,identifier,'source.tar.gz').read_bytes()
            if __import__('hashlib').sha256(data).hexdigest()!=artifact['sha256']:
                self.respond(409, {'error':'Artifact changed'}); return
            self.respond(200,data,'application/octet-stream',download_name=artifact['tool']+'-'+artifact['revision']+'.tar.gz')
        elif path=='/api/council':
            if not self.authenticated():self.respond(401,{'error':'Authentication required'});return
            try:self.respond(200,self.server.app.council.get(parse_qs(urlsplit(self.path).query).get('id',[''])[0]))
            except (ValueError,FileNotFoundError):self.respond(404,{'error':'Unknown council review'})
        elif path == '/api/ctf':
            if not self.authenticated():
                self.respond(401, {'error': 'Authentication required'}); return
            try:self.respond(200,self.server.app.ctf_lab.catalog())
            except RuntimeError as error:self.respond(503,{'error':str(error)})
        elif path == '/api/training':
            if not self.authenticated():
                self.respond(401, {'error': 'Authentication required'}); return
            self.respond(200, {'coordinator': self.server.app.training_coordinator.status(),
                               'missions': self.server.app.training_coordinator.list(20)})
        elif path == '/api/training/missions':
            if not self.authenticated():
                self.respond(401, {'error': 'Authentication required'}); return
            self.respond(200, self.server.app.training_coordinator.list(20))
        elif path.startswith('/api/training/missions/'):
            if not self.authenticated():
                self.respond(401, {'error': 'Authentication required'}); return
            mission_id = path.removeprefix('/api/training/missions/')
            try:
                if mission_id.endswith('/export'):
                    mission_id = mission_id.removesuffix('/export')
                    self.respond(200, self.server.app.training_coordinator.export(mission_id),
                                 download_name='azrael-training-'+mission_id+'.json')
                else:
                    self.respond(200, self.server.app.training_coordinator.get(mission_id))
            except ValueError as error:
                self.respond(404, {'error': str(error)})
        elif path == '/api/training/datasets':
            if not self.authenticated():
                self.respond(401, {'error': 'Authentication required'}); return
            self.respond(200, self.server.app.training_coordinator.metrics()['dataset_versions'])
        elif path=='/api/install':
            if not self.authenticated():self.respond(401,{'error':'Authentication required'});return
            try:self.respond(200,self.server.app.installation.details(parse_qs(urlsplit(self.path).query).get('id',[''])[0]))
            except (ValueError,FileNotFoundError):self.respond(404,{'error':'Unknown install request'})
        elif path=='/api/research/dorks':
            if not self.authenticated():self.respond(401,{'error':'Authentication required'});return
            try:self.respond(200,self.server.app.role_research.dorks(parse_qs(urlsplit(self.path).query).get('role',[''])[0]))
            except ValueError as error:self.respond(400,{'error':str(error)})
        elif path=='/api/research/dataset':
            if not self.authenticated():self.respond(401,{'error':'Authentication required'});return
            try:
                role=parse_qs(urlsplit(self.path).query).get('role',[''])[0]
                raw=self.server.app.role_research.dataset(role)
                self.respond(200,raw,'application/x-ndjson',download_name=role+'-references.jsonl')
            except (ValueError,FileNotFoundError):self.respond(404,{'error':'Unknown role dataset'})
        elif path=='/api/evidence/trace':
            if not self.authenticated():self.respond(401,{'error':'Authentication required'});return
            try:
                query=parse_qs(urlsplit(self.path).query)
                self.respond(200,self.server.app.evidence.trace(query.get('id',[''])[0],limit=20,offset=int(query.get('offset',['0'])[0])))
            except ValueError:self.respond(400,{'error':'Unknown evidence record'})
        elif path == '/api/feature-schema':
            if not self.authenticated():
                self.respond(401, {'error': 'Authentication required'})
            else:
                self.respond(200, json.loads(storage_paths.training_file(ROOT,'models-public','android-feature-schema.json').read_text()))
        elif path == '/api/state':
            if not self.authenticated():
                self.respond(401, {'error': 'Authentication required'})
            else:
                self.respond(200, self.server.app.snapshot())
        elif path.startswith('/api/ops/'):
            if not self.authenticated():
                self.respond(401, {'error': 'Authentication required'})
            else:
                name = path.removeprefix('/api/ops/')
                try:
                    self.respond(200, ops_api.endpoint(self.server.app, name))
                except ValueError:
                    self.respond(404, {'error': 'Unknown operations endpoint'})
                except (OSError, RuntimeError, KeyError) as error:
                    self.respond(503, {'error': 'Operations telemetry is temporarily unavailable',
                                       'error_type': type(error).__name__})
        else:
            self.respond(404, {'error': 'Not found'})

    def do_POST(self):
        if not self.boundary(mutate=True):
            return
        try:
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                self.respond(415, {'error': 'JSON required'}); return
            if self.headers.get('Transfer-Encoding'):
                self.respond(400, {'error': 'Transfer encoding unsupported'}); return
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 32768:
                self.respond(413, {'error': 'Body must be 1–32768 bytes'}); return
            data = json.loads(self.rfile.read(length))
            path = urlsplit(self.path).path
            app = self.server.app
            if path == '/api/login':
                fields(data, {'token'}, {'token'})
                if not isinstance(data['token'], str):
                    raise ValueError('Token must be a string')
                now = time.monotonic()
                with app.lock:
                    while app.login_attempts and app.login_attempts[0] < now - 60:
                        app.login_attempts.popleft()
                    if len(app.login_attempts) >= 10:
                        self.respond(429, {'error': 'Too many login attempts; wait one minute'}); return
                    app.login_attempts.append(now)
                if not hmac.compare_digest(data['token'], app.token):
                    self.respond(401, {'error': 'Invalid login'}); return
                with app.lock:
                    app.session=secrets.token_urlsafe(32)
                    app.session_expires_at=time.monotonic()+3600
                    session=app.session
                self.respond(200, {'ok': True}, cookie=f'lab_session={session}; Max-Age=3600; HttpOnly; SameSite=Strict; Path=/')
                return
            if not self.authenticated():
                self.respond(401, {'error': 'Authentication required'}); return
            if path == '/api/ctf/attempt':
                fields(data, {'challenge_id','flag'}, {'challenge_id','flag'})
                self.respond(200, app.ctf_lab.attempt(data['challenge_id'],data['flag']))
            elif path == '/api/ctf/practice':
                fields(data, {'challenge_id','role'}, {'challenge_id'})
                role=data.get('role','analyst')
                if role not in ACTORS-{'controller'}:raise ValueError('Unknown role')
                app.ctf_lab.challenge(data['challenge_id'])
                result=app.submit({'action':'ctf_practice','text':json.dumps({'challenge_id':data['challenge_id']}),'role':role})
                self.respond(202,result)
            elif path == '/api/training/missions':
                result = app.training_coordinator.start(data)
                self.respond(202, result)
            elif path == '/api/training/emergency-stop':
                fields(data, set(), set())
                self.respond(200, app.training_coordinator.emergency_stop())
            elif path == '/api/training/reset':
                fields(data, {'confirmed'}, {'confirmed'})
                self.respond(200, app.training_coordinator.reset_emergency_stop(data['confirmed']))
            elif path.startswith('/api/training/missions/') and path.endswith('/cancel'):
                fields(data, set(), set())
                mission_id = path.removeprefix('/api/training/missions/').removesuffix('/cancel')
                self.respond(200, app.training_coordinator.cancel(mission_id))
            elif path.startswith('/api/training/missions/') and path.endswith('/review'):
                mission_id = path.removeprefix('/api/training/missions/').removesuffix('/review')
                self.respond(200, app.training_coordinator.review(mission_id, data))
            elif path=='/api/install/request':
                with app.lock:result=app.installation.request(data)
                self.respond(202,result)
            elif path=='/api/research/dorks':
                self.respond(200,app.role_research.dork_access(data))
            elif path=='/api/council/decide':
                fields(data,{'id','decision','note'},{'id','decision','note'})
                self.respond(200,app.council.decide(data['id'],data['decision'],'authenticated_admin',data['note']))
            elif path == '/api/command':
                self.respond(202, app.submit(data))
            elif path == '/api/ops/inference':
                result = ops_api.inference(app, data)
                self.respond(200, result)
            elif path=='/api/directives':
                fields(data,{'role','profile','objective'},{'role','profile','objective'})
                self.respond(200,app.directives.assign(data['role'],data['profile'],data['objective']))
            elif path in {'/api/evidence/review','/api/evidence/freeze','/api/evidence/delete','/api/evidence/expire'}:
                self.respond(200,app.evidence_action(path.rsplit('/',1)[1],data))
            elif path == '/api/artifact/request':
                self.respond(201, app.artifact_request(data))
            elif path == '/api/artifact/decide':
                self.respond(200, app.artifact_decide(data))
            elif path == '/api/artifact/execute':
                self.respond(202, app.artifact_execute(data))
            elif path == '/api/approval/request':
                self.respond(201, app.approval(data))
            elif path == '/api/approval/execute':
                self.respond(200, app.execute_approval(data))
            elif path == '/api/approval/decide':
                self.respond(200, app.decide(data))
            elif path == '/api/logout':
                fields(data, set(), set())
                with app.lock:
                    app.session=secrets.token_urlsafe(32)
                    app.session_expires_at=0
                self.respond(200, {'ok': True}, cookie='lab_session=; Max-Age=0; HttpOnly; SameSite=Strict; Path=/')
            else:
                self.respond(404, {'error': 'Not found'})
        except subprocess.TimeoutExpired:
            self.respond(504, {'error': 'Local worker exceeded its request deadline; retry after checking worker health'})
        except OSError:
            self.respond(503, {'error': 'Local worker or required storage is unavailable; check service logs'})
        except (ValueError, TypeError, KeyError, UnicodeError) as error:
            self.respond(400, {'error': str(error) or 'Invalid request'})
        except RuntimeError as error:
            self.respond(409, {'error': str(error) or 'A command is already running'})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', type=int, default=8765)
    p.add_argument('--container',action='store_true')
    args = p.parse_args()
    if not 1024 <= args.port <= 65535:
        p.error('Port must be 1024–65535')
    if args.container and __import__('os').environ.get('LAB_CONTAINER')!='1':p.error('--container requires the configured container environment')
    token=Path('/run/secrets/admin_token').read_text().strip() if args.container else None
    app = App(token=token)
    server = Server(('0.0.0.0' if args.container else '127.0.0.1', args.port), app)
    print(f'Local dashboard: http://127.0.0.1:{args.port}', flush=True)
    if not args.container: print(f'One-session admin login token: {app.token}', flush=True)
    print('No elevated executor configured. Ctrl+C stops the server.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close(); app.close()


if __name__ == '__main__':
    main()
