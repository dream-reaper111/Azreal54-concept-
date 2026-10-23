'use strict';
(() => {
 const panel=document.createElement('details');panel.id='pocPanel';panel.className='panel';
 panel.innerHTML='<summary>Red / Blue PoC candidates · idle trainer</summary><p>Queue two small candidate classifiers using admitted lab observations: recorded reproduction outcomes and verified mitigation outcomes. Candidate weights stay separate from registered roles.</p><p id="pocStatus" role="status"></p><p id="idleTrainerStatus" role="status"></p><pre id="pocContract"></pre><form id="pocTrainForm"><label>Training manifest ID<input id="pocTrain" pattern="[a-f0-9]{64}" maxlength="64" required></label><label>Validation manifest ID<input id="pocValidation" pattern="[a-f0-9]{64}" maxlength="64" required></label><label>Test manifest ID<input id="pocTest" pattern="[a-f0-9]{64}" maxlength="64" required></label><label class="motion-label"><input id="pocConfirm" type="checkbox" required> I approve training isolated candidates from these admitted, frozen observations.</label><button id="pocTrainButton">Queue for idle training</button></form><p class="help">The background worker waits until the shared inference/command lock is free, uses the UUID-aware GPU path when available, and falls back to CPU. It never starts without this approval, does not resume jobs after restart, and runs two bounded 60-step classifiers. Freeze the training split as Training and both holdouts as Evaluation. Record identities, duplicate clusters and feature vectors may not cross splits.</p><form id="pocPredictForm"><label>Six feature values as JSON<textarea id="pocFeatures" rows="3" maxlength="1000" required placeholder="Supply each named feature as a number from 0 through 1."></textarea></label><button id="pocPredictButton" disabled>Estimate both recorded outcomes</button></form><div id="pocMetrics"></div><p id="pocError" role="alert"></p>';
 document.getElementById('evidencePanel').after(panel);
 const byId=id=>document.getElementById(id);
 const error=message=>{byId('pocError').textContent=message;};
 byId('pocTrainForm').onsubmit=async event=>{
  event.preventDefault();error('');
  const data={confirmed:byId('pocConfirm').checked,datasets:{train:byId('pocTrain').value,validation:byId('pocValidation').value,test:byId('pocTest').value}};
  try{await api('/api/command',{action:'train_poc',text:JSON.stringify(data)});byId('pocConfirm').checked=false;await refresh();}catch(e){error(e.message);}
 };
 byId('pocPredictForm').onsubmit=async event=>{
  event.preventDefault();error('');
  try{const features=JSON.parse(byId('pocFeatures').value);await api('/api/command',{action:'poc_predict',text:JSON.stringify(features)});await refresh();}catch(e){error(e.message);}
 };
 const spread=document.createElement('form');spread.id='spreadForm';
 spread.innerHTML='<h3>Spread / containment what-if model</h3><p class="help">Uses the inventory above. Every supplied link, including a hypothesis, is assumed traversable. This models reachability only.</p><label>Contained node IDs, separated by commas<input id="containedIds" maxlength="2000"></label><label>Steps (1–20)<input id="spreadSteps" type="number" min="1" max="20" value="5" required></label><button>Compare red paths with blue containment</button><p id="spreadError" role="alert"></p>';
 byId('inventoryForm').after(spread);
 spread.onsubmit=async event=>{
  event.preventDefault();byId('spreadError').textContent='';
  try{const data={inventory:JSON.parse(byId('inventoryInput').value),contained:byId('containedIds').value.split(',').map(x=>x.trim()).filter(Boolean),steps:Number(byId('spreadSteps').value)};await api('/api/command',{action:'spread_model',text:JSON.stringify(data)});await refresh();}catch(e){byId('spreadError').textContent=e.message;}
 };
 const libraries=document.createElement('details');libraries.id='researchLibraryPanel';libraries.className='panel';
 libraries.innerHTML='<summary>Python research libraries · availability and supplied-evidence analysis</summary><p>Offline analysis helpers matched to the specialist roles. Installed versions are measured in this environment; configured versions are the project dependency pins.</p><div class="graph-scroll"><table><thead><tr><th>Library</th><th>Installed / configured</th><th>Purpose / roles</th></tr></thead><tbody id="researchLibraryRows"></tbody></table></div><form id="researchInspectForm"><label>Evidence type<select id="researchInspectKind"><option value="html">HTML reference text / Beautiful Soup</option><option value="pcap">PCAP packet metadata / Scapy</option><option value="dns">DNS wire message / dnspython</option><option value="disassembly">Instruction bytes / Capstone</option><option value="pe">Windows PE headers / pefile</option><option value="elf">ELF headers / pyelftools</option><option value="yara">Signature matching / YARA</option><option value="xml">XML / defusedxml</option><option value="certificate">PEM certificate / cryptography</option></select></label><label>Supplied file (at most 15,000 bytes)<input id="researchInspectFile" type="file"></label><label>Or supplied text<textarea id="researchInspectText" rows="3" maxlength="15000" placeholder="Paste HTML, XML, a PEM certificate, or text for signature matching."></textarea></label><label>Disassembly architecture<select id="researchArchitecture"><option value="x86_64">x86-64</option><option value="x86">x86-32</option><option value="arm64">ARM64</option></select></label><label>YARA rules (for signature matching)<textarea id="researchYaraRules" rows="3" maxlength="4000"></textarea></label><button id="researchInspectButton">Analyze supplied bytes</button><p class="help">Files are parsed as data. These helpers do not sniff interfaces, contact endpoints, run a binary or scan host processes. Results appear in the activity panel.</p><p id="researchInspectError" role="alert"></p></form>';
 panel.after(libraries);
 byId('researchInspectForm').onsubmit=async event=>{
  event.preventDefault();byId('researchInspectError').textContent='';
  try{
   const file=byId('researchInspectFile').files[0];
   if(file&&file.size>15000)throw new Error('Choose a file of at most 15,000 bytes.');
   const bytes=file?new Uint8Array(await file.arrayBuffer()):new TextEncoder().encode(byId('researchInspectText').value);
   if(!bytes.length||bytes.length>15000)throw new Error('Supply 1 through 15,000 bytes.');
   const data={kind:byId('researchInspectKind').value,data_base64:btoa(Array.from(bytes,b=>String.fromCharCode(b)).join(''))};
   if(data.kind==='disassembly')data.architecture=byId('researchArchitecture').value;
   if(data.kind==='yara')data.rules=byId('researchYaraRules').value;
   await api('/api/command',{action:'research_inspect',text:JSON.stringify(data)});await refresh();
  }catch(e){byId('researchInspectError').textContent=e.message;}
 };
 window.PocPanel={update(state){
  const status=state.poc_training;if(!status)return;
  byId('pocStatus').textContent=`STATUS: ${status.status.replaceAll('_',' ')} · promotion: disabled`;
  const idle=state.idle_trainer||{};
  byId('idleTrainerStatus').textContent=`IDLE TRAINER: ${idle.status||'unavailable'} · ${idle.queued_jobs||0} queued · active job ${idle.active_job||'none'} · worker ${idle.worker_ready?'ready':'unavailable'} · GPU preferred with CPU fallback`;
  byId('pocContract').textContent=`Task: ${status.task}\nSchema: ${status.schema}\nFeatures: ${status.features.join(', ')}\nLabels: reproduced, mitigation_verified`;
  byId('pocTrainButton').disabled=state.busy;byId('pocPredictButton').disabled=state.busy||status.status!=='candidate';
  const metrics=byId('pocMetrics');metrics.replaceChildren();
  for(const [role,model]of Object.entries(status.models||{})){const p=document.createElement('p');p.textContent=`${role}: held-out accuracy ${(model.accuracy*100).toFixed(1)}%, macro F1 ${model.macro_f1.toFixed(3)}, majority baseline ${(model.majority_baseline_accuracy*100).toFixed(1)}%. Scope: supplied lab observations.`;metrics.append(p);}
  const rows=byId('researchLibraryRows');rows.replaceChildren();
  for(const item of state.research_libraries?.libraries||[]){
   const row=document.createElement('tr'),label=document.createElement('td'),version=document.createElement('td'),purpose=document.createElement('td'),link=document.createElement('a');
   link.textContent=item.package;link.href=item.documentation;link.target='_blank';link.rel='noopener noreferrer';label.append(link);
   version.textContent=`${item.available?item.installed_version:'Not installed'} / ${item.version}`;
   purpose.textContent=`${item.purpose}. Roles: ${item.role_examples.join(', ')}`;row.append(label,version,purpose);rows.append(row);
  }
  byId('researchInspectButton').disabled=state.busy;
 }};
 if(typeof lastState!=='undefined'&&lastState)window.PocPanel.update(lastState);
})();
