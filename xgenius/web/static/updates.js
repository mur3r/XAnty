'use strict';
const Updates=(()=>{
 let state=null,dialog=null,notesDialog=null,shownVersion='',polling=false,dismissed='',notified='';
 function notesHTML(notes){
  let html='',list='',paragraph=[];
  const flush=()=>{if(paragraph.length){html+=`<p>${esc(paragraph.join(' '))}</p>`;paragraph=[];}};
  const closeList=()=>{if(list){html+=`</${list}>`;list='';}};
  for(const line of String(notes||t('update_no_notes')).replace(/\r/g,'').split('\n')){
   const heading=line.match(/^#{1,6}\s+(.+)$/),bullet=line.match(/^\s*[-*+]\s+(.+)$/),number=line.match(/^\s*\d+[.)]\s+(.+)$/);
   if(heading){flush();closeList();html+=`<h3>${esc(heading[1])}</h3>`;}
   else if(bullet||number){flush();const kind=bullet?'ul':'ol';if(list!==kind){closeList();list=kind;html+=`<${kind}>`;}html+=`<li>${esc((bullet||number)[1])}</li>`;}
   else{closeList();if(line.trim())paragraph.push(line.trim());else flush();}
  }
  flush();closeList();return html;
 }
 function renderInstalled(){
  if(notesDialog?.closed||!notesDialog?.el.isConnected||!state?.installed_release)return;
  const release=state.installed_release,scroll=$('.modal-body',notesDialog.el),position=scroll.scrollTop;
  $('[data-installed-notes]',notesDialog.body).innerHTML=`<div class="release-hero"><span class="release-version">XAnty ${esc(release.version)}</span><h1>${t('release_notes_title')}</h1><p>${t('release_notes_intro')}</p></div><article class="release-content">${notesHTML(release.notes)}</article><p class="release-hint">${t('release_notes_hint')}</p>`;
  scroll.scrollTop=position;
 }
 async function acknowledge(version){
  if(state?.installed_release?.version===version)state.installed_release.pending=false;
  try{await api('POST','/api/updates/notes/seen',{version});}catch(error){toast(error.message,'error');}
 }
 function showInstalled(automatic=false){
  const release=state?.installed_release;
  if(!release||(notesDialog?.el.isConnected&&!notesDialog.closed)||(automatic&&(!release.pending||shownVersion===release.version)))return;
  shownVersion=release.version;
  notesDialog=Dialogs.open({title:'whats_new',icon:'download',fullscreen:true,body:'<div data-installed-notes></div>',buttons:[{label:'release_notes_continue',kind:'primary',onClick:d=>d.close()}],onClose:()=>{notesDialog=null;acknowledge(release.version);}});
  renderInstalled();
  if(automatic)api('POST','/api/updates/notes/open',{}).catch(()=>{});
 }
 function render(){
  if(!state)return;
  const banner=$('#update-banner'),release=state.release,wasHidden=banner.classList.contains?.('hidden')??true;
  banner.classList.toggle('hidden',!release||dismissed===release.version);
  if(release)banner.innerHTML=`${I('download',18)}<div class="spacer"><strong>${t('update_available',{version:esc(release.version)})}</strong><p>${t(state.status==='ready'?'update_ready':'update_banner_text')}</p></div><button class="btn primary small" data-update-open>${t(state.status==='ready'?'update_install':'update_details')}</button><button class="icon-button" data-update-dismiss title="${t('close')}">${I('x',16)}</button>`;
  if(wasHidden&&release&&dismissed!==release.version&&typeof Motion!=='undefined')Motion.enter(banner,'banner');
  if(dialog?.el.isConnected&&!dialog.closed){
   const progress=typeof Motion!=='undefined'?Motion.captureProgress(dialog.body):null;
   const status=state.status,downloading=status==='downloading',busy=downloading||status==='checking'||status==='installing';
   const percent=release?Math.min(100,Math.round(state.downloaded/release.size*100)):0;
   $('[data-update-body]',dialog.body).innerHTML=`${state.installed_release?.version===state.current_version?'':`<p>${t('update_current',{version:esc(state.current_version)})}</p>`}${!state.configured?`<div class="notice">${t('update_not_configured')}</div>`:''}${state.error?`<div class="notice error" role="alert">${esc(I18N.error(state.error))}</div>`:''}${status==='current'?`<div class="notice success">${t('update_current_ok')}</div>`:''}${release?`<h3>${t('update_available',{version:esc(release.version)})}</h3><article class="release-notes release-preview">${notesHTML(release.notes)}</article><a href="${esc(release.page_url)}" target="_blank" rel="noopener noreferrer">${t('update_github')}</a>${!state.can_install?`<div class="notice">${t('update_manual_only')}</div>`:''}`:''}${downloading?`<div class="progress-track"><i data-progress-id="update-download" style="width:${percent}%"></i></div><p role="status">${t('update_downloading',{n:percent})}</p>`:''}${status==='ready'?`<div class="notice success">${t('update_ready')}</div><p>${t('update_close_profiles')}</p>`:''}${status==='installing'?`<div class="notice">${t('update_restarting')}</div>`:''}<div class="update-actions"><button class="btn" data-update-check ${busy||status==='ready'?'disabled':''}>${t('update_check')}</button>${release&&state.can_install?`<button class="btn primary" data-update-action ${busy?'disabled':''}>${busy?'<span class="spinner"></span>':''}${t(status==='ready'?'update_install':downloading?'update_loading':'update_download')}</button>`:''}</div>`;
   if(state.installed_release)$('[data-update-body]',dialog.body).insertAdjacentHTML('afterbegin',`<div class="installed-update"><div><strong>${t('update_current',{version:esc(state.installed_release.version)})}</strong><p>${t('release_notes_saved')}</p></div><button class="btn small" data-update-notes>${t('whats_new')}</button></div>`);
   if(typeof Motion!=='undefined')Motion.restoreProgress(dialog.body,progress);
  }
 }
 async function accept(data){state=data;render();showInstalled(true);if(data.release&&notified!==data.release.version){notified=data.release.version;toast(t('update_available',{version:data.release.version}),'info',12000,{label:t('update_details'),run:show});}}
 async function check(automatic=false){try{await accept(await api('POST','/api/updates/check',{automatic}));}catch(error){if(!automatic)toast(error.message,'error');}}
 async function show(){try{await accept(await api('GET','/api/updates'));if(dialog?.el.isConnected&&!dialog.closed){render();return;}dialog=Dialogs.open({title:'updates',icon:'download',wide:true,body:'<div data-update-body></div>',buttons:[{label:'close',onClick:d=>d.close()}]});render();}catch(error){toast(error.message,'error');}}
 async function act(){try{state=await api('POST',state.status==='ready'?'/api/updates/install':'/api/updates/download',{});render();}catch(error){toast(error.message,'error',12000);}}
 async function poll(){if(polling||state?.status!=='downloading')return;polling=true;try{await accept(await api('GET','/api/updates'));}catch{}finally{polling=false;}}
 function bind(){document.addEventListener('click',event=>{if(event.target.closest('[data-update-notes]'))showInstalled();if(event.target.closest('[data-update-open]'))show();if(event.target.closest('[data-update-dismiss]')){dismissed=state.release?.version||'';render();}const checkButton=event.target.closest('[data-update-check]');if(checkButton){checkButton.disabled=true;check().finally(render);}const action=event.target.closest('[data-update-action]');if(action){action.disabled=true;act();}});document.addEventListener('languagechange',()=>{render();renderInstalled();});}
 document.addEventListener('DOMContentLoaded',async()=>{bind();try{await accept(await api('GET','/api/updates'));const result=state.install_result;if(result&&!result.ok)toast(t('update_previous_failed')+'\n'+result.error,'error',20000);await check(true);}catch{}setInterval(poll,1200);setInterval(()=>check(true),60*60*1000);});
 return {show};
})();
