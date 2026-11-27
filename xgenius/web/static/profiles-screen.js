'use strict';
const ProfilesScreen=(()=>{
 let collator=null,collatorLanguage='',loadingCount=0,loadingTimer=null;
 const modes=new Set(['favorites','number','name','last_launch']);
 function sort(rows,mode='favorites'){
  if(!modes.has(mode)||mode==='favorites')return ProfileUI.sort(rows);
  if(collatorLanguage!==I18N.language){collatorLanguage=I18N.language;collator=new Intl.Collator(I18N.language,{numeric:true,sensitivity:'base'});}
  const number=a=>Number(a.index)||0;
  const date=a=>Number.isFinite(Date.parse(a.last_launch))?Date.parse(a.last_launch):0;
  return [...rows].sort((a,b)=>(mode==='name'?collator.compare(a.profile_name||a.username,b.profile_name||b.username):mode==='last_launch'?date(b)-date(a):number(a)-number(b))||number(a)-number(b));
 }
 function tags(value){return (Array.isArray(value)?value:[value||'']).map(tag=>typeof tag==='string'?tag:tag?.name||'').filter(Boolean);}
 function tagsHTML(values,limit=3){
  if(!values.length)return '';
  return `<span class="profile-tags" aria-label="${esc(values.join(', '))}">${values.slice(0,limit).map(value=>`<span class="profile-tag" title="${esc(value)}">${esc(value)}</span>`).join('')}${values.length>limit?`<span class="profile-tag profile-tag-more" title="${esc(values.slice(limit).join(', '))}">+${values.length-limit}</span>`:''}</span>`;
 }
 function avatar(account){
  const name=account.profile_name||account.username||'',words=name.trim().split(/[\s._-]+/).filter(Boolean);
  const initials=account.icon_text||((words.length>1?Array.from(words[0])[0]+Array.from(words[1])[0]:Array.from(words[0]||'?').slice(0,2).join('')).toLocaleUpperCase(I18N.language));
  let hash=0;for(const c of account.profile_id||account.username||name)hash=(hash*31+c.codePointAt(0))>>>0;
  return `<span class="profile-avatar avatar-tone-${hash%3} ${Array.from(initials).length>3?'avatar-long':''}" aria-hidden="true">${esc(initials)}</span>`;
 }
 function pageIndex(value,total,size){return Math.max(0,Math.min(Math.max(0,Math.ceil(total/size)-1),Math.floor(Number(value)||1)-1));}
 function syncControls(filtered){
  const pages=Math.max(1,Math.ceil(filtered.length/S.pageSize)),jump=$('#profile-page-jump');
  if(jump){jump.max=pages;jump.disabled=!filtered.length;if(document.activeElement!==jump)jump.value=S.page+1;}
  const total=$('#profile-page-total');if(total)total.textContent=pages;
  const visible=$('#profile-results');if(visible)visible.textContent=t('profiles_result_count',{n:filtered.length,total:accounts().length});
  for(const [id,value] of [['f-status',S.status],['f-profile-status',S.profileStatus],['f-proxy',S.proxyFilter],['profile-sort',S.profileSort!=='favorites']])$('#'+id)?.classList.toggle('has-filter',!!value);
  const reset=$('#profiles-clear-filters');if(reset)reset.disabled=!(S.q||S.status||S.profileStatus||S.proxyFilter||S.profileSort!=='favorites');
  const folderEmpty=!!S.group&&!S.q&&!S.status&&!S.profileStatus&&!S.proxyFilter;
  const heading=$('#profiles-empty-heading'),hint=$('#profiles-empty-hint');
  if(heading)heading.textContent=t(folderEmpty?'profiles_folder_empty':'no_matches');
  if(hint)hint.textContent=t(folderEmpty?'profiles_folder_empty_hint':'profiles_no_matches_hint');
 }
 function beforeRender(){
  const wrap=$('#view-profiles .table-wrap'),open=$('#rows .row-options[open]');
  const focused=document.activeElement,owner=focused?.closest?.('[data-u]');
  return {top:wrap?.scrollTop||0,left:wrap?.scrollLeft||0,open:open?.closest('[data-u]')?.dataset.u,
   focused:owner?.dataset.u,action:focused?.dataset?.act,summary:focused?.tagName==='SUMMARY',
   control:['[data-note]','[data-rename]','[data-chk]','[data-profile-status]'].find(selector=>focused?.matches?.(selector))};
 }
 function positionMenu(summary){
  if(!summary?.parentElement?.open)return;
  const menu=$('.context-menu',summary.parentElement),box=summary.getBoundingClientRect(),height=menu.offsetHeight,width=menu.offsetWidth;
  const below=box.bottom+6,top=below+height<=innerHeight-8?below:box.top-height-6;
  menu.style.top=Math.max(8,Math.min(top,innerHeight-height-8))+'px';
  menu.style.left=Math.max(8,Math.min(box.right-width,innerWidth-width-8))+'px';
 }
 function afterRender(context,resetScroll=false){
  const wrap=$('#view-profiles .table-wrap');if(wrap){wrap.scrollTop=resetScroll?0:context.top;wrap.scrollLeft=context.left;}
  if(context.open||context.focused){
   const rows=$$('#rows tr[data-u]');
   const opened=rows.find(row=>row.dataset.u===context.open);
   if(opened){const details=$('.row-options',opened);details.open=true;positionMenu($('summary',details));}
   const focused=rows.find(row=>row.dataset.u===context.focused);
   if(focused&&context.action)$$('[data-act]',focused).find(el=>el.dataset.act===context.action)?.focus({preventScroll:true});
   else if(focused&&context.summary)$('summary',focused)?.focus({preventScroll:true});
   else if(focused&&context.control)$(context.control,focused)?.focus({preventScroll:true});
  }
 }
 function loading(active){
  loadingCount=Math.max(0,loadingCount+(active?1:-1));
  const panel=$('#view-profiles .profile-panel'),banner=$('#profiles-loading'),button=$('#btn-refresh');
  panel?.setAttribute('aria-busy',String(loadingCount>0));if(button)button.disabled=loadingCount>0;
  if(active){$('#profiles-load-error')?.classList.add('hidden');if(!loadingTimer)loadingTimer=setTimeout(()=>{loadingTimer=null;if(loadingCount)banner?.classList.remove('hidden');},160);}
  if(!loadingCount){clearTimeout(loadingTimer);loadingTimer=null;banner?.classList.add('hidden');}
 }
 function loadError(){$('#profiles-load-error')?.classList.remove('hidden');}
 return {sort,tags,tagsHTML,avatar,pageIndex,syncControls,beforeRender,afterRender,positionMenu,loading,loadError};
})();
