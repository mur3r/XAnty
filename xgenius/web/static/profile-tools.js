'use strict';
const ProfileTools=(()=>{
 let sets=[];
 const toolPath=(u,tool)=>`/api/accounts/${encodeURIComponent(u)}/tools/${tool}`;
 async function loadSets(){try{sets=(await api('GET','/api/extension-sets')).sets||[];}catch{sets=[];}return sets;}
 function setOptions(value=''){
  return `<option value="">${t('extensions_none')}</option>${value&&!sets.some(s=>s.id===value)?`<option value="${esc(value)}" selected>${t('extensions_portable')}</option>`:''}`+sets.map(s=>`<option value="${esc(s.id)}" ${s.id===value?'selected':''}>${esc(s.name)}</option>`).join('');
 }
 function fields(a={}){return `<div class="profile-browser-tools settings-group"><h3>${I('sliders',16)}<span data-i18n="ui_browser_behavior">${t('ui_browser_behavior')}</span></h3><label class="check"><input type="checkbox" name="restore_tabs" ${a.restore_tabs!==false?'checked':''}><span data-i18n="restore_tabs">${t('restore_tabs')}</span></label><div class="grid2"><label class="field"><span data-i18n="extension_set">${t('extension_set')}</span><select name="extension_set">${setOptions(a.extension_set)}</select><button type="button" class="text-button" data-extension-manage>${t('extension_sets')}</button></label><label class="field"><span>${t('profile_icon_text')}</span><input name="icon_text" maxlength="8" value="${esc(a.icon_text||'')}" placeholder="${t('profile_icon_auto')}"><small>${t('profile_icon_hint')}</small></label>${['block_images','block_media','block_fonts','phishing_protection'].map(key=>`<label class="check"><input type="checkbox" name="${key}" ${key==='phishing_protection'?a[key]!==false?'checked':'':a[key]?'checked':''}><span>${t('ops_'+key)}</span></label>`).join('')}<p class="hint span2">${t('ops_phishing_hint')}<br>${t('next_open')}</p></div></div>`;}
 async function settings(){
  const prefs=await run(()=>api('GET','/api/preferences'));if(!prefs)return;
  Dialogs.open({title:'browser_tools_settings',icon:'sliders',body:`<form><label class="check"><input type="checkbox" name="session_autosave" ${prefs.session_autosave?'checked':''}><span>${t('session_autosave')}</span></label><label class="field"><span>${t('autosave_seconds')}</span><input type="number" name="autosave_seconds" min="30" max="3600" step="1" required value="${prefs.autosave_seconds||60}"><small>${t('autosave_hint')}</small></label><button type="button" class="btn full" data-extension-manage>${t('extension_sets')}</button></form>`,buttons:[{label:'cancel',kind:'ghost',onClick:d=>d.close()},{label:'save',kind:'primary',onClick:async d=>{
   if(!$('form',d.body).reportValidity())return;
   S.preferences=await api('PUT','/api/preferences',{session_autosave:$('[name=session_autosave]',d.body).checked,autosave_seconds:Number($('[name=autosave_seconds]',d.body).value)});d.close();toast(t('saved'),'ok');
  }}]});
 }
 async function extensionSets(){
  await loadSets();let editId='';
  const d=Dialogs.open({title:'extension_sets',icon:'layers',wide:true,body:`<p>${t('extensions_hint')}</p><div class="extension-set-list"></div><form class="extension-set-form"><label class="field"><span>${t('set_name')}</span><input name="set_name" maxlength="100" required></label><label class="field"><span>${t('extension_directories')}</span><textarea name="directories" rows="4" placeholder="D:\\Extensions\\extension-one&#10;D:\\Extensions\\extension-two" required></textarea></label><div class="hint">${t('extension_directories_hint')}</div></form>`,buttons:[{label:'close',kind:'ghost',onClick:d=>d.close()},{label:'save_set',kind:'primary',onClick:async d=>{
   if(!$('form',d.body).reportValidity())return;
   await api('POST','/api/extension-sets',{name:$('[name=set_name]',d.body).value.trim(),directories:$('[name=directories]',d.body).value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean),...(editId?{id:editId}:{})});editId='';$('form',d.body).reset();await reload();toast(t('saved'),'ok');
  }}]});
  function render(){ $('.extension-set-list',d.body).innerHTML=sets.map(s=>`<article class="extension-set-item"><div><strong>${esc(s.name)}</strong><p class="hint">${s.extensions.map(e=>esc(e.name+' '+e.version)).join(' · ')}</p></div><button class="icon-button" data-set-delete="${esc(s.id)}" aria-label="${t('delete')}">${I('trash-2',14)}</button></article>`).join('')||`<p class="hint">${t('no_extension_sets')}</p>`; }
  async function reload(){await loadSets();render();$$('select[name=extension_set]').forEach(el=>{const value=el.value;el.innerHTML=setOptions(value);});}
  d.body.onclick=async event=>{const button=event.target.closest('[data-set-delete]');if(!button)return;if(!await Dialogs.confirm('delete',t('delete_set_question'),'delete','danger'))return;button.disabled=true;try{await api('DELETE','/api/extension-sets',{id:button.dataset.setDelete});await reload();}catch(error){d.error(error.message);}finally{button.disabled=false;}};
  render();
 }
 async function cookies(username){
  const response=await run(()=>api('GET',toolPath(username,'cookies')));if(!response)return;
  let current=response.cookies||[];
  const a=accounts().find(a=>a.username===username),opened=!!(a?.has_browser||a?.opening||a?.closing);
  const d=Dialogs.open({title:'cookies_all',icon:'layers',wide:true,body:`<p class="hint">${t('cookies_all_hint')}</p><div class="notice">${esc(a?.profile_name||username)} · <span data-cookie-count>${current.length}</span> cookies · ${t(response.source==='live'?'cookies_live':'cookies_snapshot')}</div>${response.warnings?.length?`<div class="notice warning">${esc(response.warnings.map(I18N.error).join('\n'))}</div>`:''}<label class="field"><span>${t('existing_cookies')}</span><textarea class="cookie-json" readonly rows="8" spellcheck="false">${esc(JSON.stringify(current,null,2))}</textarea></label><details ${!current.length?'open':''}><summary>${t('paste_cookie_data')}</summary><p class="hint">${t(opened?'cookies_close_first':'cookies_merge_hint')}</p><label class="field"><span>${t('cookies_file')}</span><input type="file" name="cookie_file" accept=".json,.txt,.cookies" ${opened?'disabled':''}></label><textarea name="cookie_input" aria-label="${t('paste_cookie_data')}" data-i18n-aria-label="paste_cookie_data" rows="6" spellcheck="false" placeholder="JSON / Netscape" ${opened?'disabled':''}></textarea><button class="btn primary" data-cookie-import ${opened?'disabled':''}>${t('import')}</button></details>`,buttons:[{label:'download',kind:'ghost',onClick:()=>downloadJSON(current,`cookies-${username}.json`)},{label:'close',kind:'primary',onClick:d=>d.close()}]});
  $('[data-cookie-import]',d.body).onclick=async event=>{const button=event.currentTarget;button.disabled=true;try{const file=$('[name=cookie_file]',d.body).files[0];if(file&&file.size>16*1024*1024)throw Error(t('cookie_file_limit'));const input=file?await file.text():$('[name=cookie_input]',d.body).value;if(!input.trim())throw Error(t('paste_cookie_data'));const result=await api('POST',toolPath(username,'cookies_import'),{cookies:input});current=(await api('GET',toolPath(username,'cookies'))).cookies;$('.cookie-json',d.body).value=JSON.stringify(current,null,2);$('[data-cookie-count]',d.body).textContent=current.length;toast(t('cookies_imported_all',{n:result.imported}),'ok');}catch(error){d.error(error.message);}finally{button.disabled=false;}};
 }
 async function diagnostics(username){
  const d=Dialogs.open({title:'network_diagnostics',icon:'activity',wide:true,body:`<p class="hint">${t('diagnostics_hint')}</p><div class="diagnostic-result"><div class="notice"><span class="spinner"></span> ${t('diagnostics_running')}</div></div>`,buttons:[{label:'close',kind:'ghost',onClick:d=>d.close()}]});
  try{const data=await api('POST',toolPath(username,'diagnostics'),{});if(d.closed||!d.el.isConnected)return;
   const rtc=data.webrtc||{},dns=data.dns||{};
   const badge=status=>`<span class="status-pill ${status==='warning'?'error':status==='matched'?'ok':''}">${t('diagnostic_'+status)}</span>`;
   $('.diagnostic-result',d.body).innerHTML=`<div class="diagnostic-card"><h3>${t('browser_ip')}</h3><p class="mono">${esc(data.ip||t('diagnostic_inconclusive'))}</p>${data.ip_mismatch?`<div class="notice warning">${t('browser_ip_changed')}</div>`:''}</div><div class="diagnostic-card"><h3>WebRTC ${badge(rtc.status)}</h3><p class="mono">${esc((rtc.public_ips||[]).join(', ')||'—')}</p>${rtc.mismatches?.length?`<div class="notice warning">${t('rtc_mismatch')}: ${esc(rtc.mismatches.join(', '))}</div>`:''}<p class="hint">${t('rtc_hint')}</p></div><div class="diagnostic-card"><h3>DNS ${badge(dns.status)}</h3><p class="hint">${t('dns_lookups',{n:dns.lookups||0,total:dns.expected||0})}</p>${(dns.resolvers||[]).map(r=>`<p class="mono">${esc([r.ip,r.operator||r.org,r.country,r.hostname].filter(Boolean).join(' · '))}</p>`).join('')}<p class="hint">${esc(dns.detail||'')}</p><p class="hint">${t('dns_hint')}</p></div>`;
  }catch(error){if(!d.closed&&d.el.isConnected){$('.diagnostic-result',d.body).innerHTML=`<div class="notice warning">${t('diagnostics_unavailable')}</div>`;d.error(error.message);}}
 }
 async function clearCache(username){
  if(!await Dialogs.confirm('clear_cache',t('clear_cache_question'),'clear_cache','danger'))return;
  await run(()=>api('POST',toolPath(username,'cache'),{}),r=>t('cache_cleared',{n:r.files,mb:(r.bytes/1048576).toFixed(2)}));
 }
 const openFolder=u=>run(()=>api('POST',toolPath(u,'folder'),{}));
 const saveSession=u=>run(()=>api('POST',toolPath(u,'save'),{}),t('session_saved'));
 document.addEventListener('click',event=>{if(event.target.closest('[data-extension-manage]'))extensionSets();});
 return {fields,loadSets,settings,extensionSets,cookies,diagnostics,clearCache,openFolder,saveSession};
})();
