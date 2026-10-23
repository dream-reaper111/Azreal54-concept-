"""Retain an externally approved HTTP observation without extending other tool authority."""
import re
import runtime_tools
from external_targets import contract,validate_approval


def execute(approval):
    payload={key:approval[key] for key in ('request_id','target','model','expires_at','operation')}
    validate_approval(payload)
    result=runtime_tools.broker('/run',payload,service='external-tools')
    if not isinstance(result,dict) or not isinstance(result.get('resolved_ip'),str):raise ValueError('Missing observed address')
    recipe=contract(approval['target'],result['resolved_ip'])
    if type(result.get('redacted_cookie_lines')) is not int or not 0<=result['redacted_cookie_lines']<=262144:
        raise ValueError('Invalid credential redaction count')
    if not isinstance(result.get('original_output_sha256'),str) or not re.fullmatch('[a-f0-9]{64}',result['original_output_sha256']):
        raise ValueError('Missing original response hash')
    return runtime_tools.retain_result(result,approval,'external_http_headers',recipe,
        extra_fields={'resolved_ip','original_output_sha256','redacted_cookie_lines'})
