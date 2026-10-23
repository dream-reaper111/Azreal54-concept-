'use strict';
(() => {
 const panel=document.createElement('section');panel.id='setupPanel';panel.className='panel';
 panel.innerHTML='<div class="section-heading"><h2>INSTALL / BUILD CONTROL</h2><span id="setupRunnerState">Checking host runner</span></div><p>Run this command from the project folder in your admin terminal. It installs pinned dependencies, prepares missing SLM weights, builds the images, starts the lab, verifies its APIs, performs one SLM inference and checks role-scoped source access.</p><pre id="setupCommand">bash install.sh --runtime auto --install --build --start --verify --verify-slm --verify-providers --serve</pre><button id="setupCopy" class="quiet" type="button">Copy full setup command</button><p class="help">The installer prefers functional rootless Podman and falls back to Docker Compose. The host runner handles the fixed install request; the dashboard receives no container socket or arbitrary host command access.</p><form id="setupForm"><label class="motion-label"><input id="setupConfirmed" type="checkbox" required> Install the project dependencies, build the images, start the services and run the fixed health/inference checks.</label><button id="setupRequest" disabled>Install, build & verify</button></form><p id="setupError" role="alert"></p><div id="setupRuns"></div>';
 document.getElementById('evidencePanel').before(panel);
 const byId=id=>document.getElementById(id);
 byId('setupCopy').onclick=async()=>{
  try{await navigator.clipboard.writeText(byId('setupCommand').textContent);byId('setupError').textContent='Setup command copied. Run it from your project folder.';}
  catch{byId('setupError').textContent='Copy the displayed command and run it from your project folder.';}
 };
 byId('setupForm').onsubmit=async event=>{
  event.preventDefault();byId('setupError').textContent='';
  try{await api('/api/install/request',{operation:'install_and_build',confirmed:byId('setupConfirmed').checked});byId('setupConfirmed').checked=false;await refresh();}
  catch(error){byId('setupError').textContent=error.message;}
 };
 window.SetupPanel={update(state){
  const setup=state.installation;if(!setup)return;
  byId('setupCommand').textContent=setup.command;
  byId('setupRunnerState').textContent=setup.runner_active?'HOST RUNNER ONLINE':'HOST RUNNER NOT CONNECTED';
  byId('setupRequest').disabled=!setup.runner_active||setup.runs.some(run=>['running','queued'].includes(run.status));
  const runs=byId('setupRuns');runs.replaceChildren();
  for(const run of setup.runs){
   const item=document.createElement('div'),title=document.createElement('strong'),description=document.createElement('p'),link=document.createElement('a');
   item.className='council-item';title.textContent=run.status.toUpperCase();description.textContent=`${run.requested_at} · ${run.operation}${run.reason?' · '+run.reason:''}`;
   link.href='/api/install?id='+encodeURIComponent(run.id);link.textContent='Inspect status and log tail';link.target='_blank';link.rel='noopener';item.append(title,description,link);runs.append(item);
  }
  if(!setup.runs.length){const p=document.createElement('p');p.textContent='No installation has been requested from this dashboard.';runs.append(p);}
 }};
 if(typeof lastState!=='undefined'&&lastState)window.SetupPanel.update(lastState);
})();
