'use strict';
const InterfaceQuality=(()=>{
 let initialized=false;
 function init(){
  if(initialized)return;
  const toggle=document.querySelector('#btn-sidebar-toggle'),close=document.querySelector('#btn-sidebar-close'),
   sidebar=document.querySelector('#workspace-sidebar'),backdrop=document.querySelector('#navigation-backdrop'),shell=document.querySelector('#screen-main');
  if(!toggle||!close||!sidebar||!backdrop||!shell)return;
  initialized=true;
  const small=matchMedia('(max-width:650px)');let opened=false,collapsed=typeof S!=='undefined'&&S.preferences?.folders_collapsed===true,saving=false;
  function sync(){
   shell.classList.toggle('navigation-open',small.matches&&opened);
   shell.classList.toggle('folders-collapsed',!small.matches&&collapsed);
   toggle.setAttribute('aria-expanded',String(small.matches?opened:!collapsed));
   backdrop.classList.toggle('hidden',!small.matches||!opened);
   sidebar.inert=small.matches?!opened:collapsed;
  }
  function setOpen(value,restore=false){
   opened=!!value&&small.matches;sync();
   if(opened)document.querySelector('#folder-search')?.focus({preventScroll:true});
   else if(restore)toggle.focus({preventScroll:true});
  }
  toggle.onclick=async()=>{
   if(small.matches){setOpen(!opened,true);return;}
   if(saving)return;
   const previous=collapsed;collapsed=!collapsed;sync();
   if(typeof S!=='undefined')S.preferences={...S.preferences,folders_collapsed:collapsed};
   if(typeof api!=='function')return;
   saving=true;toggle.disabled=true;
   try{const saved=await api('PUT','/api/preferences',{folders_collapsed:collapsed});collapsed=saved.folders_collapsed;if(typeof S!=='undefined')S.preferences={...S.preferences,folders_collapsed:collapsed};sync();}
   catch(error){collapsed=previous;if(typeof S!=='undefined')S.preferences={...S.preferences,folders_collapsed:previous};sync();if(typeof toast==='function')toast(error.message,'error');}
   finally{saving=false;toggle.disabled=false;}
  };
  close.onclick=()=>setOpen(false,true);backdrop.onclick=()=>setOpen(false,true);
  sidebar.addEventListener('click',event=>{if(small.matches&&event.target.closest('[data-folder]'))setOpen(false,true);});
  document.addEventListener('keydown',event=>{if(small.matches&&opened&&event.key==='Escape'){event.preventDefault();event.stopPropagation();setOpen(false,true);}},true);
  document.addEventListener('focusin',event=>{if(small.matches&&opened&&!sidebar.contains(event.target)&&event.target!==toggle)setOpen(false);});
  document.addEventListener('appearancechange',event=>{collapsed=event.detail?.folders_collapsed===true;sync();});
  small.addEventListener('change',()=>{opened=false;sync();if(sidebar.inert&&sidebar.contains(document.activeElement))toggle.focus({preventScroll:true});});
  sync();
 }
 document.addEventListener('DOMContentLoaded',init);
 return {init};
})();
