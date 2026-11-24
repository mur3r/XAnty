'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function environment({modal=false,closing=false,menus=[],bridge=true}={}){
 const events=new Map(),calls=[];let done;
 const c=vm.createContext({console,Promise,window:bridge?{pywebview:{api:{hide:()=>{calls.push('hide');return new Promise(resolve=>{done=resolve;});}}}}:{},
  document:{addEventListener:(name,handler)=>events.set(name,handler),
   querySelector:selector=>selector.includes('modal')&&(modal||(closing&&!selector.includes(':not([inert])')))?{}:null,
   querySelectorAll:()=>menus}});
 const file='xgenius/web/static/desktop-shortcuts.js';
 if(fs.existsSync(file))vm.runInContext(fs.readFileSync(file,'utf8'),c);
 function press(overrides={}){const handler=events.get('keydown');assert.equal(typeof handler,'function','desktop Esc handler is registered');const e={key:'Escape',defaultPrevented:false,repeat:false,isComposing:false,preventDefault(){this.defaultPrevented=true;},...overrides};e.completion=handler(e);return e;}
 return {press,calls,finish:()=>done?.(true)};
}
test('Esc hides the desktop once until the native call completes',async()=>{
 const e=environment();const first=e.press();e.press();assert.deepEqual(e.calls,['hide']);e.finish();await first.completion;const next=e.press();assert.deepEqual(e.calls,['hide','hide']);e.finish();await next.completion;
});
test('dialogs, consumed Escape and modified shortcuts keep normal behavior',()=>{
 const modal=environment({modal:true});modal.press();assert.deepEqual(modal.calls,[]);
 for(const overrides of [{defaultPrevented:true},{ctrlKey:true},{altKey:true},{shiftKey:true},{metaKey:true},{repeat:true},{isComposing:true},{key:'Enter'}]){
  const e=environment();e.press(overrides);assert.deepEqual(e.calls,[],JSON.stringify(overrides));
 }
});
test('Escape closes an open row menu before hiding and ordinary web mode stays usable',()=>{
 const menu={open:true};const e=environment({menus:[menu]});e.press();assert.equal(menu.open,false);assert.deepEqual(e.calls,[]);
 const web=environment({bridge:false});assert.equal(web.press().defaultPrevented,false);assert.deepEqual(web.calls,[]);
});

test('an inert closing dialog does not delay the next desktop Escape shortcut',async()=>{
 const e=environment({closing:true});const key=e.press();assert.deepEqual(e.calls,['hide']);e.finish();await key.completion;
});
