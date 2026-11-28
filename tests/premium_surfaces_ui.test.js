'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

function environment(){
 const elements=new Map();
 const document={activeElement:null,documentElement:{},addEventListener(){},dispatchEvent(){},querySelector:s=>elements.get(s)||null,querySelectorAll:()=>[]};
 const c=vm.createContext({console,document,Date,Intl,Set,Map,FormData:class{},CustomEvent:class{},setTimeout(){},setInterval(){}});
 for(const name of ['icons.js','i18n.js','profile-management.js','profiles-screen.js','profile-tools.js','workspace-operations.js','app.js','dialogs.js']){
  let source=fs.readFileSync('xgenius/web/static/'+name,'utf8');
  // Expose only the private rendering/serialization functions inside this test VM.
  if(name==='dialogs.js')source=source.replace('return {open,confirm,','return {accountFields,formData,open,confirm,');
  vm.runInContext(source,c,{filename:name});
 }
 return {c,document,elements,run:code=>vm.runInContext(code,c)};
}
const fields=['user_agent_mode','user_agent','profile_name','username','group','profile_status','tags','favorite','notes','important','reminder_at','reminder_note','proxy','proxy_protocol','proxy_rotation_url','password','auth_token','ct0_token','auto_login','restore_tabs','extension_set','icon_text','block_images','block_media','block_fonts','phishing_protection','browser_language','browser_timezone','window_width','window_height'];

test('the grouped editor retains all 30 unique controls, constraints and safe defaults',()=>{
 const e=environment(),html=e.run('Dialogs.accountFields()');
 const names=[...html.matchAll(/\bname="([^"]+)"/g)].map(m=>m[1]);
 assert.deepEqual([...names].sort(),[...fields].sort());assert.equal(new Set(names).size,30);
 assert.match(html,/name="username"[^>]*required[^>]*pattern="\[A-Za-z0-9_\]\{1,32\}"/);
 assert.match(html,/name="proxy_rotation_url" type="url"[^>]*maxlength="8192"/);
 for(const name of ['restore_tabs','phishing_protection'])assert.match(html,new RegExp('name="'+name+'" checked'));
 for(const value of ['active','new','review','unused'])assert.match(html,new RegExp('option value="'+value+'"'));
 assert.match(html,/name="window_width"[^>]*min="800" max="3840"/);
 assert.match(html,/name="window_height"[^>]*min="600" max="2160"/);
});

test('grouped editor preserves stored values including opt-outs and escapes user content in every locale',()=>{
 const e=environment();e.c.account={username:'qa',profile_name:'<img src=x>',notes:'<script>bad()</script>',tags:['<b>','work'],proxy_rotation_url:'https://provider.example/rotate?key=a&b=c',restore_tabs:false,phishing_protection:false,auto_login:true,window_width:1600,window_height:900,extension_set:'portable-demo',icon_text:'"<svg>'};
 for(const lang of ['ru','en','uk']){
  e.c.lang=lang;e.run('I18N.set(lang)');const html=e.run('Dialogs.accountFields(account)');
  assert.doesNotMatch(html,/<img|<script>|<svg>/);assert.match(html,/&lt;img/);
  assert.doesNotMatch(html,/name="(?:restore_tabs|phishing_protection)" checked/);
  assert.match(html,/name="auto_login" checked/);assert.match(html,/value="1600"/);assert.match(html,/value="portable-demo" selected/);
  for(const key of ['ui_identity','ui_organization','ui_network','ui_session','ui_browser_behavior'])assert.notEqual(e.run(`t('${key}')`),key);
 }
});

test('editor serialization keeps the established wire format and UTC reminder conversion',()=>{
 const e=environment();
 e.c.form={querySelectorAll:()=>[{name:'username',type:'text',value:'qa'},{name:'auto_login',type:'checkbox',checked:true},{name:'restore_tabs',type:'checkbox',checked:false},{name:'reminder_at',type:'datetime-local',value:'2026-11-23T14:30'},{name:'proxy_rotation_url',type:'url',value:'https://provider.example/rotate'}]};
 const result=e.run('Dialogs.formData({body:form})');
 assert.equal(result.username,'qa');assert.equal(result.auto_login,true);assert.equal(result.restore_tabs,false);
 assert.equal(result.reminder_at,new Date('2026-11-23T14:30').toISOString());assert.equal(result.proxy_rotation_url,'https://provider.example/rotate');
 assert.equal(Object.keys(result).length,5);
});

test('monitoring retains two bounded history series, all metrics and CSV account columns',()=>{
 const e=environment();
 for(const selector of ['#metrics','#load-chart','#load-accounts'])e.elements.set(selector,{innerHTML:''});
 e.c.sample={cpu:{total:32},mem:{used_gb:8,total_gb:16,pct:50},chrome:{rss_gb:1.2},loop_lag_ms:3,accounts:[{username:'<img src=x>',procs:5,threads:20,cpu:2,rss_mb:180}]};
 e.run('for(let i=0;i<150;i++)acceptMetrics(sample);renderMetrics();');
 assert.equal(e.run('S.history.length'),100);
 assert.equal((e.elements.get('#load-chart').innerHTML.match(/<polyline/g)||[]).length,2);
 assert.equal((e.elements.get('#metrics').innerHTML.match(/class="metric"/g)||[]).length,4);
 const table=e.elements.get('#load-accounts').innerHTML;
 assert.equal((table.match(/<th>/g)||[]).length,5);assert.doesNotMatch(table,/<img/);assert.match(table,/&lt;img/);
});

