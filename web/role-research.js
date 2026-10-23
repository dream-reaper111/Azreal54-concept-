'use strict';
(() => {
 const panel=document.createElement('section');panel.id='roleResearchPanel';panel.className='panel';
 panel.innerHTML='<div class="section-heading"><h2>ROLE RESEARCH / RED & BLUE CORPORA</h2><span id="roleResearchStatus"></span></div><p>Each role has authored queries for Stack Overflow, Security Stack Exchange and GitHub repository metadata. Collected records enter quarantine. Repository matches are tool proposals for review.</p><label>Research role<select id="roleSearchRole"></select></label><pre id="roleSearchQueries"></pre><button id="roleSearchCollect">Collect public sources for this role</button> <button id="roleDatasetsBuild" class="quiet">Build red / blue reference datasets</button><p id="roleDatasetStatus"></p><a id="roleDatasetDownload" hidden>Download selected role corpus</a><p id="roleSearchError" role="alert"></p><details><summary>Restricted search operators / vulnerability-review roles</summary><p>Templates use an exact admin-assigned domain or owner/repository. They generate search links for the selected role; opening a link does not establish a vulnerability.</p><form id="dorkPolicyForm"><label>Eligible role<select id="dorkRole"></select></label><label>Scope type<select id="dorkScopeType"><option value="domain">Domain</option><option value="repository">Owner/repository</option></select></label><label>Exact authorized scope<input id="dorkScope" maxlength="253" required placeholder="your-authorized-domain.example"></label><label class="motion-label"><input id="dorkEnabled" type="checkbox"> Enable templates for this role and scope</label><label class="motion-label"><input id="dorkConfirmed" type="checkbox" required> I confirm the scope and assignment for this role.</label><button>Save role assignment</button></form><button id="dorkShow" class="quiet">Show this role’s scoped templates</button><div id="dorkResults"></div><p id="dorkError" role="alert"></p></details>';
 document.getElementById('inventoryPanel').before(panel);
 const pitches=document.createElement('div');pitches.id='repositoryPitches';panel.querySelector('details').before(pitches);
 const byId=id=>document.getElementById(id);let latest=null;
 function selection(){
  if(!latest)return;const role=byId('roleSearchRole').value,profile=latest.profiles[role];if(!profile)return;
  byId('roleSearchQueries').textContent=profile.providers.map(provider=>`${provider.provider}: ${provider.query}`).join('\n');
  const dataset=latest.datasets.roles?.[role],link=byId('roleDatasetDownload');
  byId('roleDatasetStatus').textContent=dataset?`${dataset.lane.toUpperCase()} reference corpus · ${dataset.records} records · training admission required`:'No reference dataset has been built for this role.';
  link.hidden=!dataset;link.href='/api/research/dataset?role='+encodeURIComponent(role);
  pitches.replaceChildren();
  for(const proposal of latest.repository_pitches.pitches.filter(item=>item.roles.includes(role))){
   const item=document.createElement('div'),link=document.createElement('a'),text=document.createElement('p'),review=document.createElement('button');
   item.className='council-item';link.textContent=proposal.repository+' · proposal only';link.href=proposal.url;link.target='_blank';link.rel='noopener noreferrer';text.textContent=proposal.fit;
   review.textContent='Ask hive to review this tool proposal';review.disabled=Boolean(lastState?.busy);
   review.onclick=async()=>{try{await api('/api/command',{action:'council_review',role,text:`Review this tool proposal for the selected role: ${proposal.repository}. Source: ${proposal.url}. Proposed fit: ${proposal.fit} Identify missing license, maintenance, dependency and lab-scope checks. Source and code were not installed. Return a proposal to admin.`});await refresh();}catch(error){byId('roleSearchError').textContent=error.message;}};
   item.append(link,text,review);pitches.append(item);
  }
 }
 function policy(){
  if(!latest)return;const assignment=latest.dork_assignments[byId('dorkRole').value];
  byId('dorkEnabled').checked=Boolean(assignment?.enabled);byId('dorkScope').value=assignment?.scope||'';
  byId('dorkScopeType').value=assignment?.scope_type||'domain';byId('dorkConfirmed').checked=false;byId('dorkResults').replaceChildren();
 }
 byId('roleSearchRole').onchange=selection;byId('dorkRole').onchange=policy;
 byId('roleSearchCollect').onclick=async()=>{
  byId('roleSearchError').textContent='';
  try{await api('/api/command',{action:'role_collect',role:byId('roleSearchRole').value});await refresh();}catch(error){byId('roleSearchError').textContent=error.message;}
 };
 byId('roleDatasetsBuild').onclick=async()=>{
  byId('roleSearchError').textContent='';
  try{await api('/api/command',{action:'role_datasets'});await refresh();}catch(error){byId('roleSearchError').textContent=error.message;}
 };
 byId('dorkPolicyForm').onsubmit=async event=>{
  event.preventDefault();byId('dorkError').textContent='';
  try{await api('/api/research/dorks',{role:byId('dorkRole').value,enabled:byId('dorkEnabled').checked,scope_type:byId('dorkScopeType').value,scope:byId('dorkScope').value,confirmed:byId('dorkConfirmed').checked});byId('dorkConfirmed').checked=false;await refresh();}catch(error){byId('dorkError').textContent=error.message;}
 };
 byId('dorkShow').onclick=async()=>{
  byId('dorkError').textContent='';
  try{const result=await api('/api/research/dorks?role='+encodeURIComponent(byId('dorkRole').value)),list=byId('dorkResults');list.replaceChildren();for(const item of result.templates){const p=document.createElement('p'),link=document.createElement('a');link.textContent=item.query;link.href=item.search_url;link.target='_blank';link.rel='noopener noreferrer';p.append(link);list.append(p);}}
  catch(error){byId('dorkError').textContent=error.message;}
 };
 window.RoleResearchPanel={update(state){
  latest=state.role_research;if(!latest)return;
  if(!byId('roleSearchRole').options.length){
   for(const [role,profile]of Object.entries(latest.profiles)){const option=document.createElement('option');option.value=role;option.textContent=profile.name;byId('roleSearchRole').append(option);}
   for(const role of latest.dork_eligible_roles){const option=document.createElement('option');option.value=role;option.textContent=latest.profiles[role]?.name||role;byId('dorkRole').append(option);}
   byId('roleSearchRole').value='web_red';byId('dorkRole').value='web_red';policy();
  }
  byId('roleResearchStatus').textContent=`${Object.keys(latest.profiles).length} role profiles · ${Object.keys(latest.datasets.roles||{}).length} corpora`;
  byId('roleSearchCollect').disabled=state.busy;byId('roleDatasetsBuild').disabled=state.busy;selection();
 }};
 if(typeof lastState!=='undefined'&&lastState)window.RoleResearchPanel.update(lastState);
})();
