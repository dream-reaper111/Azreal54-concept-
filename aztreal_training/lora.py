"""Native PyTorch LoRA adapters, response-only supervised loss, immutable base weights."""
import ast
import json
import math
import operator
from pathlib import Path


def install(model,rank):
    import torch
    from torch import nn
    class LoRALinear(nn.Module):
        def __init__(self,base):
            super().__init__();self.base=base;self.enabled=True;self.scale=2.0
            self.lora_a=nn.Linear(base.in_features,rank,bias=False,dtype=torch.float32,device=base.weight.device)
            self.lora_b=nn.Linear(rank,base.out_features,bias=False,dtype=torch.float32,device=base.weight.device)
            nn.init.kaiming_uniform_(self.lora_a.weight,a=math.sqrt(5));nn.init.zeros_(self.lora_b.weight)
        def forward(self,x):
            result=self.base(x)
            return result+(self.lora_b(self.lora_a(x.float()))*self.scale).to(result.dtype) if self.enabled else result
    for p in model.parameters():p.requires_grad_(False)
    names=[]
    for name,module in list(model.named_modules()):
        if name.rsplit('.',1)[-1] in {'q_proj','v_proj'} and isinstance(module,nn.Linear):
            if '.' in name:parent_name,child=name.rsplit('.',1);parent=model.get_submodule(parent_name)
            else:parent=model;child=name
            setattr(parent,child,LoRALinear(module));names.append(name)
    if not names:raise ValueError('No supported q_proj/v_proj linear modules in this architecture')
    return names


def adapter_state(model):return {k:v.detach().cpu() for k,v in model.state_dict().items() if '.lora_a.' in k or '.lora_b.' in k}


def set_adapters(model,enabled):
    for m in model.modules():
        if hasattr(m,'enabled') and hasattr(m,'lora_a'):m.enabled=enabled


def load_adapter(model,state):
    expected=set(adapter_state(model))
    if set(state)!=expected:raise ValueError('Adapter keys do not match model/recipe')
    result=model.load_state_dict(state,strict=False)
    if result.unexpected_keys:raise ValueError('Unexpected adapter weights')


def encode(tokenizer,row,max_length):
    prompt=tokenizer.apply_chat_template([{'role':'user','content':row['instruction']}],tokenize=False,add_generation_prompt=True)
    prefix=tokenizer.encode(prompt,add_special_tokens=False)
    answer=tokenizer.encode(row['response'],add_special_tokens=False)+[tokenizer.eos_token_id]
    # Reserve actual response tokens; never train purely on prompt tokens.
    prefix=prefix[:max_length-2];answer=answer[:max_length-len(prefix)]
    if not answer:raise ValueError('Sequence leaves no response tokens')
    return prefix+answer,[-100]*len(prefix)+answer


def batch(tokenizer,rows,max_length,device):
    import torch
    pairs=[encode(tokenizer,r,max_length) for r in rows];width=max(len(x[0]) for x in pairs)
    ids=[];labels=[];mask=[]
    pad=tokenizer.pad_token_id if tokenizer.pad_token_id is not None else tokenizer.eos_token_id
    for tokens,targets in pairs:
        n=len(tokens);ids.append(tokens+[pad]*(width-n));labels.append(targets+[-100]*(width-n));mask.append([1]*n+[0]*(width-n))
    return {k:torch.tensor(v,device=device) for k,v in {'input_ids':ids,'labels':labels,'attention_mask':mask}.items()}


def heldout_loss(model,tokenizer,rows,length,device):
    import torch
    model.eval();total=0.;tokens=0
    with torch.no_grad():
        for row in rows:
            inputs=batch(tokenizer,[row],length,device);count=int((inputs['labels'][:,1:]!=-100).sum())
            total+=float(model(**inputs).loss.item())*count;tokens+=count
    if not tokens:raise ValueError('Held-out split has no response tokens')
    return total/tokens


def safe_add_correctness(text):
    """Interpret only arithmetic AST; generated Python is NEVER exec/eval'ed."""
    try:
        code=text.split('```python',1)[-1].split('```',1)[0].strip()
        tree=ast.parse(code);fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='add')
        if len(fn.args.args)!=2 or len(fn.body)!=1 or not isinstance(fn.body[0],ast.Return):return False
        def calculate(n,values):
            if isinstance(n,ast.Name):return values[n.id]
            if isinstance(n,ast.Constant) and type(n.value) in {int,float}:return n.value
            if isinstance(n,ast.BinOp) and isinstance(n.op,(ast.Add,ast.Sub,ast.Mult)):
                op={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul}[type(n.op)]
                return op(calculate(n.left,values),calculate(n.right,values))
            raise ValueError('Unsupported generated syntax')
        return all(calculate(fn.body[0].value,dict(zip([a.arg for a in fn.args.args],(a,b))))==a+b for a,b in [(0,0),(1,2),(-5,2),(123,456)])
    except (ValueError,SyntaxError,StopIteration,KeyError,TypeError):return False


def generated_assessment(model,tokenizer,device):
    import torch
    results={}
    for name,prompt in [('arithmetic','Write only Python code defining def add(a, b): that returns their sum.'),
                        ('secure_sql','Write only a Python function lookup_user(conn, name) using a bound SQL parameter to look up a username. No string interpolation.')]:
        value=tokenizer.apply_chat_template([{'role':'user','content':prompt}],tokenize=False,add_generation_prompt=True)
        inputs=tokenizer(value,return_tensors='pt');inputs={k:v.to(device) for k,v in inputs.items()}
        with torch.no_grad():out=model.generate(**inputs,max_new_tokens=96,do_sample=False,pad_token_id=tokenizer.eos_token_id)
        text=tokenizer.decode(out[0,inputs['input_ids'].shape[1]:],skip_special_tokens=True)
        if name=='arithmetic':passed=safe_add_correctness(text)
        else:
            try:
                code=text.split('```python',1)[-1].split('```',1)[0].strip();tree=ast.parse(code)
                calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='execute']
                passed=bool(calls) and all(len(n.args)>=2 and isinstance(n.args[0],ast.Constant) and isinstance(n.args[0].value,str)
                    and ('?' in n.args[0].value or '%s' in n.args[0].value) and isinstance(n.args[1],(ast.Tuple,ast.List)) for n in calls)
            except (ValueError,SyntaxError):passed=False
        results[name]={'passed':passed,'generated_text':text,'method':'Restricted arithmetic AST interpretation' if name=='arithmetic' else 'Static bound-parameter AST check; not a full security certification',
                       'generated_code_executed':False}
    return results
