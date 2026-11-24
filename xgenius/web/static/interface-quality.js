'use strict';
const InterfaceQuality=(()=>{
 let initialized=false;
 function init(){
  if(initialized)return;
  const toggle=document.querySelector('#btn-sidebar-toggle'),close=document.querySelector('#btn-sidebar-close'),
   sidebar=document.querySelector('#workspace-sidebar'),backdrop=document.querySelector('#navigation-backdrop'),shell=document.querySelector('#screen-main');
  if(!toggle||!close||!sidebar||!backdrop||!shell)return;
  initialized=true;
  const small=matchMedia('(max-width:650px)');let opened=false;
  function setOpen(value,restore=false){
   opened=!!value&&small.matches;
   shell.classList.toggle('navigation-open',opened);toggle.setAttribute('aria-expanded',String(opened));
   backdrop.classList.toggle('hidden',!opened);
   if(opened)document.querySelector('#folder-search')?.focus({preventScroll:true});
   else if(restore)toggle.focus({preventScroll:true});
  }
  toggle.onclick=()=>setOpen(!opened,true);close.onclick=()=>setOpen(false,true);backdrop.onclick=()=>setOpen(false,true);
  sidebar.addEventListener('click',event=>{if(event.target.closest('[data-folder]'))setOpen(false,true);});
  document.addEventListener('keydown',event=>{if(opened&&event.key==='Escape'){event.preventDefault();event.stopPropagation();setOpen(false,true);}},true);
  document.addEventListener('focusin',event=>{if(opened&&!sidebar.contains(event.target)&&event.target!==toggle)setOpen(false);});
  small.addEventListener('change',()=>{if(!small.matches)setOpen(false);});
 }
 document.addEventListener('DOMContentLoaded',init);
 return {init};
})();
