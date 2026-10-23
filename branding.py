"""User-supplied local artwork registry; no arbitrary static file access."""
import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parent


def assets():
    items=json.loads((ROOT/'ARTWORK.json').read_text())
    result=[]
    for item in items:
        path=item.get('file','')
        if not re.fullmatch(r'web/art/[a-z0-9-]+\.png',path):raise ValueError('Invalid artwork registry path')
        result.append({'url':'/'+path.removeprefix('web/'),'name':Path(path).stem.replace('-',' ').title(),
                       'sha256':item['sha256'],'use':'decorative user-supplied artwork'})
    return result


def static_art():
    return {a['url']:(a['url'].removeprefix('/'),'image/png') for a in assets()}


def public():
    return {'name':'AZRAEL-54','subtitle':'Security research console','assets':assets(),'artwork_is_telemetry':False}
