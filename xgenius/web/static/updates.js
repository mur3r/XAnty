'use strict';
const Updates=(()=>{
 let state=null,dialog=null,polling=false,dismissed='',notified='';
 function render(){
  if(!state)return;
  const banner=$('#update-banner'),release=state.release;
  banner.classList.toggle('hidden',!release||dismissed===release.version);
  if(release)banner.innerHTML=`${I('download',18)}<div class="spacer"><strong>${t('update_available',{version:esc(release.version)})}</strong><p>${t(state.status==='ready'?'update_ready':'update_banner_text')}</p></div><button class="btn primary small" data-update-open>${t(state.status==='ready'?'update_install':'update_details')}</button><button class="icon-button" data-update-dismiss title="${t('close')}">${I('x',16)}</button>`;
  if(dialog?.el.isConnected){
   const status=state.status,downloading=status==='downloading',busy=downloading||status==='checking'||status==='installing';
   const percent=release?Math.min(100,Math.round(state.downloaded/release.size*100)):0;
   $('[data-update-body]',dialog.body).innerHTML=`<p>${t('update_current',{version:esc(state.current_version)})}</p>${!state.configured?`<div class="notice">${t('update_not_configured')}</div>`:''}${state.error?`<div class="notice error" role="alert">${esc(I18N.error(state.error))}</div>`:''}${status==='current'?`<div class="notice success">${t('update_current_ok')}</div>`:''}${release?`<h3>${t('update_available',{version:esc(release.version)})}</h3><pre class="release-notes">${esc(release.notes||t('update_no_notes'))}</pre><a href="${esc(release.page_url)}" target="_blank" rel="noopener noreferrer">${t('update_github')}</a>${!state.can_install?`<div class="notice">${t('update_manual_only')}</div>`:''}`:''}${downloading?`<div class="progress-track"><i style="width:${percent}%"></i></div><p role="status">${t('update_downloading',{n:percent})}</p>`:''}${status==='ready'?`<div class="notice success">${t('update_ready')}</div><p>${t('update_close_profiles')}</p>`:''}${status==='installing'?`<div class="notice">${t('update_restarting')}</div>`:''}<div class="update-actions"><button class="btn" data-update-check ${busy||status==='ready'?'disabled':''}>${t('update_check')}</button>${release&&state.can_install?`<button class="btn primary" data-update-action ${busy?'disabled':''}>${busy?'<span class="spinner"></span>':''}${t(status==='ready'?'update_install':downloading?'update_loading':'update_download')}</button>`:''}</div>`;
  }
 }
 async function accept(data){state=data;render();if(data.release&&notified!==data.release.version){notified=data.release.version;toast(t('update_available',{version:data.release.version}),'info',12000,{label:t('update_details'),run:show});}}
 async function check(automatic=false){try{await accept(await api('POST','/api/updates/check',{automatic}));}catch(error){if(!automatic)toast(error.message,'error');}}
 async function show(){try{await accept(await api('GET','/api/updates'));if(dialog?.el.isConnected){render();return;}dialog=Dialogs.open({title:'updates',icon:'download',wide:true,body:'<div data-update-body></div>',buttons:[{label:'close',onClick:d=>d.close()}]});render();}catch(error){toast(error.message,'error');}}
 async function act(){try{state=await api('POST',state.status==='ready'?'/api/updates/install':'/api/updates/download',{});render();}catch(error){toast(error.message,'error',12000);}}
 async function poll(){if(polling||state?.status!=='downloading')return;polling=true;try{await accept(await api('GET','/api/updates'));}catch{}finally{polling=false;}}
 function bind(){document.addEventListener('click',event=>{if(event.target.closest('[data-update-open]'))show();if(event.target.closest('[data-update-dismiss]')){dismissed=state.release?.version||'';render();}const checkButton=event.target.closest('[data-update-check]');if(checkButton){checkButton.disabled=true;check().finally(render);}const action=event.target.closest('[data-update-action]');if(action){action.disabled=true;act();}});document.addEventListener('languagechange',render);}
 document.addEventListener('DOMContentLoaded',async()=>{bind();try{await accept(await api('GET','/api/updates'));const result=state.install_result;if(result&&!result.ok)toast(t('update_previous_failed')+'\n'+result.error,'error',20000);await check(true);}catch{}setInterval(poll,1200);setInterval(()=>check(true),60*60*1000);});
 return {show};
})();
