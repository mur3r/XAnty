'use strict';
const Motion=(()=>{
 const media=typeof matchMedia==='function'?matchMedia('(prefers-reduced-motion: reduce)'):null;
 const entering=new Map(),leaving=new Map();
 const kinds=new Set(['view','dialog','menu','toast','startup','banner','progress']);
 const reduced=()=>!!media?.matches;
 function enter(element,kind='view'){
  if(!element||!kinds.has(kind)||reduced()||element.isConnected===false||leaving.has(element))return;
  if(entering.has(element))return;
  const name='motion-enter-'+kind;
  let timer;
  const finish=event=>{
   if(event&&(event.target!==element||(event.animationName&&!event.animationName.startsWith('xanty-enter-'))))return;
   clearTimeout(timer);element.classList.remove(name);
   element.removeEventListener('animationend',finish);element.removeEventListener('animationcancel',finish);
   entering.delete(element);
  };
  entering.set(element,finish);element.classList.add(name);
  element.addEventListener('animationend',finish);element.addEventListener('animationcancel',finish);
  timer=setTimeout(finish,260);
 }
 function exit(element){
  if(!element||leaving.has(element))return;
  element.inert=true;element.setAttribute('aria-hidden','true');
  const immediate=reduced()||element.isConnected===false;
  if(!immediate&&typeof getComputedStyle==='function'){
   const opacity=Number(getComputedStyle(element).opacity);
   if(Number.isFinite(opacity))element.style.setProperty('--motion-exit-opacity',String(opacity));
  }
  entering.get(element)?.();
  if(immediate){element.remove();return;}
  let timer;
  const finish=event=>{
   if(event&&(event.target!==element||(event.animationName&&!event.animationName.startsWith('xanty-exit-'))))return;
   clearTimeout(timer);element.removeEventListener('animationend',finish);element.removeEventListener('animationcancel',finish);
   leaving.delete(element);element.remove();
  };
  leaving.set(element,finish);element.classList.add('motion-exit');
  element.addEventListener('animationend',finish);element.addEventListener('animationcancel',finish);
  timer=setTimeout(finish,200);
 }
 function captureProgress(root){
  const values=new Map();
  if(!root||reduced())return values;
  for(const bar of root.querySelectorAll('[data-progress-id]')){
   const value=Number.parseFloat(bar.style.width);
   if(!bar.parentElement?.classList.contains('indeterminate')&&Number.isFinite(value))values.set(bar.dataset.progressId,value);
  }
  return values;
 }
 function restoreProgress(root,values){
  if(!root||!values?.size||reduced())return;
  for(const bar of root.querySelectorAll('[data-progress-id]')){
   const previous=values.get(bar.dataset.progressId),next=Number.parseFloat(bar.style.width);
   if(!Number.isFinite(previous)||!Number.isFinite(next)||next<=previous||next>100||previous<0||bar.parentElement?.classList.contains('indeterminate'))continue;
   bar.style.setProperty('--motion-progress-from',String(previous/next));enter(bar,'progress');
  }
 }
 media?.addEventListener?.('change',()=>{
  if(!reduced())return;
  for(const finish of [...entering.values()])finish();
  for(const finish of [...leaving.values()])finish();
 });
 document.addEventListener('DOMContentLoaded',()=>enter(document.querySelector('.welcome-card'),'startup'));
 return {enter,exit,reduced,captureProgress,restoreProgress};
})();
