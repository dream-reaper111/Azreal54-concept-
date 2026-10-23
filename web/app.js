'use strict';
const $ = id => document.getElementById(id);
const node = (tag, text, cls) => { const n=document.createElement(tag); if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n; };
let lastState=null, signature='', polling=false;
let labels={controller:'Coordinator',admin:'Human admin'};
const offensive=new Set(['offense_test','offense_tools','web_red','network_red','rf_red','automotive_red']);
const name=id=>labels[id]||id;
async function api(path,body){
 const response=await fetch(path,{method:body===undefined?'GET':'POST',credentials:'same-origin',headers:body===undefined?{}:{'Content-Type':'application/json','X-Lab-Request':'1'},body:body===undefined?undefined:JSON.stringify(body)});
 const data=await response.json();
 if(!response.ok){if(response.status===401){$('login').hidden=false;$('workspace').hidden=true;}throw new Error(data.error||'Request failed');}return data;
}
const counted=action=>['exercise','simulate','purple_team'].includes(action);
function sharedMode(){
 if(!lastState)return;
 const mode=lastState.shared_modes[$('sharedMode').value];
 for(const o of $('action').options)o.hidden=!mode.actions.includes(o.value);
 $('modeHelp').textContent=mode.workflow||`${mode.label}: execution still requires separate scoped admin approval.`;
 if(!mode.actions.length){$('submitCommand').disabled=true;return;}
 if(!mode.actions.includes($('action').value))$('action').value=mode.actions[0];
 $('submitCommand').disabled=lastState.busy;modes();
}
function modes(){
 const action=$('action').value;
 for(const option of $('role').options)option.disabled=action==='analyze'&&(!lastState?.readiness[option.value]?.classifier_enabled||['offense_test','offense_tools'].includes(option.value));
 if($('role').selectedOptions[0]?.disabled)$('role').value=[...$('role').options].find(o=>!o.disabled)?.value||'';
 $('roundsGroup').hidden=!counted(action);$('textGroup').hidden=counted(action)||['tool_status','collect_sources','hak5_repos'].includes(action);
 $('roleGroup').hidden=!['analyze','code_draft','tools','wireless','radio','incident_review','live_intel','tool_plan','published_exploits','online_brief','council_review','role_hive_review'].includes(action);
 $('languageGroup').hidden=action!=='code_draft';
 const helps={role_hive_review:'Run the selected role’s three fixed public search queries, then planner/critic/chair review. Failures remain visible. Recommendations return to admin; no code application or training.',hak5_repos:'Refresh official Hak5 public-repository metadata into quarantine. No payloads, archives or executable code are fetched.',council_review:'Three role contexts on one shared SLM cross-review your project brief and submit a proposal to the admin. No project files are changed.',online_brief:'Fetch the fixed primary-source APIs into staging, then ask the shared local SLM to plan from source-linked metadata. One pass only; no training or active testing. Collection cooldown applies.',published_exploits:'Search the retained official Exploit-DB CSV metadata. This is a stored snapshot, not a fresh crawl or proof of exploitability. No payload is downloaded or run.',collect_sources:'Run the advisory, research and software metadata collectors (five fixed APIs, two workers, at most once per minute). The operational lane waits for approved inputs. Records enter staging; no training occurs.',live_intel:'Fetch the public CISA KEV catalog now; search locally by vendor, product or CVE. Use * for newest catalog additions. Results include source URL, retrieval timestamp and digest. This does not train weights.',tool_status:'Ask the internal broker which tools are installed. Requires a running container deployment.',tool_plan:'The shared SLM may propose up to three fixed lab recipes. Every step requires admin approval; generation does not execute tools.',exercise:'Synthetic secret-detection cases. The defender checks seven sibling representations.',purple_team:'Red/blue comparison on synthetic fixtures; highlights disagreements and missed cases.',tools:'Search official Kali, Parrot and BlackArch references. No tool is executed.',wireless:'802.11 references and lab planning. No live network tests.',radio:'Software-defined radio references and planning. No RF transmission.',incident_review:'Find incident-response and forensic references for the blue team.',analyze:'Match the input to the learning path. Text models take code or descriptions. Network models take 41 KDD features as a JSON array; RF takes seven RSSI values. Automotive takes named simulation-window features.',simulate:'Abstract in-memory graph only; no malware replication, network connections or files.',literature:'Search public MITRE ATT&CK malware descriptions. Reference material only.',admin_chat:'Shared local SLM. Generated advice is not verified evidence.',team_brief:'The SLM coordinates role capabilities and recent messages. Replies are not fresh independent classifier inferences.',code_draft:'Draft or review Python, C#, Java or C++. Generated code is never automatically executed.'};
 $('actionHelp').textContent=helps[action]||'';
 $('inputLabel').textContent=action==='code_draft'?'Coding task':action==='analyze'?'Model input':'Question / search query';
 $('inputText').maxLength=['council_review','role_hive_review'].includes(action)?3000:action==='analyze'&&$('role').value==='malware_static'?16384:['tools','wireless','radio','literature','incident_review','live_intel','published_exploits'].includes(action)?500:4096;
}
function option(select,value,label){const o=node('option',label);o.value=value;select.append(o);}
function renderGraph(state){
 const svg=$('networkMap');svg.replaceChildren();const NS='http://www.w3.org/2000/svg';
 const make=(tag,attrs,text)=>{const n=document.createElementNS(NS,tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,String(v));if(text!==undefined)n.textContent=text;return n;};
 const recent=new Set(state.messages.slice(-10).flatMap(m=>[m.sender,m.receiver]));
 const count=Math.ceil(state.roles.length/2),width=Math.max(1040,count*135),center=width/2;svg.setAttribute('viewBox',`0 0 ${width} 260`);svg.style.minWidth=width+'px';
 state.roles.forEach((r,i)=>{const top=i<count,j=top?i:i-count,x=55+j*((width-110)/Math.max(1,count-1)),y=top?34:226;const cls=r.id.endsWith('_red')||r.id.startsWith('offense')?'red':'blue';svg.append(make('path',{d:`M ${x} ${top?y+12:y-12} L ${x} ${top?82:178} L ${center} 130`,class:`map-line ${cls} ${recent.has(r.id)?'recent':''}`}));svg.append(make('rect',{x:x-10,y:y-10,width:20,height:20,class:`map-node ${cls}`}));svg.append(make('text',{x,y:top?13:253,'text-anchor':'middle',class:'map-label'},r.name.replace('Malware · ','Malware ')));});
 svg.append(make('rect',{x:center-115,y:109,width:230,height:42,class:'map-hub'}),make('text',{x:center,y:127,'text-anchor':'middle',class:'hub-title'},'LOCAL MESSAGE BUS'),make('text',{x:center,y:141,'text-anchor':'middle',class:'hub-sub'},'STRUCTURED DATA / HUMAN AUTHORITY'));
}
function renderMessages(state){
 const filter=$('filter').value;const messages=state.messages.filter(m=>filter==='all'||m.sender===filter||m.receiver===filter);$('events').replaceChildren();
 if(!messages.length){$('events').append(node('p','NO TRAFFIC YET.\nStart a bounded experiment to connect the dots.','empty'));return;}
 for(const m of messages.slice().reverse()){const d=node('details',undefined,'event'),s=node('summary');s.append(node('span',String(m.sequence).padStart(3,'0'),'seq'),node('span',`${name(m.sender)} → ${name(m.receiver)}`,'route'),node('span',m.kind.replaceAll('_',' '),'event-kind'));d.append(s,node('pre',JSON.stringify(m.payload,null,2)));$('events').append(d);}
}
function button(parent,title,task,error){const b=node('button',title);b.type='button';b.onclick=async()=>{b.disabled=true;try{await task();await refresh();}catch(e){$(error).textContent=e.message;}finally{b.disabled=false;}};parent.append(b);}
function renderApprovals(state){
 $('approvals').replaceChildren();
 for(const r of state.approvals.slice().reverse()){const c=node('div',undefined,'approval');c.append(node('strong',`${name(r.model)} / ${r.section} / ${r.operation}`),node('p',`TARGET: ${r.target} · STATUS: ${r.status} · EXPIRES: ${r.expires_at}`),node('p',r.reason));
 if(r.status==='pending'){
  let confirmation=null;
  if(r.operation==='external_http_headers'){const label=node('label','I confirm authorization for this exact target and HTTP HEAD method.','motion-label');confirmation=node('input');confirmation.type='checkbox';label.prepend(confirmation);c.append(label);}
  for(const [decision,title]of[['approve_plan',r.executable?'Approve one exact test':'Approve plan only'],['reject','Reject']])button(c,title,()=>{if(decision==='approve_plan'&&confirmation&&!confirmation.checked)throw new Error('Confirm target authorization first.');return api('/api/approval/decide',{request_id:r.request_id,decision,...(confirmation&&decision==='approve_plan'?{authorized:true}:{})});},'approvalError');
 }
 if(['approved','approved_plan_only'].includes(r.status)){if(r.executable)button(c,'Run approved recipe',()=>api('/api/approval/execute',{request_id:r.request_id,model:r.model,section:r.section}),'approvalError');button(c,'Revoke',()=>api('/api/approval/decide',{request_id:r.request_id,decision:'revoke'}),'approvalError');}
 $('approvals').append(c);}
}
function renderConsole(state){
 const enabled=Object.values(state.readiness).filter(r=>r.classifier_enabled).length;
 $('readyCount').replaceChildren(document.createTextNode(String(enabled)),node('span','limited classifiers enabled'));
 $('checkpointCount').textContent=`${Object.keys(state.checkpoints).length} loaded .pt files`;
 $('modelSummary').replaceChildren();
 const entries=[['Registered roles',state.roles.length],['Limited classifiers',enabled],['Blocked / pending',state.roles.length-enabled],['Shared coding SLM',state.slm.available?'Present / unqualified':'Not installed'],['Council proposals',state.council_reviews.length]];
 for(const [label,value]of entries){const row=node('div',undefined,'summary-row');row.append(node('strong',label),node('span',String(value),typeof value==='number'&&label==='Blocked / pending'?'pending':''));$('modelSummary').append(row);}
 $('systemFacts').replaceChildren();
 const storage=state.storage||{};const storageValue=storage.available_bytes==null?'Capacity unavailable':`${(storage.available_bytes/1024**3).toFixed(1)} GiB free · ${storage.capacity_status||'unknown'}${storage.writable_for_current_user?'':' · not writable'}`;
 for(const [label,value]of [['Container verification','Not verified'],['Storage',`${storage.configured_root||'unconfigured'} · ${storageValue}`],['Evidence records',state.evidence_summary.records],['Evidence retention',`${state.storage?.retention?.retention_days??'—'} days · admin-confirmed`],['External executor',state.external_runtime_configured?'Configured / unverified':'Not configured'],['Training in collection','None'],['Active command',state.busy?'Running':'Idle'],['Admin approvals',state.approvals.filter(a=>a.status==='pending').length]]){const row=node('div',undefined,'status-fact');row.append(node('dt',label),node('dd',String(value)));$('systemFacts').append(row);}
 $('councilReviews').replaceChildren();
 for(const review of state.council_reviews){const item=node('div',undefined,'council-item');item.append(node('strong',review.status||'Recorded review'),node('p',review.objective||review.id));const link=node('a','Inspect recorded passes ↗');link.href='/api/council?id='+encodeURIComponent(review.id);link.target='_blank';link.rel='noopener';item.append(link);if(review.status==='pending_admin_review'){const note=node('input');note.placeholder='Admin decision note';note.maxLength=1000;item.append(note);for(const [decision,label]of [['accept','Accept proposal only'],['reject','Reject']])button(item,label,()=>api('/api/council/decide',{id:review.id,decision,note:note.value}),'commandError');}$('councilReviews').append(item);}
 if(!state.council_reviews.length)$('councilReviews').append(node('p','No project cross-review has run. Choose Plan → Review council.','empty'));
 if(!$('artworkGrid').children.length)for(const asset of state.brand.assets){const link=node('a',asset.name),img=node('img');img.src=asset.url;img.alt=asset.name;img.loading='lazy';link.href=asset.url;link.target='_blank';link.rel='noopener';link.prepend(img);$('artworkGrid').append(link);}
}
function directiveDefinition(){
 if(!lastState)return;const item=lastState.directives.definitions[$('directiveProfile').value];$('directiveDefinition').replaceChildren(node('p',item.definition),node('p',`Application behavior: ${item.engine_behavior}`));
 $('directiveDefinition').append(node('p',`Reference snapshot retrieved ${item.retrieved_at}; publication date ${item.publication_at||'unknown'}. These are attributed paraphrases, not live definitions.`));
 for(const url of item.sources){const link=node('a',new URL(url).hostname+' definition ↗');link.href=url;link.target='_blank';link.rel='noopener noreferrer';$('directiveDefinition').append(link,document.createTextNode(' '));}
}
function renderDirectives(state){
 const counts={};for(const item of Object.values(state.directives.assignments))counts[item.profile]=(counts[item.profile]||0)+1;
 $('directiveSummary').textContent=Object.entries(counts).map(([key,count])=>`${state.directives.profiles[key].label}: ${count}`).join(' · ');
 directiveDefinition();
}
function renderEvidence(state){
 const summary=state.evidence_summary;
 $('evidenceSummary').textContent=`${summary.records} records · ${summary.retrievals} retrievals · ${summary.datasets} dataset manifests · ${summary.invalidated_datasets} invalidated · retention ${summary.retention_days} days · training performed: no. Near-duplicate matching is a lexical heuristic.`;
 $('evidenceRecords').replaceChildren();
 for(const record of state.evidence_records){
  const c=node('details',undefined,'approval'),meta=record.metadata;
  c.append(node('summary',`${record.status} / ${meta.worker||'unknown worker'} / ${record.source_url}`));
  c.append(node('p',`Collected: ${record.retrieved_at||'unknown'} · Published: ${meta.publication_at||'unknown'} · Event: ${meta.event_at||'unknown'}`));
  c.append(node('p',`License: ${meta.license?.status||'unknown'} · Data provenance: ${meta.synthetic_status||'unknown'} · Intended routes: ${(meta.task_routes||[]).join(', ')||'reference library only'}`));
  c.append(node('p',(meta.limitations||[]).join(' ')));
  const link=node('a','Inspect version history and dataset lineage');link.href='/api/evidence/trace?id='+encodeURIComponent(record.record_id);link.target='_blank';link.rel='noopener';c.append(link);
  if(record.status==='accepted_training'){const label=node('label',' Include this admitted version in the frozen evidence membership','motion-label'),check=node('input');check.type='checkbox';check.className='dataset-member';check.dataset.record=record.record_id;check.dataset.version=record.version_id;label.prepend(check);c.append(label);}
  const note=node('textarea');note.placeholder='Reviewer note: source facts, limitations, or reason for rejection';note.maxLength=1000;note.rows=2;c.append(note);
  const checked={};
  for(const [key,text] of [['provenance_valid','Source provenance reviewed'],['license_permits_use','Verified license permits intended use'],['privacy_reviewed','Privacy and credential review complete']]){const label=node('label',text,'motion-label'),check=node('input');check.type='checkbox';label.prepend(check);c.append(label);checked[key]=check;}
  for(const [decision,title] of [['accept_reference','Accept reference (requires verified license metadata)'],['reject','Reject record'],['quarantine','Keep quarantined']])button(c,title,()=>api('/api/evidence/review',{record_id:record.record_id,version_id:record.version_id,decision,note:note.value,checks:Object.fromEntries(Object.entries(checked).map(([key,check])=>[key,check.checked]))}),'evidenceError');
  const deletion=node('label','Permanently delete content and invalidate dependent manifests','motion-label'),confirm=node('input');confirm.type='checkbox';deletion.prepend(confirm);c.append(deletion);
  button(c,'Delete selected record',()=>{if(!confirm.checked)throw new Error('Confirm permanent deletion first.');return api('/api/evidence/delete',{record_id:record.record_id,reason:note.value,confirmed:true});},'evidenceError');
  $('evidenceRecords').append(c);
 }
 if(!state.evidence_records.length)$('evidenceRecords').append(node('p','No staged records yet. Use Observe → Collect primary sources.'));
}
function artifactParents(){
 const selected=$('artifactParent').value,stage=$('artifactStage').value;$('artifactParentGroup').hidden=stage==='download';$('artifactParent').replaceChildren();
 if(lastState)for(const r of lastState.downloads)if(r.status==='consumed'&&r.model===$('artifactModel').value&&r.tool===$('artifactTool').value&&r.stage===(stage==='extract'?'download':'extract'))option($('artifactParent'),r.request_id,`${r.tool} / ${r.stage} / ${r.request_id}`);
 if([...$('artifactParent').options].some(o=>o.value===selected))$('artifactParent').value=selected;
}
function renderArtifacts(state){
 $('artifactRequests').replaceChildren();artifactParents();
 for(const r of state.downloads.slice().reverse()){const c=node('div',undefined,'approval');c.append(node('strong',`${name(r.model)} / ${r.tool} / ${r.stage}`),node('p',`${r.status} · ${r.repo} @ ${r.revision} · expires ${r.expires_at}`),node('p',r.reason));
 if(r.status==='pending')for(const [decision,title]of[['approve',r.executable?'Approve one stage':'Approve plan only'],['reject','Reject']])button(c,title,()=>api('/api/artifact/decide',{request_id:r.request_id,decision}),'artifactError');
 if(['approved','approved_plan_only'].includes(r.status)){if(r.executable)button(c,`Run approved ${r.stage}`,()=>api('/api/artifact/execute',{request_id:r.request_id,model:r.model}),'artifactError');button(c,'Revoke',()=>api('/api/artifact/decide',{request_id:r.request_id,decision:'revoke'}),'artifactError');}
 if(r.result)c.append(node('pre',JSON.stringify(r.result,null,2)));
 if(r.error)c.append(node('p',r.error,'failed'));
 if(r.status==='consumed'&&r.stage==='download'){const a=node('a','Save retrieved source archive ↗');a.href='/api/artifact/file?id='+encodeURIComponent(r.request_id);a.download='';c.append(a);}
 $('artifactRequests').append(c);}
}
function permissionsMode(){
 for(const o of $('operation').options){o.disabled=o.dataset.section!==$('approvalSection').value||(o.value==='external_http_headers'&&!lastState?.external_runtime_configured)||(o.dataset.runtime==='true'&&!lastState?.runtime_tools_configured);o.hidden=o.disabled;}
 if($('operation').selectedOptions[0]?.disabled)$('operation').value=[...$('operation').options].find(o=>!o.disabled)?.value||'';
 const external=['external_http_headers','published_exploit_validation'].includes($('operation').value);
 const recipe=lastState?.tool_recipes[$('operation').value.replace(/^recipe_/,'')];
 $('permissionHelp').textContent=$('operation').value==='published_exploit_validation'?'Plan only: no exploit executor is implemented. Approval records a reviewable plan, not permission to run arbitrary code.':$('approvalSection').value==='external'&&!lastState?.external_runtime_configured?'External executor is not configured here. Start the container deployment to enable one-use HTTP-header requests.':external?'One HEAD request to an exact public HTTP(S) URL on its default port; no credentials, query parameters or redirects. DNS is checked and pinned at execution.':'Only implemented recipes can run; other operations remain plans.';
 $('requestPermission').disabled=!$('operation').value;
 $('target').placeholder=external?'https://your-authorized-domain.example/path':'Exact target';
 $('target').readOnly=Boolean(recipe);if(recipe)$('target').value=recipe.target;
 const allowed={web_red:'vulnerability',network_red:'vulnerability',rf_red:'radio',automotive_red:'automotive'};
 for(const o of $('approvalModel').options)o.disabled=Boolean((!recipe&&!external&&!offensive.has(o.value))||(!external&&allowed[o.value]&&allowed[o.value]!==$('approvalSection').value));
 if($('approvalModel').selectedOptions[0]?.disabled)$('approvalModel').value=[...$('approvalModel').options].find(o=>!o.disabled)?.value||'';
}

