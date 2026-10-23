'use strict';
(() => {
 const canvas=document.getElementById('roleScene'),ctx=canvas.getContext('2d'),rotate=document.getElementById('sceneRotate'),slider=document.getElementById('sceneTime'),view=document.getElementById('sceneView');
 let state=null,yaw=.32,pitch=-.15,moving=false,lastFrame=0,frame=0,drag=null,reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
 function latestJob(action){return state?.jobs.slice().reverse().find(j=>j.status==='completed'&&j.action===action&&j.result?.nodes);}
 function spreadJob(){return state?.jobs.slice().reverse().find(j=>j.status==='completed'&&j.action==='spread_model'&&Array.isArray(j.result?.timeline));}
 function rangeMax(){
  if(!state)return 0;
  if(view.value==='roles')return state.messages.length;
  if(view.value==='spread')return Math.max(0,(spreadJob()?.result.timeline.length||1)-1);
  return 0;
 }
 function syncRange(followEnd=false){const max=rangeMax();slider.max=String(max);if(followEnd||Number(slider.value)>max)slider.value=String(max);}
 function content(){
  if(view.value==='assets'){
   const job=latestJob('topology'),result=job?.result;
   return result?{nodes:result.nodes.map(n=>({id:n.id,name:n.label,enabled:true})),links:result.links,kind:'assets'}:{nodes:[],links:[],kind:'assets'};
  }
  if(view.value==='spread'){
   const result=spreadJob()?.result;
   if(!result)return {nodes:[],links:[],kind:'spread',timeline:[]};
   const index=Math.min(Number(slider.value),result.timeline.length-1),step=result.timeline[index];
   const red=new Set(step.red_reachable),blue=new Set(step.blue_reachable),contained=new Set(result.contained);
   return {nodes:result.nodes.map(n=>({id:n.id,name:n.label,state:contained.has(n.id)?'contained':red.has(n.id)?(blue.has(n.id)?'both':'red_only'):'unreached'})),
    links:result.links,kind:'spread',step:step.step,redCount:red.size,blueCount:blue.size,
    redOnlyCount:[...red].filter(id=>!blue.has(id)).length,containedCount:contained.size};
  }
  const count=Number(slider.value);
  return {nodes:state.roles.map(r=>({id:r.id,name:r.name,enabled:state.readiness[r.id]?.classifier_enabled})),links:state.messages.slice(0,count).slice(-40).map(m=>({source:m.sender,target:m.receiver,status:'recorded'})),kind:'roles'};
 }
 function draw(){
  if(!state||canvas.clientWidth===0)return;
  const width=canvas.clientWidth,height=canvas.clientHeight||174,dpr=Math.min(devicePixelRatio||1,2),data=content();
  if(canvas.width!==Math.round(width*dpr)||canvas.height!==Math.round(height*dpr)){canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);}
  ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,width,height);
  if(!data.nodes.length){ctx.font='11px sans-serif';ctx.fillStyle='#91a9b1';ctx.textAlign='center';ctx.fillText('No authorized inventory has been analyzed.',width/2,height/2);ctx.textAlign='left';return;}
  const radiusX=Math.min(width*.34,height*.9),radiusY=height*.39,points=new Map(),count=data.nodes.length;
  data.nodes.forEach((role,i)=>{
   const y=1-2*(i+.5)/count,r=Math.sqrt(1-y*y),a=i*2.399963229728653;
   const x=Math.cos(a)*r,z=Math.sin(a)*r,rx=x*Math.cos(yaw)+z*Math.sin(yaw),rz=-x*Math.sin(yaw)+z*Math.cos(yaw);
   const ry=y*Math.cos(pitch)-rz*Math.sin(pitch),depth=y*Math.sin(pitch)+rz*Math.cos(pitch),scale=3/(3-depth);
   points.set(role.id,{role,x:width/2+rx*radiusX*scale,y:height/2+ry*radiusY*scale,depth,scale});
  });
  if(data.kind==='roles')points.set('controller',{x:width/2,y:height/2,depth:0,scale:1});
  for(const link of data.links){
   const a=points.get(link.source),b=points.get(link.target);if(!a||!b)continue;
   ctx.strokeStyle=link.status==='hypothesis'?'#b8775b':'#708e99';ctx.globalAlpha=.5;ctx.setLineDash(link.status==='hypothesis'?[3,3]:[]);ctx.lineWidth=.8;ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();
  }ctx.setLineDash([]);ctx.globalAlpha=1;
  [...points.values()].filter(p=>p.role).sort((a,b)=>a.depth-b.depth).forEach(p=>{
   const colors={both:'#d6a54b',red_only:'#cf5945',contained:'#56a9bf',unreached:'#737f84'};
   ctx.fillStyle=data.kind==='spread'?colors[p.role.state]:(p.role.enabled?'#7daaa1':'#b17864');ctx.globalAlpha=.45+(p.depth+1)*.25;
   ctx.beginPath();ctx.arc(p.x,p.y,2.5*p.scale,0,Math.PI*2);ctx.fill();
  });ctx.globalAlpha=1;
  // Labels are a readable subset; all identities remain in the accessible roster.
  const occupied=data.kind==='roles'?[{x:width/2-6,y:height/2-10,w:110,h:22}]:[];
  ctx.font='10px sans-serif';ctx.fillStyle='#b2c3c9';
  [...points.values()].filter(p=>p.role&&p.depth>.3).sort((a,b)=>b.depth-a.depth).forEach(p=>{
   if(width<=340||occupied.length>=8)return;
   const text=p.role.name.slice(0,24),box={x:p.x+7,y:p.y-14,w:ctx.measureText(text).width+4,h:14};
   if(box.x+box.w>width-4||box.y<4||box.y+box.h>height-4||occupied.some(b=>box.x<b.x+b.w&&box.x+box.w>b.x&&box.y<b.y+b.h&&box.y+box.h>b.y))return;
   ctx.fillText(text,box.x,box.y+10);occupied.push(box);
  });
  if(data.kind==='roles'){ctx.fillStyle='#c54d38';ctx.fillRect(width/2-4,height/2-4,8,8);ctx.font='9px sans-serif';ctx.fillStyle='#cddbe0';ctx.fillText('COORDINATOR',width/2+11,height/2+3);}
  if(data.kind==='spread'){
   ctx.font='8px sans-serif';ctx.fillStyle='#d6a54b';ctx.fillText('AMBER BOTH',8,13);ctx.fillStyle='#cf5945';ctx.fillText('RED ONLY',86,13);ctx.fillStyle='#56a9bf';ctx.fillText('TEAL CONTAINED',151,13);ctx.fillStyle='#9ba9ad';ctx.fillText('GREY UNREACHED',260,13);
   canvas.setAttribute('aria-label',`Reachability what-if at step ${data.step}: ${data.redCount} red reachable, ${data.blueCount} blue reachable, ${data.containedCount} contained. Simulated graph only; no propagation.`);
  }else if(data.kind==='assets')canvas.setAttribute('aria-label','Three-dimensional view of caller-supplied inventory relationships. No live telemetry.');
  else canvas.setAttribute('aria-label','Interactive three-dimensional map of registered roles. Connections represent retained messages only.');
 }
 function labels(){
  if(!state)return;syncRange();const count=Number(slider.value),last=state.messages[count-1],spread=content();slider.disabled=rangeMax()===0;
  if(view.value==='assets')document.getElementById('sceneTimeLabel').textContent='Inventory snapshot · no temporal telemetry';
  else if(view.value==='spread')document.getElementById('sceneTimeLabel').textContent=spread.timeline.length?`What-if step ${spread.step} · simulated`:'No completed spread simulation';
  else document.getElementById('sceneTimeLabel').textContent=last?`#${last.sequence} · ${new Date(last.at).toISOString().slice(11,19)} UTC`:'No recorded messages selected';
  if(view.value==='assets')document.getElementById('sceneDescription').textContent='Layout shows caller-supplied relationships. Dashed links are hypotheses; this snapshot has no temporal telemetry and no propagation occurs.';
  else if(view.value==='spread')document.getElementById('sceneDescription').textContent=spread.timeline.length?`Simulated step ${spread.step}: red reachability ${spread.redCount} · blue after containment ${spread.blueCount} · red-only ${spread.redOnlyCount} · contained ${spread.containedCount}. This is supplied-graph reachability, not infection, exploitability or actual containment.`:'Run a bounded spread / containment what-if using the supplied inventory. The simulation uses graph relationships only.';
  else document.getElementById('sceneDescription').textContent=`${state.roles.length} role identities · ${count} of ${state.messages.length} retained events. Time is the fourth dimension; checkpoint activity is not measured.`;
 }
 function tick(time){frame=0;if(!moving||reduced||document.hidden)return;if(time-lastFrame>33){yaw+=.003;draw();lastFrame=time;}frame=requestAnimationFrame(tick);}
 function motion(value){reduced=value;rotate.disabled=reduced;rotate.title=reduced?'Disable reduced motion to rotate':'Rotate recorded layout';if(reduced){moving=false;rotate.setAttribute('aria-pressed','false');rotate.textContent='Rotate scene';}if(frame)cancelAnimationFrame(frame);frame=0;draw();}
 rotate.onclick=()=>{if(reduced)return;moving=!moving;rotate.setAttribute('aria-pressed',String(moving));rotate.textContent=moving?'Pause scene':'Rotate scene';if(moving&&!frame)frame=requestAnimationFrame(tick);};
 slider.oninput=()=>{labels();draw();};view.onchange=()=>{syncRange(true);labels();draw();};
 canvas.addEventListener('pointerdown',event=>{drag={x:event.clientX,y:event.clientY};canvas.setPointerCapture(event.pointerId);});
 canvas.addEventListener('pointermove',event=>{if(!drag||reduced)return;yaw+=(event.clientX-drag.x)*.006;pitch=Math.max(-1,Math.min(1,pitch+(event.clientY-drag.y)*.006));drag={x:event.clientX,y:event.clientY};draw();});
 canvas.addEventListener('pointerup',()=>{drag=null;});canvas.addEventListener('pointercancel',()=>{drag=null;});
 canvas.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)||reduced)return;event.preventDefault();yaw+=event.key==='ArrowLeft'?-.1:event.key==='ArrowRight'?.1:0;pitch+=event.key==='ArrowUp'?-.1:event.key==='ArrowDown'?.1:0;draw();});
 new ResizeObserver(draw).observe(canvas);document.addEventListener('visibilitychange',()=>{if(!document.hidden&&moving&&!reduced&&!frame)frame=requestAnimationFrame(tick);});
 window.NodeScene={update(next){const follow=Number(slider.value)===Number(slider.max);state=next;syncRange(follow);labels();draw();},reduceMotion:motion};
 const picker=document.getElementById('artTheme'),toggle=document.getElementById('reduceMotion');toggle.checked=reduced;document.body.dataset.art=picker.value||'azrael';picker.onchange=()=>{document.body.dataset.art=picker.value;};
 toggle.onchange=()=>{document.body.classList.toggle('reduced-motion',toggle.checked);motion(toggle.checked);};if(reduced)document.body.classList.add('reduced-motion');motion(reduced);
 matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change',event=>{toggle.checked=event.matches;toggle.onchange();});
 const visual=document.querySelector('.login-visual');visual.addEventListener('pointermove',event=>{if(reduced)return;const box=visual.getBoundingClientRect();visual.style.setProperty('--tilt-y',((event.clientX-box.left)/box.width*5-2.5)+'deg');visual.style.setProperty('--tilt-x',(-(event.clientY-box.top)/box.height*5+2.5)+'deg');});visual.addEventListener('pointerleave',()=>{visual.style.setProperty('--tilt-y','0deg');visual.style.setProperty('--tilt-x','0deg');});
})();
