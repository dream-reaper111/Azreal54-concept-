"""Separate authenticated public-egress broker: one approved HEAD attempt, no redirects."""
import base64,hashlib,hmac,json
from pathlib import Path
from http.server import HTTPServer,BaseHTTPRequestHandler
from external_targets import validate_approval,resolve_public,contract
from tool_broker import run_contract
USED=set()


def execute(data):
    validate_approval(data)
    if data['request_id'] in USED:raise ValueError('External permission already consumed')
    if len(USED)>=1000:raise ValueError('Broker approval capacity reached; restart explicitly')
    USED.add(data['request_id'])  # DNS and failed attempts also consume the approval.
    address=resolve_public(data['target'])
    result=run_contract('external_http_headers',contract(data['target'],address))
    raw=base64.b64decode(result['output_b64'],validate=True)
    # Structured transport credential redaction; original response hash is retained.
    retained=[];redacted=0;continuation=False
    for line in raw.splitlines(keepends=True):
        if line[:1] in (b' ',b'\t') and continuation:
            redacted+=1;continue
        continuation=line.lower().startswith(b'set-cookie:')
        if continuation:
            retained.append(b'Set-Cookie: [REDACTED]\r\n');redacted+=1
        else:retained.append(line)
    result.update(output_b64=base64.b64encode(b''.join(retained)).decode(),resolved_ip=address,
                  original_output_sha256=hashlib.sha256(raw).hexdigest(),redacted_cookie_lines=redacted)
    return result


class Handler(BaseHTTPRequestHandler):
    def setup(self):super().setup();self.connection.settimeout(5)
    def log_message(self,*_):pass
    def reply(self,status,value):
        raw=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        if self.path=='/healthz':self.reply(200,{'status':'ok'})
        else:self.reply(404,{'error':'Not found'})
    def do_POST(self):
        try:
            if not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+self.server.token):self.reply(401,{'error':'Authentication required'});return
            length=int(self.headers.get('Content-Length','0'))
            if self.path!='/run' or not 0<length<=2048:raise ValueError('Invalid external request')
            self.reply(200,execute(json.loads(self.rfile.read(length))))
        except (ValueError,TypeError,KeyError):self.reply(400,{'error':'Invalid, expired, consumed or unsupported external permission'})
        except Exception:self.reply(502,{'error':'External HTTP observation failed; attempt consumed'})

if __name__=='__main__':
    server=HTTPServer(('0.0.0.0',8792),Handler);server.token=Path('/run/secrets/external_token').read_text().strip();server.serve_forever()
