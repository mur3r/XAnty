'use strict';
(()=>{
 let hiding=false;
 document.addEventListener('keydown',async event=>{
  if(event.key!=='Escape'||event.defaultPrevented||event.repeat||event.isComposing||event.altKey||event.ctrlKey||event.metaKey||event.shiftKey)return;
  // Dialog/inline editor handlers take precedence over hiding the application.
  if(document.querySelector('.modal-overlay:not([inert])'))return;
  const menus=Array.from(document.querySelectorAll('.row-options[open]'));
  if(menus.length){menus.forEach(menu=>menu.open=false);event.preventDefault();return;}
  const hide=window.pywebview?.api?.hide;
  if(typeof hide!=='function'||hiding)return;
  event.preventDefault();hiding=true;
  try{
   const hidden=await hide();
   if(hidden===false&&typeof toast==='function')toast(t('desktop_hide_failed'),'warn');
  }catch(error){console.warn('Could not hide XAnty',error);}
  finally{hiding=false;}
 });
})();
