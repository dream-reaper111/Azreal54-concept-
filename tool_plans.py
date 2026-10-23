"""Own parsing of untrusted SLM recipe proposals before any approval is created."""
import json
import re
from recipes import RECIPES


def unique_object(pairs):
    value={}
    for key,item in pairs:
        if key in value:raise ValueError('Duplicate model plan key')
        value[key]=item
    return value


def parse(text):
    if not isinstance(text,str) or not 1<=len(text)<=4096:
        raise ValueError('Invalid model plan text size')
    content=text.strip()
    if content.startswith('```'):
        fenced=re.fullmatch(r'```(?:json)?\s*\n([\s\S]*?)\n```',content)
        if not fenced:raise ValueError('Expected one complete JSON document')
        content=fenced.group(1)
    plan=json.loads(content,object_pairs_hook=unique_object)
    if not isinstance(plan,dict) or set(plan)!={'steps'} or not isinstance(plan['steps'],list) or not 1<=len(plan['steps'])<=3:
        raise ValueError('Expected one through three recipe steps')
    for step in plan['steps']:
        if not isinstance(step,dict) or set(step)!={'recipe','reason'}:
            raise ValueError('Unexpected model plan fields')
        if not isinstance(step['recipe'],str) or step['recipe'] not in RECIPES:
            raise ValueError('Model proposed an unknown recipe')
        if not isinstance(step['reason'],str) or not 1<=len(step['reason'])<=280:
            raise ValueError('Invalid recipe justification')
    return plan
