'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

function element(){
 const classes=new Set(),events=new Map(),attributes={},properties={};
 return {isConnected:true,inert:false,style:{width:'',setProperty:(k,v)=>properties[k]=v},properties,attributes,
  classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x)},
  addEventListener(k,fn){if(!events.has(k))events.set(k,new Set());events.get(k).add(fn);},
  removeEventListener(k,fn){events.get(k)?.delete(fn);},
  emit(k,target=this,animationName){for(const fn of [...events.get(k)||[]])fn({target,animationName});},
  setAttribute(k,v){attributes[k]=v;},remove(){this.isConnected=false;},focus(){this.focused=true;},
  append(){},querySelector(){return null;},querySelectorAll(){return [];}};
}
function environment(reduced=false,dialogs=false){
 const timers=new Map(),changes=new Map();let timerId=0;
 const media={matches:reduced,addEventListener:(key,fn)=>changes.set(key,fn)};
 const body=element(),foot=element(),close=element(),modal=element(),root=element(),previous=element();
 let overlay;
 const document={activeElement:previous,addEventListener(){},querySelector:s=>s==='#modal-root'?root:null,
  createElement(tag){const el=element();if(tag==='div'){overlay=el;el.querySelector=s=>({'.modal-body':body,'.modal-foot':foot,'[data-close]':close,'.modal':modal}[s]||null);}return el;}};
 const c=vm.createContext({document,matchMedia:()=>media,Map,Set,console,
  setTimeout:(fn,ms)=>{timers.set(++timerId,{fn,ms});return timerId;},clearTimeout:id=>timers.delete(id),
  I:()=>'',t:key=>key,esc:String,I18N:{localize(){},error:String}});
 vm.runInContext(fs.readFileSync('xgenius/web/static/motion.js','utf8'),c);
 if(dialogs)vm.runInContext(fs.readFileSync('xgenius/web/static/dialogs.js','utf8'),c);
 const run=code=>vm.runInContext(code,c);
 if(dialogs)run('globalThis.$=(s,root=document)=>root.querySelector(s);globalThis.$$=(s,root=document)=>root.querySelectorAll(s);globalThis.motionEnter=(el,kind)=>Motion.enter(el,kind);globalThis.motionExit=el=>Motion.exit(el);globalThis.closedCount=0;');
 return {c,run,timers,media,previous,getOverlay:()=>overlay,
  reduce(){media.matches=true;changes.get('change')();},
  flush(){for(const [id,task]of [...timers]){timers.delete(id);task.fn();}}};
}

test('entrances finish only on their own event, with a fallback and no layout reads',()=>{
 const e=environment();e.c.node=element();
 Object.defineProperty(e.c.node,'offsetWidth',{get(){throw Error('Layout read');}});
 e.run('Motion.enter(node,"view");Motion.enter(node,"view")');
 assert.equal(e.timers.size,1);assert.equal(e.c.node.classList.contains('motion-enter-view'),true);
 e.c.node.emit('animationend',element());assert.equal(e.timers.size,1);
 e.c.node.emit('animationend');assert.equal(e.timers.size,0);
 assert.equal(e.c.node.classList.contains('motion-enter-view'),false);
 e.run('Motion.enter(node,"view")');e.flush();assert.equal(e.timers.size,0);
});

test('exits surrender input immediately, are idempotent and remove at animation completion',()=>{
 const e=environment();e.c.node=element();e.run('Motion.enter(node,"dialog");Motion.exit(node);Motion.exit(node)');
 assert.equal(e.c.node.inert,true);assert.equal(e.c.node.attributes['aria-hidden'],'true');
 assert.equal(e.c.node.isConnected,true);assert.equal(e.timers.size,1);
 e.c.node.emit('animationcancel',e.c.node,'xanty-enter-overlay');assert.equal(e.c.node.isConnected,true);
 e.c.node.emit('animationend',e.c.node,'xanty-exit-overlay');assert.equal(e.c.node.isConnected,false);assert.equal(e.timers.size,0);
});

test('reduced motion skips entrance and removes closing elements synchronously',()=>{
 const e=environment(true);e.c.node=element();e.run('Motion.enter(node,"toast");Motion.exit(node)');
 assert.equal(e.timers.size,0);assert.equal(e.c.node.isConnected,false);
});