function initialize(state){
 if($('models').children.length)return;
 labels={controller:'Coordinator',admin:'Human admin',...Object.fromEntries(state.roles.map(r=>[r.id,r.name]))};
 state.roles.forEach((r,i)=>{const c=node('article',undefined,'model-card');const readiness=state.readiness[r.id];c.dataset.readiness=readiness?.classifier_status||'unknown';c.title=readiness?.reason||'Readiness unknown';c.append(node('span',String(i+1).padStart(2,'0'),'role-index'),node('span',r.group,`role-kind ${r.group}`),node('h3',r.name),node('p',r.description));const reporting=state.hierarchy.find(h=>h.id===r.id);if(reporting)c.append(node('p',`Level ${reporting.rank} → ${name(reporting.reports_to)}`));const checkpoint=state.checkpoints[r.id];c.append(node('p',checkpoint?`${checkpoint.parameters.toLocaleString()} parameters · ${checkpoint.tensors} tensors`:'No independent checkpoint'));$('models').append(c);option($('role'),r.id,r.name);option($('filter'),r.id,r.name);option($('directiveRole'),r.id,r.name);option($('artifactModel'),r.id,r.name);option($('approvalModel'),r.id,r.name);});
 for(const [id,recipe]of Object.entries(state.tool_recipes)){const o=node('option',`${recipe.tool}: ${recipe.question}`);o.value='recipe_'+id;o.dataset.section=recipe.section;o.dataset.runtime='true';$('operation').prepend(o);}
 for(const [tool,v]of Object.entries(state.curated_tools))option($('artifactTool'),tool,`${tool} / ${v.repo}`);
 $('learning').replaceChildren();
 for(const [id,path]of Object.entries(state.learning_paths)){const row=node('div',undefined,'learning-row');row.append(node('strong',name(id)),node('p',path.training),node('p',`STATUS: ${path.status}`));if(path.missing_coverage)row.append(node('p',path.missing_coverage));const m=state.public_metrics[id];if(m)row.append(node('p',`Executed holdout: ${(100*m.accuracy).toFixed(1)}% accuracy · macro F1 ${m.macro_f1.toFixed(3)} · ${m.test_rows} examples. Dataset scope limits apply.`));$('learning').append(row);}
 permissionsMode();sharedMode();
}
function render(state){
 lastState=state;initialize(state);window.PocPanel?.update(state);window.SetupPanel?.update(state);window.RoleResearchPanel?.update(state);$('connection').textContent=state.busy?'PROCESSING':'LOCAL · CONNECTED';$('submitCommand').disabled=state.busy||$('sharedMode').value==='verify';$('jobState').textContent=state.busy?'Command running':'Idle';
 renderConsole(state);
 $('messageCount').replaceChildren(document.createTextNode(String(state.messages.length)),node('span','visible messages'));$('roleCount').replaceChildren(document.createTextNode(String(state.roles.length).padStart(2,'0')),node('span','registered roles'));
 window.NodeScene?.update(state);renderGraph(state);renderMessages(state);renderEvidence(state);renderDirectives(state);renderApprovals(state);renderArtifacts(state);$('jobs').replaceChildren();
 for(const job of state.jobs.slice().reverse()){const d=node('details',undefined,'result'),s=node('summary');s.append(node('span',job.status,`status ${['failed','partial'].includes(job.status)?'failed':''}`),document.createTextNode(`${job.action.replaceAll('_',' ')} · ${job.id}`));d.append(s,node('pre',JSON.stringify(job.result||{error:job.error||'In progress'},null,2)));$('jobs').append(d);}
 if(!state.jobs.length)$('jobs').append(node('p','NO OBSERVATIONS YET. Choose an operation to begin.','empty'));modes();
}
async function refresh(){if(polling)return;polling=true;try{const state=await api('/api/state');$('login').hidden=true;$('workspace').hidden=false;const next=JSON.stringify(state);if(next!==signature){render(state);signature=next;}}catch(e){if(!$('workspace').hidden)$('connection').textContent='DISCONNECTED';}finally{polling=false;}}
$('loginForm').onsubmit=async e=>{e.preventDefault();$('loginError').textContent='';try{await api('/api/login',{token:$('token').value});$('token').value='';await refresh();}catch(error){$('loginError').textContent=error.message;}};
$('logout').onclick=async()=>{await api('/api/logout',{});$('workspace').hidden=true;$('login').hidden=false;signature='';};
$('sharedMode').onchange=sharedMode;$('action').onchange=modes;$('role').onchange=modes;$('filter').onchange=()=>lastState&&renderMessages(lastState);
$('commandForm').onsubmit=async e=>{e.preventDefault();$('commandError').textContent='';const action=$('action').value,command={action};if(counted(action))command.rounds=Number($('rounds').value);else if(!['tool_status','collect_sources','hak5_repos'].includes(action))command.text=$('inputText').value;if(['analyze','code_draft','tools','wireless','radio','incident_review','live_intel','tool_plan','published_exploits','online_brief','council_review','role_hive_review'].includes(action))command.role=$('role').value;if(action==='code_draft')command.language=$('language').value;try{await api('/api/command',command);await refresh();}catch(error){$('commandError').textContent=error.message;}};
$('approvalSection').onchange=permissionsMode;$('operation').onchange=permissionsMode;
$('approvalForm').onsubmit=async e=>{e.preventDefault();$('approvalError').textContent='';try{await api('/api/approval/request',{operation:$('operation').value,target:$('target').value,model:$('approvalModel').value,section:$('approvalSection').value});await refresh();}catch(error){$('approvalError').textContent=error.message;}};
for(const id of ['artifactTool','artifactStage','artifactModel'])$(id).onchange=artifactParents;
$('artifactForm').onsubmit=async e=>{e.preventDefault();$('artifactError').textContent='';const body={tool:$('artifactTool').value,model:$('artifactModel').value,stage:$('artifactStage').value};if(body.stage!=='download')body.parent_id=$('artifactParent').value;try{await api('/api/artifact/request',body);await refresh();}catch(error){$('artifactError').textContent=error.message;}};
$('inventoryForm').onsubmit=async event=>{event.preventDefault();$('inventoryError').textContent='';try{await api('/api/command',{action:'topology',text:$('inventoryInput').value});await refresh();$('sceneView').value='assets';$('sceneView').onchange();}catch(error){$('inventoryError').textContent=error.message;}};
const clockTick=()=>{$('operatorClock').textContent=new Date().toLocaleTimeString('en-GB',{timeZone:'UTC'})+'Z';};clockTick();setInterval(clockTick,1000);
$('directiveProfile').onchange=directiveDefinition;
$('directiveRole').onchange=()=>{const assignment=lastState?.directives.assignments[$('directiveRole').value];if(assignment){$('directiveProfile').value=assignment.profile;$('directiveObjective').value=assignment.objective;directiveDefinition();}};
$('directiveForm').onsubmit=async event=>{event.preventDefault();try{const result=await api('/api/directives',{role:$('directiveRole').value,profile:$('directiveProfile').value,objective:$('directiveObjective').value});$('directiveResult').textContent=`Assigned to ${result.updated_roles} roles. Execution permissions unchanged. No training occurred.`;await refresh();}catch(error){$('directiveResult').textContent=error.message;}};
$('datasetForm').onsubmit=async event=>{event.preventDefault();$('evidenceError').textContent='';try{const members=[...document.querySelectorAll('.dataset-member:checked')].map(check=>({record_id:check.dataset.record,version_id:check.dataset.version}));await api('/api/evidence/freeze',{name:$('datasetName').value,kind:$('datasetKind').value,members,approved:$('datasetApproval').checked});await refresh();}catch(error){$('evidenceError').textContent=error.message;}};
$('applyRetention').onclick=async()=>{try{if(!$('retentionConfirm').checked)throw new Error('Confirm retention deletion first.');await api('/api/evidence/expire',{confirmed:true});await refresh();}catch(error){$('evidenceError').textContent=error.message;}};
modes();refresh();setInterval(refresh,1500);
