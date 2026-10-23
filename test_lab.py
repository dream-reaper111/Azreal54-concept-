"""Production-boundary checks for local auth, commands, provenance and permissions."""
import json
import threading
import time
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from admin import App, Server
from lab import Bus
from simulation import spread
from public_training import DATA
import csv,io,zipfile,tarfile,hashlib
from unittest.mock import patch
from datetime import datetime,timezone,timedelta
import artifacts
import permissions


class Boundaries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=App(token='test-only-token',test_fixtures=True)
        try:cls.server=Server(('127.0.0.1',0),cls.app)
        except PermissionError as error:
            cls.app.close()
            raise unittest.SkipTest('Sandbox forbids local listening sockets: '+str(error)) from error
        cls.port=cls.server.server_port
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.port}'

    @classmethod
    def tearDownClass(cls):
        if getattr(cls,'server',None) is not None:
            cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.app.close()

    def request(self,path,body=None,authenticated=False,headers=None):
        h={'X-Lab-Request':'1','Content-Type':'application/json','Origin':self.base}
        if authenticated:
            h['Cookie']='lab_session='+self.app.session
        h.update(headers or {})
        data=None if body is None else json.dumps(body).encode()
        req=Request(self.base+path,data=data,headers=h)
        try:
            response=urlopen(req,timeout=10)
        except HTTPError as error:
            response=error
        return response.status,response.headers,response.read()

    def test_authentication(self):
        self.assertEqual(self.request('/api/state')[0],401)
        self.assertEqual(self.request('/api/login',{'token':'wrong'})[0],401)
        status,headers,_=self.request('/api/login',{'token':'test-only-token'})
        self.assertEqual(status,200);self.assertIn('HttpOnly',headers['Set-Cookie']);self.assertIn('SameSite=Strict',headers['Set-Cookie'])
        self.assertEqual(self.request('/api/state',authenticated=True)[0],200)

    def test_cross_origin_and_host(self):
        self.assertEqual(self.request('/api/state',authenticated=True,headers={'Host':'evil.example'})[0],403)
        self.assertEqual(self.request('/api/command',{'action':'exercise'},True,{'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.request('/api/command',{'action':'exercise'},True,{'X-Lab-Request':''})[0],403)

    def test_static_and_no_traversal(self):
        for path in ['/','/app.js','/style.css','/training.js']:
            status,headers,body=self.request(path);self.assertEqual(status,200);self.assertTrue(body);self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])
        self.assertIn(b'id="trainingConsole"',self.request('/')[2])
        self.assertEqual(self.request('/../admin.py')[0],404)
        self.assertEqual(self.request('/slm-model-manifest.json')[0],404)

    def test_live_training_console_requires_auth_and_operator_approval(self):
        self.assertEqual(self.request('/api/training')[0],401)
        status,_,body=self.request('/api/training',authenticated=True)
        self.assertEqual(status,200)
        payload=json.loads(body)
        self.assertEqual(payload['coordinator']['concurrency_limit'],1)
        self.assertTrue(payload['coordinator']['synthetic_fixtures_preserved'])
        self.assertEqual(self.request('/api/training/missions',{'approved':True},False)[0],401)
        status,_,body=self.request('/api/training/missions',{'approved':False},True)
        self.assertEqual(status,400)
        self.assertIn('approval',json.loads(body)['error'].lower())

    def test_command_boundary(self):
        for body in [{'action':'shell','text':'whoami'},{'action':'exercise','rounds':100000},{'action':'exercise','rounds':True},{'action':'exercise','shell':'id'}, {'action':'analyze','role':'offense_test','text':'sample'}]:
            self.assertEqual(self.request('/api/command',body,True)[0],400)
        self.assertEqual(self.request('/api/command',{'action':'tools','text':'x'*40000},True)[0],413)

    def test_human_approval_is_not_execution(self):
        status,_,body=self.request('/api/approval/request',{'operation':'isolated_crash_replay','target':'disposable-lab-vm'},True)
        self.assertEqual(status,201);request=json.loads(body)
        status,_,body=self.request('/api/approval/decide',{'request_id':request['request_id'],'decision':'approve_plan'},True)
        self.assertEqual(status,200);self.assertEqual(json.loads(body)['status'],'approved_plan_only')
        self.assertFalse(self.app.snapshot()['security']['privileged_execution'])
        event=next(e for e in self.app.team.bus.snapshot() if e['kind']=='approval_request' and e['payload']['request_id']==request['request_id'])
        self.assertEqual(event['payload']['status'],'pending')
        self.assertEqual(self.request('/api/approval/decide',{'request_id':request['request_id'],'decision':'approve_plan'},True)[0],400)

    def test_public_model_inputs(self):
        with zipfile.ZipFile(DATA/'tuandromd.zip') as z:
            rows=csv.DictReader(io.StringIO(z.read('TUANDROMD.csv').decode('utf-8-sig')))
            row=next(rows)
        values={k:int(v) for k,v in row.items() if k!='Label'}
        result=self.app.research.analyze('malware_static',json.dumps(values))
        self.assertIn(result['category'],{'malware','goodware'})
        with self.assertRaises(ValueError):
            self.app.research.analyze('malware_static','{"ACCESS_NETWORK_STATE": 1}')
        for role,text in [('bounty_review','cursor.execute("SELECT * FROM data WHERE id=" + input_id)'),('malware_behavior','Repeated periodic network connections to a remote server'),('cve_triage','An unauthenticated input causes a remote buffer overflow')]:
            result=self.app.research.analyze(role,text);self.assertIn('scores',result)
        self.assertEqual(len(self.app.snapshot()['roles']),66)

    def test_message_ownership_and_bounds(self):
        b=Bus();p={'decision':'one'};b.send('controller','defender','summary',p);p['decision']='two';copy=b.snapshot();copy[0]['payload']['decision']='three';self.assertEqual(b.snapshot()[0]['payload']['decision'],'one')
        for args in [('unknown','defender','summary',{}),('controller','defender','shell',{}),('controller','defender','summary',{'command':'id'}),('controller','defender','summary',{'reason':'x'*20000})]:
            with self.assertRaises(ValueError):b.send(*args)

    def test_simulation_bounded(self):
        b=Bus();result=spread(b,3,100);self.assertEqual(len(result['timeline']),3);self.assertEqual(result['nodes'],40)
        for row in result['timeline']:self.assertLessEqual(row['contained'],row['ever_infected']);self.assertLessEqual(row['ever_infected'],40)
        with self.assertRaises(ValueError):spread(b,100000,1)

    def test_scoped_expiring_single_use_demo(self):
        request=self.app.approval({'operation':'demo_sql_injection','target':'builtin://sqlite-demo','model':'web_red','section':'vulnerability'})
        with self.assertRaises(ValueError):self.app.execute_approval({'request_id':request['request_id'],'model':'web_red','section':'vulnerability'})
        self.app.decide({'request_id':request['request_id'],'decision':'approve_plan'})
        with self.assertRaises(ValueError):self.app.execute_approval({'request_id':request['request_id'],'model':'offense_test','section':'vulnerability'})
        result=self.app.execute_approval({'request_id':request['request_id'],'model':'web_red','section':'vulnerability'})
        self.assertEqual(result['vulnerable_fixture_rows'],3);self.assertEqual(result['parameterized_fixture_rows'],0)
        with self.assertRaises(ValueError):self.app.execute_approval({'request_id':request['request_id'],'model':'web_red','section':'vulnerability'})
        request=self.app.approval({'operation':'demo_sql_injection','target':'builtin://sqlite-demo'})
        self.app.decide({'request_id':request['request_id'],'decision':'approve_plan'});self.app.decide({'request_id':request['request_id'],'decision':'revoke'})
        with self.assertRaises(ValueError):self.app.execute_approval({'request_id':request['request_id'],'model':'offense_test','section':'vulnerability'})
        request=self.app.approval({'operation':'demo_sql_injection','target':'builtin://sqlite-demo'})
        stored=next(v for v in self.app.approvals if v['request_id']==request['request_id']);stored['expires_at']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        with self.assertRaises(ValueError):self.app.decide({'request_id':request['request_id'],'decision':'approve_plan'})
        for request in [{'operation':'rf_lab_test','target':'lab','model':'web_red','section':'radio'}, {'operation':'demo_sql_injection','target':'https://example.com'}, {'operation':'isolated_static_analysis','target':'lab','model':'defender'}]:
            with self.assertRaises(ValueError):permissions.proposal(request,allow_demo=True)

    def test_public_domain_models(self):
        network=[0,'tcp','http','SF']+[0]*37
        for role in ['network_red','network_blue']:
            result=self.app.domains.analyze(role,json.dumps(network));self.assertIn('scores',result)
        for role in ['rf_red','rf_blue']:
            result=self.app.domains.analyze(role,json.dumps([-64,-56,-61,-66,-71,-82,-81]));self.assertIn(result['category'],['1','2','3','4'])
        for role in ['web_red','web_blue']:
            self.assertIn('scores',self.app.domains.analyze(role,'<?php echo $_GET["message"]; ?>'))
        from automotive import NAMES
        for role in ['automotive_red','automotive_blue']:
            result=self.app.automotive.analyze(role,json.dumps({n:0.0 for n in NAMES}));self.assertIn(result['category'],['normal_window','attack_window']);self.assertIn('simulation',result['reason'])

    def test_artifact_stage_permissions_and_extraction(self):
        data=io.BytesIO()
        with tarfile.open(fileobj=data,mode='w:gz') as archive:
            member=tarfile.TarInfo('source/README.txt');member.size=4;archive.addfile(member,io.BytesIO(b'demo'))
        with patch('artifacts.fetch',return_value=json.dumps({'sha':'a'*40}).encode()):
            request=self.app.artifact_request({'tool':'can-utils','model':'automotive_blue','stage':'download'})
        self.app.artifact_decide({'request_id':request['request_id'],'decision':'approve'})
        with patch('artifacts.fetch',return_value=data.getvalue()):
            self.app.artifact_execute({'request_id':request['request_id'],'model':'automotive_blue'})
            self.wait_artifact(request['request_id'])
        r=next(v for v in self.app.downloads if v['request_id']==request['request_id']);self.assertEqual(r['status'],'consumed')
        status,headers,body=self.request('/api/artifact/file?id='+r['request_id'],authenticated=True)
        self.assertEqual(status,200);self.assertEqual(body,data.getvalue());self.assertIn('attachment',headers['Content-Disposition'])
        with self.assertRaises(ValueError):self.app.artifact_execute({'request_id':r['request_id'],'model':'automotive_blue'})
        request=self.app.artifact_request({'tool':'can-utils','model':'automotive_blue','stage':'extract','parent_id':r['request_id']})
        self.app.artifact_decide({'request_id':request['request_id'],'decision':'approve'})
        self.app.artifact_execute({'request_id':request['request_id'],'model':'automotive_blue'});self.wait_artifact(request['request_id'])
        extract=next(v for v in self.app.downloads if v['request_id']==request['request_id']);self.assertEqual(extract['status'],'consumed');self.assertFalse(extract['result']['executed'])
        plan=self.app.artifact_request({'tool':'can-utils','model':'automotive_blue','stage':'install','parent_id':extract['request_id']})
        result=self.app.artifact_decide({'request_id':plan['request_id'],'decision':'approve'});self.assertEqual(result['status'],'approved_plan_only')
        with self.assertRaises(ValueError):self.app.artifact_execute({'request_id':plan['request_id'],'model':'automotive_blue'})

    def wait_artifact(self,identifier):
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            with self.app.lock:r=next(dict(v) for v in self.app.downloads if v['request_id']==identifier)
            if r['status']!='running':return
            time.sleep(.02)
        self.fail('Artifact stage timed out')

    def test_archive_path_link_and_expansion_fail_closed(self):
        from pathlib import Path
        import tempfile
        for kind in ['traversal','symlink','oversize']:
            with tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);parent={'request_id':'parent'};folder=root/'artifacts/parent';folder.mkdir(parents=True);path=folder/'source.tar.gz'
                with tarfile.open(path,'w:gz') as archive:
                    member=tarfile.TarInfo('../escape' if kind=='traversal' else 'source/file')
                    if kind=='symlink':member.type=tarfile.SYMTYPE;member.linkname='/etc/passwd'
                    if kind=='oversize':member.size=artifacts.MAX_EXPANDED+1
                    archive.addfile(member)
                value={'request_id':'test','sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
                with patch('artifacts.ROOT',root):
                    with self.assertRaises(ValueError):artifacts.extract(value,parent)
                self.assertFalse((root/'escape').exists());self.assertTrue((root/'artifacts/test/manifest.json').exists())

    def test_external_admin_permission_is_required_and_consumed(self):
        import runtime_tools,external_runtime
        with patch.object(runtime_tools,'configured',return_value=True):
            request=self.app.approval({'model':'satellite_red','section':'external','operation':'external_http_headers','target':'https://example.com/'})
        with self.assertRaises(ValueError):self.app.decide({'request_id':request['request_id'],'decision':'approve_plan'})
        approved=self.app.decide({'request_id':request['request_id'],'decision':'approve_plan','authorized':True})
        self.assertTrue(approved['authorization_confirmed'])
        self.assertEqual(approved['approved_by'],'authenticated_admin')
        with self.assertRaises(ValueError):self.app.execute_approval({'request_id':request['request_id'],'model':'scada_red','section':'external'})
        with patch.object(external_runtime,'execute',return_value={'observed':'Explicit test fixture; no external request performed.'}) as execute:
            self.app.execute_approval({'request_id':request['request_id'],'model':'satellite_red','section':'external'})
            self.assertEqual(execute.call_count,1)
            with self.assertRaises(ValueError):self.app.execute_approval({'request_id':request['request_id'],'model':'satellite_red','section':'external'})

    def test_directive_and_evidence_api_boundaries(self):
        body={'role':'scada_blue','profile':'white_hat','objective':'Review supplied configuration references.'}
        self.assertEqual(self.request('/api/directives',body)[0],401)
        status,_,raw=self.request('/api/directives',body,True)
        self.assertEqual(status,200)
        self.assertFalse(json.loads(raw)['execution_authority_changed'])
        self.assertEqual(self.request('/api/evidence/trace?id=missing')[0],401)
        self.assertEqual(self.request('/api/evidence/trace?id=missing',authenticated=True)[0],400)
        self.assertEqual(self.request('/api/evidence/freeze',{'name':'invalid','kind':'training','members':[],'approved':True},True)[0],400)
        self.assertEqual(self.request('/api/evidence/expire',{'confirmed':False},True)[0],400)

    def test_production_blocks_fixtures_and_untrained_roles(self):
        with patch.object(self.app,'test_fixtures',False):
            for command in ({'action':'simulate','rounds':1},
                            {'action':'exercise','rounds':1},
                            {'action':'analyze','role':'hephaestus','text':'review'},
                            {'action':'analyze','role':'automotive_blue','text':'{}'}):
                with self.assertRaises(ValueError):self.app.submit(command)
        state=self.app.snapshot()
        self.assertEqual(set(state['shared_modes']),{'observe','analyze','plan','verify'})
        self.assertFalse(state['readiness']['obsidian']['classifier_enabled'])

    def test_live_public_command_boundary(self):
        import live_data
        catalog=json.dumps({'count':1,'catalogVersion':'fixture-only','vulnerabilities':[
            {'cveID':'CVE-2025-12345','vendorProject':'boundary fixture','dateAdded':'2025-01-01'}]}).encode()
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(live_data,'ROOT',Path(folder)),patch.object(live_data,'fetch',return_value=catalog):
                response=self.app.submit({'action':'live_intel','role':'obsidian','text':'boundary'})
                for _ in range(200):
                    job=next(j for j in self.app.snapshot()['jobs'] if j['id']==response['job_id'])
                    if job['status']!='running':break
                    time.sleep(.01)
                self.assertEqual(job['status'],'completed',job)
                self.assertEqual(job['result']['matched_records'],1)
                self.assertFalse(job['result']['training_performed'])

    def test_logout_invalidates_cookie(self):
        cookie='lab_session='+self.app.session
        self.assertEqual(self.request('/api/logout',{},True)[0],200)
        self.assertEqual(self.request('/api/state',headers={'Cookie':cookie})[0],401)

    def test_browser_admin_workflow(self):
        from pathlib import Path
        from playwright.sync_api import sync_playwright
        screenshots=Path(__file__).resolve().parent/'screenshots'
        screenshots.mkdir(exist_ok=True)
        with sync_playwright() as p:
            if not Path(p.chromium.executable_path).exists():
                self.skipTest('Chromium is unavailable')
            browser=p.chromium.launch(headless=True)
            try:
                page=browser.new_page(viewport={'width':1536,'height':1024},device_scale_factor=1)
                errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(self.base,wait_until='networkidle')
                page.locator('#login').wait_for(state='visible')
                page.screenshot(path=str(screenshots/'login.png'),full_page=True)
                for theme in ('crimson','cipher','atlas'):
                    page.select_option('#artTheme',theme)
                    self.assertEqual(page.locator('body').get_attribute('data-art'),theme)
                    page.screenshot(path=str(screenshots/('login-'+theme+'.png')),full_page=True)
                page.select_option('#artTheme','signal')
                page.locator('#token').fill('test-only-token')
                page.locator('#loginForm button').click()
                page.locator('#workspace').wait_for(state='visible')
                self.assertEqual(page.locator('.model-card').count(),66)
                before=page.locator('#roleScene').evaluate('(canvas)=>canvas.toDataURL()')
                page.locator('#roleScene').focus();page.keyboard.press('ArrowRight')
                after=page.locator('#roleScene').evaluate('(canvas)=>canvas.toDataURL()')
                self.assertNotEqual(before,after)
                page.select_option('#sharedMode','plan')
                self.assertEqual(page.locator('#action').input_value(),'council_review')
                self.assertFalse(page.locator('#roleGroup').is_hidden())
                page.select_option('#sharedMode','observe')
                page.select_option('#action','hak5_repos')
                self.assertTrue(page.locator('#textGroup').is_hidden())
                page.select_option('#action','live_intel')
                page.locator('#directivePanel summary').click()
                page.select_option('#directiveRole','obsidian')
                page.select_option('#directiveProfile','black_hat')
                page.fill('#directiveObjective','Review public privacy references; request approval before active tests.')
                page.locator('#directiveForm button').click()
                page.locator('#directiveResult').filter(has_text='Assigned to 1 roles').wait_for()
                page.locator('#directivePanel summary').click()
                page.evaluate('window.scrollTo(0,0)')
                page.screenshot(path=str(screenshots/'dashboard-top.png'),full_page=False)
                page.select_option('#action','tools')
                page.fill('#inputText','can-utils automotive')
                page.locator('#submitCommand').click()
                page.locator('#jobs .status').filter(has_text='completed').first.wait_for(state='visible')
                page.locator('.event').first.wait_for(state='visible')
                page.screenshot(path=str(screenshots/'dashboard.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(screenshots/'dashboard-mobile.png'),full_page=True)
                self.assertLessEqual(page.locator('html').evaluate('(element) => element.scrollWidth'),390)
                self.assertFalse(errors,errors)
                page.locator('#logout').click()
                page.locator('#login').wait_for(state='visible')
                page.locator('#reduceMotion').check()
                self.assertTrue(page.locator('#sceneRotate').is_disabled())
            finally:
                browser.close()

    def test_real_command_round_trip(self):
        status,_,body=self.request('/api/command',{'action':'simulate','rounds':2},True)
        self.assertEqual(status,202);job=json.loads(body)['job_id']
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            state=self.app.snapshot();found=next(j for j in state['jobs'] if j['id']==job)
            if found['status']!='running':break
            time.sleep(.02)
        self.assertEqual(found['status'],'completed');self.assertEqual(len(found['result']['timeline']),2)

if __name__=='__main__':unittest.main(verbosity=2)
