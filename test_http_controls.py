"""Real handler parsing on in-memory streams, with no listening socket."""
import io
import json
from types import SimpleNamespace
import unittest
from admin import App, Handler
from unittest.mock import patch


class Connection:
    def __init__(self,data):self.data=data;self.output=bytearray()
    def makefile(self,*args,**kwargs):return io.BytesIO(self.data)
    def sendall(self,data):self.output.extend(data)
    def settimeout(self,*args):pass


class HttpControls(unittest.TestCase):
    def setUp(self):
        self.app=App(test_fixtures=True);self.addCleanup(self.app.close)

    def request(self,path,body=None,authenticated=False,protected=True):
        raw=b'' if body is None else json.dumps(body).encode()
        headers=['Host: 127.0.0.1:8765','Origin: http://127.0.0.1:8765','Content-Type: application/json',f'Content-Length: {len(raw)}']
        if authenticated:headers.append('Cookie: lab_session='+self.app.session)
        if protected:headers.append('X-Lab-Request: 1')
        data=(('POST' if body is not None else 'GET')+' '+path+' HTTP/1.0\r\n'+'\r\n'.join(headers)+'\r\n\r\n').encode()+raw
        connection=Connection(data)
        Handler(connection,('127.0.0.1',1),SimpleNamespace(server_port=8765,app=self.app))
        head,payload=bytes(connection.output).split(b'\r\n\r\n',1)
        return int(head.split()[1]),head.decode(),payload

    def test_installer_auth_confirmation_and_no_arbitrary_commands(self):
        request={'operation':'install_and_build','confirmed':True}
        self.assertEqual(self.request('/api/install/request',request)[0],401)
        self.assertEqual(self.request('/api/install/request',request,True,False)[0],403)
        self.assertEqual(self.request('/api/install/request',dict(request,command='id'),True)[0],400)
        self.assertEqual(self.request('/api/install/request',dict(request,confirmed=False),True)[0],400)
        status,_,body=self.request('/api/install/request',request,True)
        self.assertEqual(status,202)
        result=json.loads(body);self.assertEqual(result['status'],'queued')
        self.assertEqual(self.request('/api/install?id='+result['id'])[0],401)
        status,_,body=self.request('/api/install?id='+result['id'],authenticated=True)
        self.assertEqual(status,200);self.assertEqual(json.loads(body)['status'],'queued')
        self.assertFalse(list(self.app.installation.root.rglob('output.log')))

    def test_new_static_assets_and_private_state(self):
        for path in ('/setup.js','/poc.js','/ops.js','/azrael.css','/art/board-a-01-tactical-reaper-hero.png'):
            status,headers,body=self.request(path)
            self.assertEqual(status,200,path);self.assertTrue(body)
            self.assertIn('nosniff',headers)
        self.assertEqual(self.request('/setup_lab.py')[0],404)
        self.assertEqual(self.request('/api/state')[0],401)
        status,_,body=self.request('/api/state',authenticated=True)
        state=json.loads(body);self.assertEqual(status,200)
        self.assertIn('installation',state);self.assertIn('research_libraries',state)
        self.assertNotIn(self.app.token,body.decode());self.assertNotIn(self.app.session,body.decode())

    def test_operations_api_is_authenticated_and_uses_structured_data(self):
        self.assertEqual(self.request('/api/ops/status')[0],401)
        with patch('admin.ops_api.endpoint',return_value={'gpus':{'status':'unavailable'},'models':{'models':[]}}) as endpoint:
            status,_,body=self.request('/api/ops/status',authenticated=True)
            self.assertEqual(status,200)
            self.assertEqual(json.loads(body),{'gpus':{'status':'unavailable'},'models':{'models':[]}})
            endpoint.assert_called_once_with(self.app,'status')
        self.assertEqual(self.request('/api/ops/host-shell',authenticated=True)[0],404)

    def test_operations_inference_requires_authentication_and_validated_fields(self):
        payload={'prompt':'Summarize safe lab monitoring.','device':'cpu'}
        self.assertEqual(self.request('/api/ops/inference',payload)[0],401)
        self.assertEqual(self.request('/api/ops/inference',dict(payload,command='id'),authenticated=True)[0],400)
        with patch('admin.ops_api.inference',return_value={'text':'READY','device':'cpu'}) as inference:
            status,_,body=self.request('/api/ops/inference',payload,authenticated=True)
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)['device'],'cpu')
        inference.assert_called_once_with(self.app,payload)

    def test_offline_ctf_api_requires_auth_and_never_returns_answer_keys(self):
        self.assertEqual(self.request('/api/ctf')[0],401)
        status,_,body=self.request('/api/ctf',authenticated=True)
        self.assertEqual(status,200)
        catalog=json.loads(body)
        self.assertEqual(len(catalog['challenges']),20)
        self.assertFalse(catalog['answers_disclosed'])
        for answer in self.app.ctf_lab._answers.values():
            self.assertNotIn(answer,body.decode())
        challenge_id=catalog['challenges'][0]['id']
        status,_,body=self.request('/api/ctf/attempt',{'challenge_id':challenge_id,'flag':'flag{wrong}'},authenticated=True)
        self.assertEqual(status,200)
        self.assertFalse(json.loads(body)['correct'])
        self.assertEqual(self.request('/api/ctf/attempt',{'challenge_id':'../secret','flag':'x'},authenticated=True)[0],400)

    def test_ctf_model_practice_is_authenticated_and_queues_only_bounded_role_work(self):
        challenge_id=self.app.ctf_lab.catalog()['challenges'][0]['id']
        self.assertEqual(self.request('/api/ctf/practice',{'challenge_id':challenge_id})[0],401)
        with patch.object(self.app,'submit',return_value={'job_id':'practice-test-id'}) as submit:
            status,_,body=self.request('/api/ctf/practice',{'challenge_id':challenge_id,'role':'analyst'},True)
        self.assertEqual(status,202)
        self.assertEqual(json.loads(body),{'job_id':'practice-test-id'})
        self.assertEqual(submit.call_args.args[0]['action'],'ctf_practice')
        self.assertEqual(submit.call_args.args[0]['role'],'analyst')
        self.assertNotIn(self.app.ctf_lab._answers[challenge_id],str(submit.call_args.args[0]))
        self.assertEqual(self.request('/api/ctf/practice',{'challenge_id':challenge_id,'role':'controller'},True)[0],400)
        self.assertEqual(self.request('/api/ctf/practice',{'challenge_id':'../outside'},True)[0],400)

    def test_loopback_health_probe_is_public_and_minimal(self):
        status,_,body=self.request('/healthz')
        self.assertEqual(status,200)
        value=json.loads(body)
        self.assertEqual(value['status'],'ok')
        self.assertIn('slm_weights_available',value)
        self.assertEqual(set(value),{'status','slm_weights_available'})

    def test_login_rotation_expiration_and_logout(self):
        self.assertEqual(self.request('/api/login',{'token':'invalid-audit-fixture'})[0],401)
        previous=self.app.session
        status,headers,_=self.request('/api/login',{'token':self.app.token})
        self.assertEqual(status,200)
        self.assertNotEqual(self.app.session,previous)
        self.assertIn('Max-Age=3600',headers)
        self.assertEqual(self.request('/api/state',authenticated=True)[0],200)
        with patch('admin.time.monotonic',return_value=self.app.session_expires_at+1):
            self.assertEqual(self.request('/api/state',authenticated=True)[0],401)
        self.assertEqual(self.request('/api/logout',{},authenticated=True)[0],200)
        self.assertEqual(self.request('/api/state',authenticated=True)[0],401)

    def test_inference_busy_response_and_capacity_release(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        import slm
        entered=threading.Event();release=threading.Event()
        def held(*args,**kwargs):
            entered.set()
            if not release.wait(5):raise RuntimeError('Fixture deadline')
            return {'text':'Explicit concurrency fixture; no model was run.','device':'cpu'}
        payload={'prompt':'Bounded concurrency fixture','device':'cpu'}
        with patch.object(slm,'_ask',side_effect=held),ThreadPoolExecutor(max_workers=1) as pool:
            first=pool.submit(self.request,'/api/ops/inference',payload,True)
            try:
                self.assertTrue(entered.wait(2))
                self.assertEqual(self.request('/api/ops/inference',payload,True)[0],409)
            finally:release.set()
            self.assertEqual(first.result(timeout=5)[0],200)
            self.assertEqual(self.request('/api/ops/inference',payload,True)[0],200)

    def test_new_role_contexts_use_one_worker_and_remain_untrained(self):
        import subprocess
        import slm
        roles=('dark_signal','nightwatch','fission','containment','event_horizon','sinkhole','crucible','malware_lab_red','malware_lab_blue')
        response=subprocess.CompletedProcess([],0,json.dumps({'text':'Explicit context fixture; no inference performed.','device':'cpu'}),'')
        with patch.object(slm,'available',return_value=True),patch.object(slm,'_run_worker',return_value=response) as worker:
            for role in roles:
                slm.ask(self.app,'admin_chat','Review supplied evidence only.',role,device_selector='cpu')
                payload=json.loads(worker.call_args.args[1])
                self.assertEqual(payload['context']['selected_role']['id'],role)
                self.assertEqual(payload['context']['specialist_count'],66)
                self.assertEqual(payload['context']['selected_role']['status'],'pending_data_and_validation')

    def test_worker_failure_responses_are_bounded_and_do_not_expose_details(self):
        import subprocess
        payload={'prompt':'Isolated failure simulation','device':'cpu'}
        for failure,expected in ((subprocess.TimeoutExpired(['private-worker-path'],180),504),
                                 (OSError('private-storage-detail'),503)):
            with self.subTest(status=expected),patch('admin.ops_api.inference',side_effect=failure):
                status,_,body=self.request('/api/ops/inference',payload,True)
                self.assertEqual(status,expected)
                self.assertIn('error',json.loads(body))
                self.assertNotIn('private-',body.decode())

    def test_frontend_health_is_observed_instead_of_assumed(self):
        import ops_api
        def probe(name,*args):
            return {'service':name,'status':'unavailable' if name=='frontend' else 'healthy','http_status':None}
        with patch.object(ops_api,'_service_probe',side_effect=probe):
            result=ops_api.container_health()
        self.assertEqual(result['status'],'degraded')
        self.assertEqual(next(row for row in result['services'] if row['service']=='frontend')['status'],'unavailable')


if __name__=='__main__':unittest.main()
