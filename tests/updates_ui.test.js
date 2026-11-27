'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

function environment({pending=true,notes='## Added\n- Scrolling notes\n- Offline access',release=null,keepClosedConnected=false,history=[],historyError=null}={}){
 const events=new Map(),calls=[],dialogs=[],toasts=[];
 let data={configured:true,current_version:'2026.11.23.3',status:'current',release,
  installed_release:{version:'2026.11.23.3',notes,pending}};
 const banner={classList:{toggle(){}},innerHTML:''};
 const escape=value=>String(value).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
 const c=vm.createContext({console,setInterval(){},document:{addEventListener:(name,handler)=>events.set(name,handler)},
  $:(selector,root)=>selector==='#update-banner'?banner:root.elements[selector],I:()=>'',esc:escape,t:key=>key,
  I18N:{error:value=>value},toast:(...args)=>toasts.push(args),api:async(method,path,body)=>{
   calls.push({method,path,body});if(path==='/api/updates/history'){if(historyError)throw historyError;return {releases:structuredClone(history)};}if(path.endsWith('/seen'))data.installed_release.pending=false;
   return structuredClone(data);
  },Dialogs:{open(options){
   const elements={'.modal-body':{scrollTop:0},'[data-installed-notes]':{innerHTML:''},
    '[data-update-body]':{innerHTML:'',insertAdjacentHTML(_,html){this.innerHTML=html+this.innerHTML;}}};
   const d={options,el:{isConnected:true,elements},body:{elements},close(){this.closed=true;if(!keepClosedConnected)this.el.isConnected=false;options.onClose?.();}};
   dialogs.push(d);return d;
  }}});
 vm.runInContext(fs.readFileSync('xgenius/web/static/updates.js','utf8'),c);
 return {events,calls,dialogs,toasts,start:()=>events.get('DOMContentLoaded')(),
  show:()=>vm.runInContext('Updates.show()',c),history:()=>vm.runInContext('Updates.history()',c),click:selector=>events.get('click')({target:{closest:s=>s===selector?{}:null}})};
}

test('a newly installed version opens full screen, maximizes once and stays open until dismissed',async()=>{
 const e=environment();await e.start();assert.equal(e.dialogs.length,1);
 const d=e.dialogs[0];assert.equal(d.options.fullscreen,true);
 assert.equal(e.calls.filter(c=>c.path.endsWith('/open')).length,1);
 assert.equal(e.calls.filter(c=>c.path.endsWith('/seen')).length,0);
 assert.match(d.body.elements['[data-installed-notes]'].innerHTML,/<li>Scrolling notes<\/li>/);
 await d.options.buttons[0].onClick(d);
 assert.equal(d.el.isConnected,false);
 assert.equal(e.calls.filter(c=>c.path.endsWith('/seen')).length,1);
 assert.equal(e.calls.at(-1).body.version,'2026.11.23.3');
 await e.show();assert.equal(e.dialogs.filter(d=>d.options.fullscreen).length,1);
});

test('acknowledged notes stay hidden on startup and can be reopened from Updates',async()=>{
 const e=environment({pending:false});await e.start();assert.equal(e.dialogs.length,0);
 await e.show();assert.match(e.dialogs[0].body.elements['[data-update-body]'].innerHTML,/data-update-notes/);
 e.click('[data-update-notes]');assert.equal(e.dialogs.length,2);assert.equal(e.dialogs[1].options.fullscreen,true);
 assert.equal(e.calls.filter(c=>c.path.endsWith('/open')).length,0);
});

test('release content is escaped, and relocalizing keeps the reading position',async()=>{
 const e=environment({notes:'## <img src=x onerror=alert(1)>\n- <script>bad()</script>\n\nA paragraph'});
 await e.start();const d=e.dialogs[0],body=d.body.elements['[data-installed-notes]'];
 assert.doesNotMatch(body.innerHTML,/<img|<script>/);assert.match(body.innerHTML,/&lt;script&gt;/);
 d.el.elements['.modal-body'].scrollTop=420;e.events.get('languagechange')();
 assert.equal(d.el.elements['.modal-body'].scrollTop,420);
});

test('available release preview uses readable headings and lists without trusting remote HTML',async()=>{
 const e=environment({pending:false,release:{version:'2026.11.23.5',size:100,page_url:'https://github.com/mur3r/XAnty/releases',notes:'## <img src=x>\n- <script>bad()</script>\n\nA paragraph'}});
 await e.start();await e.show();
 const html=e.dialogs[0].body.elements['[data-update-body]'].innerHTML;
 assert.match(html,/release-preview/);assert.match(html,/<h3>&lt;img/);assert.match(html,/<li>&lt;script/);
 assert.doesNotMatch(html,/<img|<script>/);assert.match(html,/data-update-check/);
});

test('updates reopen immediately while the old dialog is finishing its exit animation',async()=>{
 const e=environment({pending:false,keepClosedConnected:true});await e.start();await e.show();
 const old=e.dialogs[0];old.close();assert.equal(old.el.isConnected,true);assert.equal(old.closed,true);
 await e.show();assert.equal(e.dialogs.length,2);assert.notEqual(e.dialogs[1],old);
});


test('startup shows only latest notes; older releases load only when history is requested',async()=>{
 const e=environment({notes:'## Latest\n- Current change',history:[
  {version:'2026.11.23.3',notes:'## Latest\n- Current change'},
  {version:'2026.11.23.2',published_at:'2026-11-23T10:00:00Z',notes:'## Older\n- <script>older change</script>'}]});
 await e.start();assert.equal(e.calls.some(c=>c.path.endsWith('/history')),false);
 const popup=e.dialogs[0].body.elements['[data-installed-notes]'].innerHTML;
 assert.match(popup,/Current change/);assert.doesNotMatch(popup,/Older|older change/);
 await Promise.all([e.history(),e.history()]);
 assert.equal(e.calls.filter(c=>c.path.endsWith('/history')).length,1);
 assert.equal(e.dialogs.length,2);const history=e.dialogs[1];
 assert.equal(history.options.title,'release_history');assert.notEqual(history.options.fullscreen,true);
 assert.match(history.options.body,/2026.11.23.2/);assert.match(history.options.body,/&lt;script&gt;older change/);
 assert.doesNotMatch(history.options.body,/<script>/);
 assert.equal(e.calls.filter(c=>c.path.endsWith('/seen')).length,0);
 history.close();await e.history();assert.equal(e.dialogs.length,3);
});

test('a failed history load leaves the current release screen usable and reports the error',async()=>{
 const e=environment({historyError:new Error('History unavailable')});await e.start();await e.history();
 assert.equal(e.dialogs.length,1);assert.equal(e.dialogs[0].el.isConnected,true);
 assert.equal(e.toasts.at(-1)[0],'History unavailable');assert.equal(e.toasts.at(-1)[1],'error');
});