function uploadEnvironment(){
 const requests=[];
 class Request {
  constructor(){this.upload={};requests.push(this);}
  open(method,path){this.method=method;this.path=path;}
  send(body){this.body=body;}
 }
 class Fields {constructor(){this.values=[];}append(...args){this.values.push(args);}}
 const c=vm.createContext({console,FormData:Fields,XMLHttpRequest:Request,S:{seenJobs:new Set()},
  document:{documentElement:{},addEventListener(){},querySelectorAll:()=>[],dispatchEvent(){}},CustomEvent:class{}});
 vm.runInContext(fs.readFileSync('xgenius/web/static/i18n.js','utf8'),c);
 const source=fs.readFileSync('xgenius/web/static/dialogs.js','utf8').replace('return {open,confirm,','return {uploadPackage,open,confirm,');
 vm.runInContext(source,c);
 return {c,requests,run:code=>vm.runInContext(code,c)};
}

test('profile upload sends exact original size and switches to verification after transfer',async()=>{
 const e=uploadEnvironment(),stages=[];e.c.file={size:1253959786};e.c.progress=(...values)=>stages.push(values);
 const pending=e.run('Dialogs.uploadPackage(file,"rename",progress)'),xhr=e.requests[0];
 assert.equal(xhr.method,'POST');assert.equal(xhr.path,'/api/profiles/import');
 assert.equal(xhr.body.values[1][0],'file_size');assert.equal(xhr.body.values[1][1],'1253959786');
 assert.equal(xhr.body.values[2][1],e.c.file);
 xhr.upload.onprogress({lengthComputable:true,loaded:30,total:100});
 xhr.upload.onprogress({lengthComputable:true,loaded:100,total:100});xhr.upload.onload();
 assert.deepEqual(stages,[[30,false],[100,true],[100,true]]);
 xhr.status=202;xhr.response={id:'new-job'};xhr.onload();
 assert.equal((await pending).id,'new-job');assert.ok(e.c.S.seenJobs.has('new-job'));
});

test('corrupt archive errors remain rejected and actionable in every interface language',async()=>{
 const e=uploadEnvironment();e.c.file={size:100};e.c.progress=()=>{};
 const pending=e.run('Dialogs.uploadPackage(file,"rename",progress)'),xhr=e.requests[0];
 xhr.status=400;xhr.response={error:'Profile package integrity check failed: corrupt ZIP data'};xhr.onload();
 await assert.rejects(pending,/corrupt ZIP data/);assert.equal(e.c.S.seenJobs.size,0);
 for(const lang of ['ru','en','uk']){
  e.c.lang=lang;e.run('I18N.set(lang)');
  for(const message of ['Profile package integrity check failed: corrupt ZIP data',
   'Profile package integrity checksum mismatch. Export the profiles again.']){
   e.c.message=message;const translated=e.run('I18N.error(message)');
   assert.equal(translated,e.run('t("package_damaged")'));assert.ok(translated.includes('XAnty'));
   assert.doesNotMatch(translated,/corrupt ZIP|checksum mismatch/);
  }
  for(const key of ['package_checking','verifying_export','import_package_intro'])assert.notEqual(e.run(`t('${key}')`),key);
  assert.equal(e.run('I18N.error("Profile package upload is incomplete. Choose the original file and try again.")'),e.run('t("package_upload_incomplete")'));
 }
});


test('UA editor exposes auto/manual generation and escapes imported values',()=>{
 const e=environment();e.c.profile={user_agent_mode:'manual',user_agent:'<script>private()</script>'};
 const html=e.run('ProfileTools.userAgentFields(profile)');
 assert.match(html,/name="user_agent_mode"/);assert.match(html,/data-ua-generate/);assert.match(html,/data-ua-copy/);
 assert.doesNotMatch(html,/<script>/);assert.match(html,/&lt;script&gt;/);
 assert.match(e.run('rowHTML({username:"qa",profile_name:"QA"})'),/data-act="copy_user_agent"/);
 assert.equal(e.run('typeof ROW_ACTIONS.copy_user_agent'),'function');assert.equal(e.run('typeof ROW_ACTIONS.user_agent'),'function');
});

test('quick UA copy fetches the current profile value and never copies an unavailable identity',async()=>{
 const e=environment(),copied=[],paths=[],messages=[];
 e.c.navigator={clipboard:{writeText:async value=>copied.push(value)}};
 e.c.testApi=async(method,path)=>{paths.push(path);return e.c.identity;};e.c.messages=messages;
 e.run('api=testApi;toast=(...args)=>messages.push(args)');
 e.c.identity={available:true,user_agent:'native Chromium UA',source:'live'};
 await e.run('ProfileTools.copyUserAgent("qa name")');
 assert.deepEqual(copied,['native Chromium UA']);assert.equal(paths[0],'/api/accounts/qa%20name/tools/user_agent');
 e.c.identity={available:false,error:'The Chromium version is unavailable. Install or select a compatible browser first.'};
 await e.run('ProfileTools.copyUserAgent("qa")');assert.equal(copied.length,1);assert.equal(messages.at(-1)[1],'error');
});
