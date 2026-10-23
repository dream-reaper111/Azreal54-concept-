"""Exact public HTTP targets for explicit per-attempt admin approvals."""
from datetime import datetime,timezone
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit


def public_ip(value):
    address=ipaddress.ip_address(value)
    if not address.is_global or address.is_multicast or address.is_reserved:
        raise ValueError('External HTTP checks require public unicast addresses')
    return str(address)


def parse_target(value):
    if not isinstance(value,str) or not 1<=len(value)<=200 or any(ord(c)<33 or ord(c)>126 for c in value) or '\\' in value:
        raise ValueError('Supply an ASCII HTTP(S) URL of at most 200 characters')
    parsed=urlsplit(value)
    if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.fragment or parsed.query:
        raise ValueError('Target must be HTTP(S), without credentials, query parameters or a fragment')
    port=parsed.port or (443 if parsed.scheme=='https' else 80)
    if port!=(443 if parsed.scheme=='https' else 80):raise ValueError('This recipe supports the default HTTP or HTTPS port only')
    host=parsed.hostname
    try:public_ip(host)
    except ValueError:
        try:ipaddress.ip_address(host)
        except ValueError:
            if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?',host):raise ValueError('Invalid public hostname')
        else:raise
    return {'url':value,'host':host,'port':port}


def resolve_public(value):
    target=parse_target(value)
    try:return public_ip(target['host'])
    except ValueError:pass
    request=json.dumps({'host':target['host'],'port':target['port']}).encode()
    result=subprocess.run([sys.executable,'-I',str(Path(__file__).with_name('external_resolver.py'))],
        input=request,capture_output=True,timeout=5,check=True,env={'PATH':'/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8'})
    if len(result.stdout)>8192:raise ValueError('DNS result exceeds bound')
    addresses=json.loads(result.stdout)
    if not isinstance(addresses,list) or not 1<=len(addresses)<=16:raise ValueError('Invalid DNS address set')
    verified=[public_ip(address) for address in addresses]
    return sorted(verified,key=lambda address:(':' in address,address))[0]


def contract(value,address):
    target=parse_target(value);address=public_ip(address)
    pinned='['+address+']' if ':' in address else address
    argv=['curl','--silent','--show-error','--head','--max-time','10','--connect-timeout','3','--max-redirs','0',
          '--noproxy','*','--proto','=http,https']
    try:literal=ipaddress.ip_address(target['host'])
    except ValueError:argv+=['--resolve',f"{target['host']}:{target['port']}:{pinned}"]
    else:
        if str(literal)!=address:raise ValueError('Literal target and resolved address disagree')
    argv+=['--',value]
    return {'tool':'curl','argv':argv,'target':value,'timeout':15}


def validate_approval(data):
    if not isinstance(data,dict) or set(data)!={'request_id','target','model','expires_at','operation'}:
        raise ValueError('Invalid external approval contract')
    if data['operation']!='external_http_headers' or not isinstance(data['request_id'],str) or not re.fullmatch('[a-f0-9]{24}',data['request_id']):
        raise ValueError('Invalid external operation or identity')
    if not isinstance(data['model'],str) or not re.fullmatch('[a-z_]{1,64}',data['model']):raise ValueError('Invalid role identity')
    expiration=datetime.fromisoformat(data['expires_at'])
    now=datetime.now(timezone.utc)
    if expiration.tzinfo is None or not 0<(expiration-now).total_seconds()<=305:
        raise ValueError('External permission expired or exceeds five minutes')
    parse_target(data['target'])
    return data
