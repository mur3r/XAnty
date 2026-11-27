'use strict';
const ProfileUI = (() => {
  const allColumns=['number','name','start','profile_status','status','proxy','auto_login','last_launch','runtime','tags','notes','group','profile_size','reminder'];
  const defaults=allColumns.slice(0,9);
  const columnLabel=key=>({number:'profile_number',profile_name:'name',favorite:'favorites',start:'start',status:'browser_state',group:'folder'}[key]||key);
  const statuses=['active','new','review','unused'];
  const statusOptions=value=>statuses.map(s=>`<option value="${s}" ${s===value?'selected':''}>${t('work_'+s)}</option>`).join('');
  function columns(){
    const value=S.preferences?.columns;
    return Array.isArray(value)&&value.includes('name')&&value.every(c=>allColumns.includes(c))&&new Set(value).size===value.length?[...value]:[...defaults];
  }
  function matches(a,query){
    const tags=Array.isArray(a.tags)?a.tags.map(tag=>typeof tag==='string'?tag:tag?.name||''):a.tags||'';
    return [a.index,a.username,a.profile_name,a.dolphin_profile_id,a.group,a.proxy,a.notes,tags,a.proxy_ip,
      ...(a.proxy_status==='ok'?[...Object.values(a.proxy_location||{}),a.proxy_location?.country_code==='US'?'USA':'']:[])]
      .join(' ').toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
  }
  const sort=rows=>[...rows].sort((a,b)=>Number(!!b.favorite)-Number(!!a.favorite));
  function runtimeSeconds(a,now=Date.now()){
    const extra=a.has_browser&&a.runtime_checkpoint?Math.max(0,(now-Date.parse(a.runtime_checkpoint))/1000):0;
    return Math.max(0,Number(a.runtime_seconds)||0)+(Number.isFinite(extra)?extra:0);
  }
  const date=value=>value&&value!=='N/A'&&!Number.isNaN(Date.parse(value))?new Date(value).toLocaleString(I18N.language==='uk'?'uk-UA':I18N.language==='ru'?'ru-RU':'en-GB',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}):'—';
  const numberFormats=new Map();
  function runtimeNumber(value){const lang=I18N.language;if(!numberFormats.has(lang))numberFormats.set(lang,new Intl.NumberFormat(lang,{minimumFractionDigits:2,maximumFractionDigits:2}));return numberFormats.get(lang).format(value);}
  function runtimeHTML(a){return `<span data-runtime>${runtimeNumber(runtimeSeconds(a)/3600)} ${t('hours_short')}</span>${a.has_browser?'<i class="runtime-live"></i>':''}`;}
  function tick(){
    const rows=new Map(accounts().map(a=>[a.username,a]));
    $$('#rows [data-runtime]').forEach(el=>{const a=rows.get(el.closest('[data-u]').dataset.u);if(a)el.textContent=runtimeNumber(runtimeSeconds(a)/3600)+' '+t('hours_short');});
  }
  function applyColumns(){
    const visible=columns(),order=[...visible,...allColumns.filter(c=>!visible.includes(c))];
    $$('.profiles-table tr').forEach(row=>{
      const end=$('.row-options-col',row);
      const cells=new Map($$('[data-column]',row).map(el=>[el.dataset.column,el]));
      order.forEach(key=>{const cell=cells.get(key);if(cell){cell.hidden=!visible.includes(key);row.insertBefore(cell,end);}});
    });
  }
  async function metadata(names,values){await api('PATCH','/api/accounts/metadata',{usernames:names,metadata:values});await refreshState();}
  function rename(username){
    if(S.renaming||S.noteEditing)return;
    const row=$$('#rows [data-u]').find(el=>el.dataset.u===username),title=$('.profile-title',row);
    if(!title)return;
    const account=accounts().find(a=>a.username===username),name=account.profile_name||username;
    S.renaming=username;
    const input=document.createElement('input');input.className='inline-rename';input.value=name;input.maxLength=200;input.setAttribute('aria-label',t('quick_rename'));
    title.replaceChildren(input);input.focus();input.select();let finished=false;
    const finish=async save=>{
      if(finished)return;finished=true;
      try{if(save&&input.value.trim()&&input.value.trim()!==name)await metadata([username],{profile_name:input.value.trim()});}
      catch(error){toast(error.message,'error');}
      finally{S.renaming=null;await refreshState();}
    };
    input.onkeydown=event=>{if(event.key==='Enter'||event.key==='Escape'){event.preventDefault();event.stopPropagation();finish(event.key==='Enter');}};
    input.onblur=()=>finish(true);
  }
  function editNote(username){
    if(S.renaming||S.noteEditing)return;
    const row=$$('#rows [data-u]').find(el=>el.dataset.u===username),cell=row&&$('[data-note]',row);
    const account=accounts().find(a=>a.username===username);
    if(!cell||!account)return;
    const original=account.notes||'',editor=document.createElement('div');
    editor.className='note-editor';
    editor.innerHTML=`<textarea rows="3" maxlength="10000" aria-label="${esc(t('notes'))}"></textarea><div class="note-editor-actions"><small>${esc(t('notes_save_hint'))}</small><button type="button" class="icon-button" data-note-save aria-label="${esc(t('save'))}" title="${esc(t('save'))}">${I('check',16)}</button><button type="button" class="icon-button" data-note-cancel aria-label="${esc(t('cancel'))}" title="${esc(t('cancel'))}">${I('x',16)}</button></div><div class="note-editor-error hidden" role="alert"></div>`;
    const input=$('textarea',editor),buttons=$$('button',editor),error=$('.note-editor-error',editor);
    input.value=original;S.noteEditing=username;cell.classList.add('is-editing');cell.replaceChildren(editor);
    let busy=false,finished=false;
    const finish=async save=>{
      if(finished||busy)return;
      if(save&&input.value!==original){
        busy=true;input.disabled=true;buttons.forEach(button=>button.disabled=true);editor.setAttribute('aria-busy','true');
        try{await metadata([username],{notes:input.value});}
        catch(reason){
          busy=false;input.disabled=false;buttons.forEach(button=>button.disabled=false);editor.setAttribute('aria-busy','false');
          error.textContent=I18N.error(reason.message);error.classList.remove('hidden');input.focus();return;
        }
      }
      finished=true;S.noteEditing=null;renderTable();
      const next=$$('#rows [data-u]').find(el=>el.dataset.u===username);
      if(!save&&next)$('[data-note]',next)?.focus({preventScroll:true});
    };
    $('[data-note-save]',editor).onclick=()=>finish(true);
    $('[data-note-cancel]',editor).onclick=()=>finish(false);
    input.onkeydown=event=>{
      if(event.key==='Escape'||event.key==='Enter'&&(event.ctrlKey||event.metaKey)){
        event.preventDefault();event.stopPropagation();finish(event.key!=='Escape');
      }
    };
    editor.onfocusout=event=>{if(!editor.contains(event.relatedTarget))finish(true);};
    input.focus();input.setSelectionRange(input.value.length,input.value.length);
  }
  async function preferences(values){S.preferences=await api('PUT','/api/preferences',values);}
  function columnSettings(){
    let order=[...columns(),...allColumns.filter(c=>!columns().includes(c))],visible=new Set(columns());
    const d=Dialogs.open({title:'columns',icon:'sliders',body:'<p data-i18n="columns_hint">'+t('columns_hint')+'</p><div class="column-list"></div>',buttons:[
      {label:'reset_columns',kind:'ghost',onClick:()=>{order=[...allColumns];visible=new Set(defaults);render();}},
      {label:'cancel',kind:'ghost',onClick:d=>d.close()},
      {label:'save',kind:'primary',onClick:async d=>{await preferences({columns:order.filter(c=>visible.has(c))});d.close();applyColumns();}}
    ]});
    function render(){
      $('.column-list',d.body).innerHTML=order.map((key,i)=>`<div class="column-item" data-key="${key}"><label><input type="checkbox" ${visible.has(key)?'checked':''} ${key==='name'?'disabled':''}>${t(columnLabel(key))}</label><button class="icon-button" data-direction="-1" ${i===0?'disabled':''} aria-label="${t('move_up')}">↑</button><button class="icon-button" data-direction="1" ${i===order.length-1?'disabled':''} aria-label="${t('move_down')}">↓</button></div>`).join('');
    }
    d.body.onchange=event=>{const key=event.target.closest('[data-key]')?.dataset.key;if(key)event.target.checked?visible.add(key):visible.delete(key);};
    d.body.onclick=event=>{const button=event.target.closest('[data-direction]');if(!button)return;const i=order.indexOf(button.closest('[data-key]').dataset.key),j=i+Number(button.dataset.direction);if(j>=0&&j<order.length){[order[i],order[j]]=[order[j],order[i]];render();}};
    render();
  }
  const daysField=(value=30)=>`<label class="field"><span data-i18n="retention_days">${t('retention_days')}</span><input type="number" name="retention_days" value="${value}" min="0" max="3650" step="1" required><small data-i18n="retention_hint">${t('retention_hint')}</small></label>`;
  function remove(names){
    const protectedProfiles=WorkspaceOps.isProtected(accounts().filter(a=>names.includes(a.username)));
    Dialogs.open({title:'move_to_trash',icon:'trash-2',body:`<p>${t('trash_question',{n:names.length})}</p><form>${daysField(S.preferences?.trash_retention_days??30)}${protectedProfiles?`<div class="notice warning">${t('ops_protected_hint')}</div><label class="field"><span>${t('ops_type_delete')}</span><input name="confirmation" pattern="DELETE" required autocomplete="off" spellcheck="false"></label>`:''}</form>`,buttons:[{label:'cancel',kind:'ghost',onClick:d=>d.close()},{label:'move_to_trash',kind:'danger',onClick:async d=>{
      if(!$('form',d.body).reportValidity())return;
      const days=Number($('[name=retention_days]',d.body).value);
      await api('POST','/api/accounts/delete',{usernames:names,retention_days:days,...(protectedProfiles?{confirmation:$('[name=confirmation]',d.body).value}:{})});
      names.forEach(n=>S.selected.delete(n));d.close();await refreshState();toast(t('trashed'),'ok');await run(()=>preferences({trash_retention_days:days}));
    }}]});
  }
  async function trash(){
    const response=await run(()=>api('GET','/api/trash'));if(!response)return;
    const d=Dialogs.open({title:'trash',icon:'trash-2',wide:true,body:`<p data-i18n="trash_hint">${t('trash_hint')}</p><div class="trash-list"></div>`,buttons:[{label:'refresh',kind:'ghost',onClick:()=>reload()},{label:'close',kind:'primary',onClick:d=>d.close()}]});
    let profiles=response.profiles;
    function render(){
      $('.trash-list',d.body).innerHTML=profiles.length?profiles.map(a=>`<article class="trash-item" data-trash-user="${esc(a.username)}"><div class="trash-heading"><strong>${esc(a.profile_name||a.username)}</strong><span class="muted">#${a.profile_number} · @${esc(a.username)}</span></div><div class="hint">${t('deleted_at')}: ${date(a.deleted_at)}<br>${t('delete_after')}: ${a.delete_after?date(a.delete_after):t('never_delete')}</div><div class="trash-controls"><button class="btn small" data-trash-action="restore">${t('restore')}</button><label>${t('retention_days')}<input type="number" value="${a.retention_days}" min="0" max="3650" step="1" required aria-label="${t('retention_days')}"></label><button class="btn small" data-trash-action="retention">${t('save')}</button><button class="btn small danger" data-trash-action="purge">${t('delete_forever')}</button><button class="icon-button" data-trash-action="history" aria-label="${t('change_history')}">↺</button></div></article>`).join(''):`<div class="empty compact">${t('trash_empty')}</div>`;
    }
    async function reload(){profiles=(await api('GET','/api/trash')).profiles;render();}
    d.body.onclick=async event=>{
      const button=event.target.closest('[data-trash-action]');if(!button)return;
      const row=button.closest('[data-trash-user]'),username=row.dataset.trashUser,action=button.dataset.trashAction;
      if(action==='history'){history(username);return;}
      let confirmation;
      if(action==='purge'){const protectedProfile=WorkspaceOps.isProtected(profiles.filter(a=>a.username===username));const accepted=protectedProfile?await Dialogs.confirmTyped('delete_forever',t('purge_question')):await Dialogs.confirm('delete_forever',t('purge_question'),'delete_forever','danger');if(!accepted)return;if(protectedProfile)confirmation='DELETE';}
      const input=$('input',row);if(action==='retention'&&!input.reportValidity())return;
      button.disabled=true;
      try{await api('POST',`/api/trash/${action}`,{usernames:[username],...(confirmation?{confirmation}:{}),...(action==='retention'?{retention_days:Number(input.value)}:{})});await reload();await refreshState();}
      catch(error){d.error(error.message);}finally{button.disabled=false;}
    };
    render();
  }
  async function history(username){
    const response=await run(()=>api('GET','/api/history'+(username?'?username='+encodeURIComponent(username):'')));if(!response)return;
    let page=0;
    const d=Dialogs.open({title:'change_history',icon:'activity',wide:true,body:`<p class="hint" data-i18n="history_hint">${t('history_hint')}</p><input type="search" class="history-search" aria-label="${t('search_history')}" placeholder="${t('search_history')}"><div class="history-list"></div><div class="history-pages"><button class="btn small" data-history-prev>‹</button><span data-history-count></span><button class="btn small" data-history-next>›</button></div>`,buttons:[{label:'close',kind:'primary',onClick:d=>d.close()}]});
    const value=(key,v)=>v==null||v===''?'—':typeof v==='boolean'?t(v?'yes':'no'):key==='profile_status'?t('work_'+v):Array.isArray(v)?v.join(', '):String(v);
    function render(){
      const query=$('.history-search',d.body).value.trim().toLocaleLowerCase();
      const events=response.events.filter(e=>[e.profile_name,e.username,e.actor,t('audit_'+e.action),JSON.stringify(e.changes)].join(' ').toLocaleLowerCase().includes(query));
      page=Math.min(page,Math.max(0,Math.ceil(events.length/50)-1));
      $('.history-list',d.body).innerHTML=events.slice(page*50,(page+1)*50).map(e=>`<article class="history-event"><div class="history-heading"><strong>${esc(e.profile_name)}</strong><span class="status-pill">${t('audit_'+e.action)}</span></div><div class="hint">${date(e.at)} · ${esc(e.actor)} · @${esc(e.username)}</div>${Object.entries(e.changes||{}).map(([key,v])=>`<div class="history-change"><b>${esc(t(columnLabel(key)))}</b><span>${esc(value(key,v.before))}</span><span>→</span><span>${esc(value(key,v.after))}</span></div>`).join('')}</article>`).join('')||`<div class="empty compact">${t(query?'no_matches':'history_empty')}</div>`;
      $('[data-history-count]',d.body).textContent=t('shown',{from:events.length?page*50+1:0,to:Math.min(events.length,(page+1)*50),total:events.length});
      $('[data-history-prev]',d.body).disabled=page===0;$('[data-history-next]',d.body).disabled=(page+1)*50>=events.length;
    }
    $('.history-search',d.body).oninput=()=>{page=0;render();};
    $('[data-history-prev]',d.body).onclick=()=>{page--;render();};$('[data-history-next]',d.body).onclick=()=>{page++;render();};
    render();
  }
  return {columns,matches,sort,runtimeSeconds,runtimeHTML,date,tick,applyColumns,metadata,rename,editNote,columnSettings,remove,trash,history,statusOptions};
})();