test('changing the system preference immediately finishes pending entrances and exits',()=>{
 const e=environment();e.c.a=element();e.c.b=element();
 e.run('Motion.enter(a,"view");Motion.exit(b)');assert.equal(e.timers.size,2);
 e.reduce();assert.equal(e.timers.size,0);assert.equal(e.c.b.isConnected,false);
 assert.equal(e.c.a.classList.contains('motion-enter-view'),false);
});

test('canceled entrances can restart and detached elements never queue work',()=>{
 const e=environment();e.c.node=element();e.run('Motion.enter(node,"menu")');
 e.c.node.emit('animationcancel');assert.equal(e.timers.size,0);
 e.run('Motion.enter(node,"menu")');assert.equal(e.timers.size,1);e.flush();
 e.c.node.isConnected=false;e.run('Motion.enter(node,"menu")');assert.equal(e.timers.size,0);
});

test('progress preserves visible fill through replacement without frames or geometry reads',()=>{
 const e=environment(),old=element(),next=element();old.dataset={progressId:'job-a'};next.dataset={progressId:'job-a'};
 old.style.width='20%';next.style.width='50%';e.c.root={querySelectorAll:()=>[old]};
 e.c.values=e.run('Motion.captureProgress(root)');e.c.root={querySelectorAll:()=>[next]};
 e.run('Motion.restoreProgress(root,values)');
 assert.equal(next.properties['--motion-progress-from'],'0.4');
 assert.equal(next.classList.contains('motion-enter-progress'),true);
 assert.equal(next.style.width,'50%');e.flush();
});

test('progress skips resets, indeterminate states, new jobs and reduced motion',()=>{
 for(const [before,after,id,indeterminate]of [[50,10,'a',false],[20,40,'b',false],[20,40,'a',true]]){
  const e=environment(),bar=element();bar.dataset={progressId:'a'};bar.style.width=before+'%';
  e.c.root={querySelectorAll:()=>[bar]};e.c.values=e.run('Motion.captureProgress(root)');
  bar.style.width=after+'%';bar.dataset.progressId=id;bar.parentElement={classList:{contains:()=>indeterminate}};
  e.run('Motion.restoreProgress(root,values)');assert.equal(e.timers.size,0);
 }
 const e=environment(true);e.c.root={querySelectorAll(){throw Error('Unnecessary traversal');}};
 assert.equal(e.run('Motion.captureProgress(root).size'),0);
});

test('modal close notifies callers and restores focus before visual removal',()=>{
 const e=environment(false,true);
 e.run('globalThis.d=Dialogs.open({title:"test",body:"",onClose:()=>closedCount++});d.close();d.close()');
 assert.equal(e.run('closedCount'),1);assert.equal(e.run('d.closed'),true);
 assert.equal(e.run('d.el.isConnected&&!d.closed'),false);
 assert.equal(e.previous.focused,true);assert.equal(e.getOverlay().inert,true);
 assert.equal(e.getOverlay().isConnected,true);e.flush();assert.equal(e.getOverlay().isConnected,false);
});

test('motion styles honor reduced motion and avoid table row entrance animations',()=>{
 const css=fs.readFileSync('xgenius/web/static/motion.css','utf8');
 assert.match(css,/@media\s*\(prefers-reduced-motion:reduce\)/);
 assert.match(css,/animation:\s*none\s*!important/);assert.match(css,/transition:\s*none\s*!important/);
 assert.doesNotMatch(css,/\.profiles-table\s+tr[^{}]*\{[^}]*animation:/);
 for(const duration of ['150ms','180ms','160ms','220ms'])assert.ok(css.includes(duration));
 assert.doesNotMatch(css,/@keyframes[^}]*\{[^}]*\b(?:height|width|top|left|filter|box-shadow):/);
});

test('closing during entrance starts from current opacity instead of flashing at full opacity',()=>{
 const e=environment();e.c.node=element();e.c.getComputedStyle=()=>({opacity:'0.63'});
 e.run('Motion.enter(node,"dialog");Motion.exit(node)');
 assert.equal(e.c.node.properties['--motion-exit-opacity'],'0.63');assert.equal(e.c.node.inert,true);
 e.flush();
});
