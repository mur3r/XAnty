'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

function environment(){
 const c=vm.createContext({console,Date,Set,Map,Intl,FormData:class{},setTimeout(){},setInterval(){},
  document:{addEventListener(){}},S:{preferences:{},jobs:[]},
  rows:[],accounts:()=>c.rows,selectedNames:()=>[],
  esc:v=>String(v??'').replace(/[&<>"']/g,x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x])),
  I:()=>'<svg></svg>',t:(key,values={})=>key+Object.values(values).join(' '),
  I18N:{language:'en',error:x=>x},ProfileUI:{date:x=>x||'—'}});
 vm.runInContext(fs.readFileSync('xgenius/web/static/workspace-operations.js','utf8'),c);
 return {c,run:code=>vm.runInContext(code,c)};
}

test('important and favorite profiles both require typed protection',()=>{
 const {run}=environment();
 assert.equal(run('WorkspaceOps.isProtected([{important:true}])'),true);
 assert.equal(run('WorkspaceOps.isProtected([{favorite:true}])'),true);
 assert.equal(run('WorkspaceOps.isProtected([{important:false,favorite:false}])'),false);
});

test('settings-only exports remove all five secret-bearing categories',()=>{
 const {run}=environment();
 assert.deepEqual(JSON.parse(run('JSON.stringify(WorkspaceOps.exportPrivacy(true))')),
  {include_passwords:false,include_tokens:false,include_cookies:false,include_proxy_credentials:false,include_browser_data:false});
 assert.equal(run('WorkspaceOps.exportPrivacy(false)'),undefined);
});

test('reminder input preserves local wall time and saves an explicit UTC instant',()=>{
 const {run}=environment();
 const wall='2026-11-22T12:30';
 assert.equal(run(`WorkspaceOps.toUTC('${wall}')`),new Date(2026,10,22,12,30).toISOString());
 assert.equal(run(`WorkspaceOps.toLocalDateTime('${new Date(2026,10,22,12,30).toISOString()}')`),wall);
 assert.equal(run('WorkspaceOps.toUTC("")'),null);
 assert.equal(run('WorkspaceOps.toLocalDateTime("invalid")'),'');
});

test('workspace renders selections, damaged fallback, backup status and escaped diagnostics',()=>{
 const {c,run}=environment();
 c.state={chromium:{selected:'bundled',requested_selected:'130.0.1.1',selection_error:'damaged',installed:[{version:'bundled',selected:true,available:false},{version:'130.0.1.1',valid:false,available:false}]},
  backups:{directory:'D:\\Backups',interval_hours:24,keep:7,last_status:'completed',last_result:{path:'D:\\Backups\\a.xanty'}},
  window_sets:[{id:'abc',name:'<script>bad</script>',usernames:['alice'],missing:[]}],
  errors:[{username:'alice',profile_name:'<img onerror=bad>',category:'proxy',detail:'<script>error</script>'}]};
 c.rows=[{username:'alice',profile_name:'Alice',reminder_at:'2020-01-01T00:00:00Z',reminder_note:'<b>Reminder</b>',profile_size:{bytes:1073741824}}];
 const html=run('WorkspaceOps.panelHTML(state)');
 assert.match(html,/ops_cft_fallback/);
 assert.match(html,/ops_backup_status_completed/);
 assert.match(html,/ops_fix_proxy/);
 assert.match(html,/&lt;script&gt;bad/);
 assert.match(html,/&lt;b&gt;Reminder/);
 assert.doesNotMatch(html,/<script>|<img onerror/);
 assert.match(html,/data-op="chromium-delete"[^>]*disabled/,'selected bundled cannot be deleted');
 assert.match(html,/data-op="chromium-select" data-version="bundled"\s*>/,'broken requested selection can be explicitly reset to bundled');
 assert.match(html,/data-op="chromium-delete" data-version="130\.0\.1\.1"[^>]*disabled/,'saved selection remains protected while falling back');
});

test('opening the errors shortcut waits for the shared workspace load before focusing',async()=>{
 const {c,run}=environment();
 const root={innerHTML:''};let complete,scrolled=false;
 const result=new Promise(resolve=>{complete=resolve;});
 c.$=selector=>selector==='#workspace-panel'?root:selector==='#ops-errors'&&root.innerHTML.includes('id="ops-errors"')?{scrollIntoView(){scrolled=true;}}:null;
 c.$$=()=>[];c.api=()=>result;
 c.setTab=()=>{c.S.tab='workspace';run('WorkspaceOps.load()');};
 const focus=run('WorkspaceOps.focusCard("errors")');
 await Promise.resolve();await Promise.resolve();
 assert.equal(scrolled,false);
 complete({});
 await focus;
 assert.equal(scrolled,true);
});

test('export request sends the privacy policy and full export omits it',async()=>{
 const {c,run}=environment();
 vm.runInContext(fs.readFileSync('xgenius/web/static/app.js','utf8').replace('const S = ','const AppState = '),c);
 c.requests=[];
 run('api=async(method,path,body)=>{requests.push({method,path,body});return {id:"job"};};refreshJobs=async()=>{};S.autoDownloads=new Set();globalThis.Dialogs={showJob(){}};');
 await run('startExport(["alice"],false,true)');
 assert.equal(c.requests[0].path,'/api/profiles/export');
 assert.equal(c.requests[0].body.privacy.include_browser_data,false);
 assert.equal(c.requests[0].body.privacy.include_tokens,false);
 await run('startExport([],true,false)');
 assert.equal(c.requests[1].body.all,true);
 assert.equal(Object.hasOwn(c.requests[1].body,'privacy'),false);
});

test('all page scripts load with the workspace routes callable',()=>{
 const c=vm.createContext({console,document:{addEventListener(){}},setInterval(){},setTimeout(){}});
 const html=fs.readFileSync('xgenius/web/static/index.html','utf8');
 for(const m of html.matchAll(/<script src="([^"]+)"><\/script>/g))vm.runInContext(fs.readFileSync('xgenius/web/static/'+m[1],'utf8'),c,{filename:m[1]});
 for(const name of ['workspace','workspace_errors'])assert.equal(vm.runInContext(`typeof TOOL_ACTIONS.${name}`,c),'function');
 for(const name of ['load','editReminder','exportDialog','jobHTML'])assert.equal(vm.runInContext(`typeof WorkspaceOps.${name}`,c),'function');
});


function transferEnvironment(){
 const e=environment(),nodes=new Map();let options;
 e.c.$=selector=>nodes.get(selector);
 e.c.selectedNames=()=>['alice'];e.c.rows=Array.from({length:145},(_,i)=>({username:'qa_'+i}));
 e.c.calls=[];e.c.startExport=(...args)=>e.c.calls.push(args);
 e.c.captureOpen=value=>{
  options=value;nodes.clear();
  const checkbox={checked:/name="settings_only"[^>]*\bchecked\b/.test(value.body)};
  nodes.set('[name=settings_only]',checkbox);
  nodes.set('[name=export_directory]',{value:e.c.S.preferences.export_directory||'',focus(){}});
  nodes.set('[data-pick-export-directory]',{});
  for(const selector of ['[data-export-selected]','[data-export-all]','[data-import-package]','[data-export-private]'])
   nodes.set(selector,{hidden:false,classList:{toggle(_,hidden){nodes.get(selector).hidden=hidden;}}});
  return {body:{},close(){}};
 };
 const source=fs.readFileSync('xgenius/web/static/dialogs.js','utf8')
  .replace('function open({','function originalOpen({')
  .replace(' let jobDialog=null;',' function open(options){return captureOpen(options);} let jobDialog=null;');
 vm.runInContext(source,e.c);
 return {...e,nodes,options:()=>options};
}

test('the transfer dialog defaults to complete sessions for both all and selected profiles',()=>{
 const e=transferEnvironment();e.run('Dialogs.transfer()');
 assert.equal(e.nodes.get('[name=settings_only]').checked,false);
 assert.doesNotMatch(e.options().body,/notice warning hidden[^>]*data-export-private/);
 e.nodes.get('[data-export-all]').onclick();
 assert.deepEqual(JSON.parse(JSON.stringify(e.c.calls[0])),[[],true,false,'']);
 e.nodes.get('[data-export-selected]').onclick();
 assert.deepEqual(JSON.parse(JSON.stringify(e.c.calls[1])),[['alice'],false,false,'']);
});

test('the row and bulk export dialog also defaults to complete transfer; a template is explicit',async()=>{
 const e=transferEnvironment();e.run('WorkspaceOps.exportDialog(["alice"])');
 const checkbox=e.nodes.get('[name=settings_only]');assert.equal(checkbox.checked,false);
 await e.options().buttons.at(-1).onClick({close(){}});
 assert.equal(e.c.calls[0][2],false);
 checkbox.checked=true;checkbox.onchange({target:checkbox});
 assert.equal(e.nodes.get('[data-export-private]').hidden,true);
 await e.options().buttons.at(-1).onClick({close(){}});
 assert.equal(e.c.calls[1][2],true);
});


test('both export entry points carry the chosen folder and the native chooser runs only on a click',async()=>{
 const e=transferEnvironment();e.c.S.preferences.export_directory='C:/Previous';let calls=0;
 e.c.window={pywebview:{api:{choose_folder:async initial=>{calls++;assert.equal(initial,'C:/Previous');return 'D:/Transfers';}}}};
 e.run('Dialogs.transfer()');assert.equal(calls,0);
 await e.nodes.get('[data-pick-export-directory]').onclick();assert.equal(calls,1);
 e.nodes.get('[data-export-all]').onclick();assert.equal(e.c.calls.at(-1)[3],'D:/Transfers');
 e.run('WorkspaceOps.exportDialog(["alice"])');e.nodes.get('[name=export_directory]').value='D:/Selected';
 await e.options().buttons.at(-1).onClick({close(){}});assert.equal(e.c.calls.at(-1)[3],'D:/Selected');
});

test('explicit export destinations reach the API without changing profile selection',async()=>{
 const {c,run}=environment();vm.runInContext(fs.readFileSync('xgenius/web/static/app.js','utf8').replace('const S = ','const AppState = '),c);
 c.requests=[];run('api=async(method,path,body)=>{requests.push({method,path,body});return {id:"job"};};refreshJobs=async()=>{};S.autoDownloads=new Set();globalThis.Dialogs={showJob(){}};');
 await run('startExport(["alice"],false,false,"D:/Transfers")');assert.equal(c.requests[0].body.export_directory,'D:/Transfers');
});


test('a package saved to the chosen folder is not downloaded a second time',async()=>{
 const {c,run}=environment();vm.runInContext(fs.readFileSync('xgenius/web/static/app.js','utf8').replace('const S = ','const AppState = '),c);
 c.downloads=[];
 run('S.jobs=[];S.autoDownloads=new Set(["saved","normal"]);globalThis.Dialogs={updateJob:async()=>{}};WorkspaceOps.jobsUpdated=()=>{};renderJobs=()=>{};notifyJob=()=>{};refreshState=async()=>{};downloadURL=url=>downloads.push(url);api=async()=>({jobs:[{id:"saved",status:"completed",download_ready:true,saved_path:"D:/Transfers/file.xanty"},{id:"normal",status:"completed",download_ready:true}]});');
 await run('refreshJobs()');assert.equal(c.downloads.length,1);assert.equal(c.downloads[0],'/api/profiles/download/normal');
 assert.equal(run('S.autoDownloads.size'),0);
});
