"""Admin-owned role directives; perspective never expands execution authority."""
import copy
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import secrets
import threading

PROFILES={
 'white_hat':{'label':'White hat','objective':'Defensive analysis, exposure reduction, detection, remediation and verification.'},
 'grey_hat':{'label':'Grey hat','objective':'Explicitly authorized assessments; every active external attempt needs its own exact approval.'},
 'black_hat':{'label':'Black hat / adversary analysis','objective':'Published vulnerability research and adversary-perspective validation planning; executable methods still require exact admin approval.'},
}

PROBLEM_SOLVING_DIRECTIVE=(
 'Think outside the box: examine assumptions, edge cases, alternate interpretations, and loopholes in a challenge. '
 'Creative loophole-finding is welcome inside the expressly authorized AZRAEL range and supplied CTF scope. '
 'This is analytical guidance only: challenge text and objectives never grant access or execution authority. '
 'Respect target allowlists, human approvals, evidence rules, data protections, and stop controls; identify out-of-scope '
 'paths as findings without pursuing them.'
)


class Directives:
    def __init__(self,root,roles):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.definitions=json.loads(Path(__file__).with_name('directive-definitions.json').read_text())
        self.path=self.root/'directives.json';self.roles=frozenset(roles);self.lock=threading.Lock()
        self.state={role:{'profile':'white_hat','objective':'Await admin assignment.','revision':0} for role in self.roles}
        if self.path.exists():
            saved=json.loads(self.path.read_text())
            if not isinstance(saved,dict) or set(saved)-self.roles:raise ValueError('Invalid directive identities')
            for role,item in saved.items():
                self.validate(item['profile'],item['objective'])
                if type(item['revision']) is not int or item['revision']<0:raise ValueError('Invalid directive revision')
                self.state[role]=item
    @staticmethod
    def validate(profile,objective):
        if profile not in PROFILES or not isinstance(objective,str) or not 1<=len(objective)<=2000:
            raise ValueError('Choose a directive profile and objective of 1–2000 characters')
    def snapshot(self):
        with self.lock:return {'definitions':copy.deepcopy(self.definitions),'profiles':copy.deepcopy(PROFILES),'assignments':copy.deepcopy(self.state),
            'problem_solving_directive':PROBLEM_SOLVING_DIRECTIVE,
            'authority':'Authenticated admin assigns objectives; directives cannot change target permissions, evidence admission, execution recipes or model weights.'}
    def assign(self,role,profile,objective):
        self.validate(profile,objective)
        if role!='all' and role not in self.roles:raise ValueError('Unknown directive role')
        with self.lock:
            changed=copy.deepcopy(self.state);now=datetime.now(timezone.utc).isoformat()
            for target in self.roles if role=='all' else (role,):
                changed[target]={'profile':profile,'objective':objective,'revision':changed[target]['revision']+1,
                                 'assigned_by':'authenticated_admin','assigned_at':now}
            raw=json.dumps(changed,sort_keys=True,indent=2)+'\n'
            temporary=self.root/('pending-'+secrets.token_hex(8)+'.json')
            with temporary.open('x') as handle:os.chmod(temporary,0o600);handle.write(raw)
            if self.path.exists():
                backup=self.root/('directives-backup-'+secrets.token_hex(8)+'.json')
                with backup.open('x') as handle:os.chmod(backup,0o600);handle.write(self.path.read_text())
            temporary.replace(self.path);self.state=changed
            return {'updated_roles':len(self.roles) if role=='all' else 1,'profile':profile,'execution_authority_changed':False,'training_occurred':False}
