'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function environment(){
 const nodes=new Map(),events=new Map(),mediaEvents=new Map();let initializedHandlers=0;
 function node(){const classes=new Set(['hidden']);return {attrs:{},focused:false,
  classList:{contains:k=>classes.has(k),toggle(k,on){on?classes.add(k):classes.delete(k);}},
  setAttribute(k,v){this.attrs[k]=v;},focus(){this.focused=true;},addEventListener(k,fn){this[k]=fn;},
  contains(target){return target===this;}};}
 for(const id of ['btn-sidebar-toggle','btn-sidebar-close','workspace-sidebar','navigation-backdrop','screen-main','folder-search'])nodes.set('#'+id,node());
 const media={matches:true,addEventListener:(key,fn)=>mediaEvents.set(key,fn)};
 const c=vm.createContext({matchMedia:()=>media,document:{querySelector:s=>nodes.get(s),addEventListener:(key,fn,capture)=>{events.set(key,{fn,capture});initializedHandlers++;}}});
 vm.runInContext(fs.readFileSync('xgenius/web/static/interface-quality.js','utf8'),c);
 vm.runInContext('InterfaceQuality.init()',c);
 return {c,nodes,events,media,resize:()=>mediaEvents.get('change')(),handlers:()=>initializedHandlers};
}
test('compact navigation exposes folders and language with keyboard focus and expanded state',()=>{
 const e=environment();e.nodes.get('#btn-sidebar-toggle').onclick();
 assert.equal(e.nodes.get('#screen-main').classList.contains('navigation-open'),true);
 assert.equal(e.nodes.get('#btn-sidebar-toggle').attrs['aria-expanded'],'true');
 assert.equal(e.nodes.get('#navigation-backdrop').classList.contains('hidden'),false);
 assert.equal(e.nodes.get('#folder-search').focused,true);
});
test('Escape closes compact navigation before the desktop shortcut and returns focus',()=>{
 const e=environment();e.nodes.get('#btn-sidebar-toggle').onclick();
 let prevented=false,stopped=false;e.events.get('keydown').fn({key:'Escape',preventDefault(){prevented=true;},stopPropagation(){stopped=true;}});
 assert.equal(e.events.get('keydown').capture,true);assert.equal(prevented,true);assert.equal(stopped,true);
 assert.equal(e.nodes.get('#btn-sidebar-toggle').attrs['aria-expanded'],'false');assert.equal(e.nodes.get('#btn-sidebar-toggle').focused,true);
});
test('tabbing away closes the nonmodal drawer without pulling focus back',()=>{
 const e=environment();e.nodes.get('#btn-sidebar-toggle').onclick();
 e.events.get('focusin').fn({target:{}});
 assert.equal(e.nodes.get('#btn-sidebar-toggle').attrs['aria-expanded'],'false');
 assert.equal(e.nodes.get('#btn-sidebar-toggle').focused,false);
});
test('folder choice, backdrop, viewport changes and repeated initialization stay predictable',()=>{
 const e=environment(),toggle=e.nodes.get('#btn-sidebar-toggle');
 toggle.onclick();e.nodes.get('#workspace-sidebar').click({target:{closest:()=>({})}});assert.equal(toggle.attrs['aria-expanded'],'false');
 toggle.onclick();e.nodes.get('#navigation-backdrop').onclick();assert.equal(toggle.attrs['aria-expanded'],'false');
 toggle.onclick();e.media.matches=false;e.resize();assert.equal(toggle.attrs['aria-expanded'],'true');
 const before=e.handlers();vm.runInContext('InterfaceQuality.init()',e.c);assert.equal(e.handlers(),before);
});
test('accessible labels are localized in all three supported languages',()=>{
 const target={dataset:{i18nAriaLabel:'select_page'},setAttribute(_,value){this.label=value;}};
 const document={documentElement:{},dispatchEvent(){},querySelectorAll:s=>s==='[data-i18n-aria-label]'?[target]:[]};
 const c=vm.createContext({document,CustomEvent:class{}});
 vm.runInContext(fs.readFileSync('xgenius/web/static/i18n.js','utf8'),c);
 const labels=[];for(const lang of ['ru','en','uk']){vm.runInContext('I18N.set("'+lang+'")',c);labels.push(target.label);}
 assert.equal(new Set(labels).size,3);for(const label of labels)assert.ok(label&&label!=='select_page');
});


test('desktop panel collapse persists and keeps selected folders visible again after expansion',async()=>{
 const e=environment();e.media.matches=false;e.resize();e.c.S={preferences:{}};
 const calls=[];e.c.api=async(method,path,body)=>{calls.push({method,path,body});return body;};
 const toggle=e.nodes.get('#btn-sidebar-toggle'),sidebar=e.nodes.get('#workspace-sidebar');
 await toggle.onclick();assert.equal(e.nodes.get('#screen-main').classList.contains('folders-collapsed'),true);
 assert.equal(sidebar.inert,true);assert.equal(toggle.attrs['aria-expanded'],'false');
 assert.equal(calls[0].body.folders_collapsed,true);assert.equal(e.c.S.preferences.folders_collapsed,true);
 await toggle.onclick();assert.equal(sidebar.inert,false);assert.equal(toggle.attrs['aria-expanded'],'true');
 assert.equal(calls[1].body.folders_collapsed,false);
});

test('restoring preferences survives resizing through compact mode and a failed save restores the panel',async()=>{
 const e=environment();e.events.get('appearancechange').fn({detail:{folders_collapsed:true}});
 e.media.matches=false;e.resize();assert.equal(e.nodes.get('#screen-main').classList.contains('folders-collapsed'),true);
 e.media.matches=true;e.resize();await e.nodes.get('#btn-sidebar-toggle').onclick();
 assert.equal(e.nodes.get('#screen-main').classList.contains('navigation-open'),true);
 e.media.matches=false;e.resize();assert.equal(e.nodes.get('#screen-main').classList.contains('folders-collapsed'),true);
 e.c.api=async()=>{throw Error('Cannot save');};
 await e.nodes.get('#btn-sidebar-toggle').onclick();
 assert.equal(e.nodes.get('#screen-main').classList.contains('folders-collapsed'),true);
 assert.equal(e.nodes.get('#btn-sidebar-toggle').disabled,false);
});
