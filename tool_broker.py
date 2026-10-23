"""Internal authenticated container tool broker; exact recipes, one request at a time."""
import argparse
from datetime import datetime,timezone
import base64
import hmac
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import time
from http.server import BaseHTTPRequestHandler,HTTPServer
from recipes import RECIPES

LIMIT=262144
PENDING={}


def run_recipe(identifier):
    if identifier not in RECIPES:raise ValueError('Unknown recipe')
    return run_contract(identifier,RECIPES[identifier])


def run_contract(identifier,recipe):
    if PENDING:raise ValueError('Previous process cleanup is unresolved')
    executable=shutil.which(recipe['tool'],path='/usr/bin:/bin')
    if not executable:raise ValueError('Required tool is not installed')
    argv=[executable,*recipe['argv'][1:]]
    started_at=datetime.now(timezone.utc).isoformat()
    started=time.monotonic();output=bytearray();truncated=timed_out=False
    proc=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                          env={'PATH':'/usr/bin:/bin','HOME':'/tmp','LANG':'C.UTF-8'},start_new_session=True)
    # Keep the owned parent unreaped until group cleanup; its PID cannot be reused.
    PENDING[proc.pid]=proc
    selector=selectors.DefaultSelector();selector.register(proc.stdout,selectors.EVENT_READ)
    try:
        deadline=started+recipe['timeout']
        while True:
            remaining=deadline-time.monotonic()
            if remaining<=0:timed_out=True;break
            events=selector.select(min(remaining,.25))
            if not events:continue
            chunk=os.read(proc.stdout.fileno(),65536)
            if not chunk:break
            capacity=LIMIT-len(output);output.extend(chunk[:capacity])
            if len(chunk)>capacity:truncated=True;break
    finally:
        selector.close()
        # Never poll/wait before signalling the process group; ownership stays anchored.
        try:os.killpg(proc.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        try:
            code=proc.wait(timeout=5)
            del PENDING[proc.pid]
        finally:
            proc.stdout.close()
    return {'recipe':identifier,'argv':argv,'target':recipe['target'],'exit_code':code,
            'started_at':started_at,'completed_at':datetime.now(timezone.utc).isoformat(),
            'elapsed_seconds':round(time.monotonic()-started,4),'timed_out':timed_out,'output_truncated':truncated,
            'output_b64':base64.b64encode(output).decode(),'cleanup_pending':bool(PENDING),
            'provenance':'Observed subprocess output, not generated model text'}


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def reply(self,status,data):
        raw=json.dumps(data).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def authorized(self):
        value=self.headers.get('Authorization','')
        try:return hmac.compare_digest(value,'Bearer '+self.server.token)
        except TypeError:return False
    def do_GET(self):
        if self.path=='/healthz':self.reply(200,{'status':'ok'});return
        if not self.authorized():self.reply(401,{'error':'Authentication required'});return
        if self.path!='/status':self.reply(404,{'error':'Not found'});return
        self.reply(200,{'tools':{r['tool']:shutil.which(r['tool'],path='/usr/bin:/bin') is not None for r in RECIPES.values()},'cleanup_pending':bool(PENDING),'target_scope':'Owned internal web-lab only'})
    def do_POST(self):
        if not self.authorized():self.reply(401,{'error':'Authentication required'});return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=4096:raise ValueError('Body bound exceeded')
            data=json.loads(self.rfile.read(length))
            if self.path!='/run' or not isinstance(data,dict) or set(data)!={'recipe'}:raise ValueError('Invalid contract')
            self.reply(200,run_recipe(data['recipe']))
        except (ValueError,TypeError,KeyError):self.reply(400,{'error':'Invalid recipe or unavailable tool'})
        except Exception:self.reply(500,{'error':'Tool execution or cleanup failed'})


def main():
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8790);args=p.parse_args()
    token=Path('/run/secrets/broker_token').read_text().strip()
    server=HTTPServer(('0.0.0.0',args.port),Handler);server.token=token
    server.serve_forever()

if __name__=='__main__':main()
