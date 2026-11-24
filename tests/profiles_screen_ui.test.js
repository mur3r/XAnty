'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

function environment(){
 const nodes=new Map(),requests=[];let formatterCount=0;
 function node(){const classes=new Set(['hidden']);return {innerHTML:'',textContent:'',value:'',disabled:false,dataset:{},
  classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x),toggle(x,on){on=on??!classes.has(x);on?classes.add(x):classes.delete(x);}},
  setAttribute(k,v){this[k]=v;},scrollTop:0,scrollLeft:0};}
 const document={activeElement:null,documentElement:{},addEventListener(){},dispatchEvent(){},querySelector:s=>nodes.get(s)||null,querySelectorAll:()=>[]};
 const c=vm.createContext({console,document,Set,Map,FormData:class{},CustomEvent:class{},Date,setTimeout,clearTimeout,setInterval(){},requests,
  Intl:{Collator:Intl.Collator,NumberFormat:function(...args){formatterCount++;return new Intl.NumberFormat(...args);}},
  navigator:{},location:{},innerWidth:1280,innerHeight:800});
 for(const name of ['icons.js','i18n.js','profile-management.js','profiles-screen.js','profile-tools.js','workspace-operations.js','app.js'])
  vm.runInContext(fs.readFileSync('xgenius/web/static/'+name,'utf8'),c,{filename:name});
 const run=code=>vm.runInContext(code,c);
 run('S.data={accounts:[]};toast=()=>{};api=async(method,path,body)=>{requests.push({method,path,body});return {ok:true};};');
 return {c,run,nodes,requests,formatterCount:()=>formatterCount,makeNode(selector){const n=node();nodes.set(selector,n);return n;}};
}

test('sorting is stable, locale aware and preserves the existing favorite-first default',()=>{
 const e=environment();e.c.rows=[{username:'a',index:2,profile_name:'Profile 10'},
  {username:'b',index:1,profile_name:'Profile 2',favorite:true,last_launch:'2026-11-22T12:00:00Z'},
  {username:'c',index:3,profile_name:'Profile 2',last_launch:'2026-11-23T12:00:00Z'}];
 assert.equal(e.run('ProfilesScreen.sort(rows).map(a=>a.username).join()'),'b,a,c');
 assert.equal(e.run('ProfilesScreen.sort(rows,"name").map(a=>a.username).join()'),'b,c,a');
 assert.equal(e.run('ProfilesScreen.sort(rows,"number").map(a=>a.username).join()'),'b,a,c');
 assert.equal(e.run('ProfilesScreen.sort(rows,"last_launch").map(a=>a.username).join()'),'c,b,a');
 assert.equal(e.c.rows.map(a=>a.username).join(),'a,b,c');
});

test('all fourteen columns and every existing row action survive the new row markup',()=>{
 const e=environment();const html=e.run('rowHTML({username:"alice",index:1,profile_name:"Alice",tags:["team","work"],proxy:"proxy.example:80"})');
 const columns=[...html.matchAll(/data-column="([^"]+)"/g)].map(m=>m[1]);
 assert.deepEqual(columns,['number','name','start','profile_status','status','proxy','auto_login','last_launch','runtime','tags','notes','group','profile_size','reminder']);
 for(const action of ['login','favorite','auto_login','export','edit','rename','history','view','proxy_check','proxy_rotate','cookies','save_session','diagnostics','folder','clear_cache','delete'])
  assert.match(html,new RegExp('data-act="'+action+'"'),action);
 assert.match(html,/profile-avatar/);assert.match(html,/data-profile-status/);assert.match(html,/data-rename/);
 assert.match(e.run('rowHTML({username:"alice",index:1,has_browser:true})'),/data-act="close"/);
 assert.match(e.run('rowHTML({username:"alice",index:1,opening:true})'),/data-act="login" disabled/);
});

test('profile names, avatar text, tags and notes are escaped and tag chips stay bounded',()=>{
 const e=environment();const html=e.run('rowHTML({username:"alice",index:1,profile_name:"<img src=x>",icon_text:"<svg>",notes:"<script>bad()</script>",tags:["<img>","b","c","d","e"]})');
 assert.doesNotMatch(html,/<img|<script>|<svg>/);assert.match(html,/&lt;img/);
 e.c.tags=Array.from({length:100},(_,i)=>'tag'+i);
 const tags=e.run('ProfilesScreen.tagsHTML(tags)');
 assert.equal((tags.match(/class="profile-tag"/g)||[]).length,3);assert.match(tags,/\+97/);assert.match(tags,/tag99/);
});

test('a five thousand profile list is filtered once per render and only the selected page is built',()=>{
 const e=environment();
 for(const selector of ['#rows','.profile-panel','#empty','#no-matches','#page-count','#page-prev','#page-next'])e.makeNode(selector);
 e.run('S.data.accounts=Array.from({length:5000},(_,i)=>({username:"profile_"+i,index:i+1,profile_name:"Profile "+i}));globalThis.passes=0;const originalFilter=filteredRows;filteredRows=()=>{passes++;return originalFilter();};renderSelection=()=>{};ProfileUI.applyColumns=()=>{};ProfilesScreen.beforeRender=()=>({});ProfilesScreen.afterRender=()=>{};ProfilesScreen.syncControls=()=>{};renderTable();');
 assert.equal(e.run('passes'),1);assert.equal((e.nodes.get('#rows').innerHTML.match(/<tr data-u=/g)||[]).length,50);
 e.run('S.pageSize=250;S.page=19;passes=0;renderTable();');
 assert.equal(e.run('passes'),1);assert.equal((e.nodes.get('#rows').innerHTML.match(/<tr data-u=/g)||[]).length,250);
 assert.match(e.nodes.get('#rows').innerHTML,/profile_4999/);
});

test('bulk requests keep known selected profiles even when current filters hide them',async()=>{
 const e=environment();e.run('S.data.accounts=[{username:"alice",group:"A"},{username:"bob",group:"B"}];S.selected=new Set(["alice","bob","deleted"]);S.group="A";');
 await e.run('TOOL_ACTIONS.close()');
 assert.equal(e.requests[0].path,'/api/actions/close');assert.deepEqual(Array.from(e.requests[0].body.usernames),['alice','bob']);
 e.run('S.selected.clear();selectFiltered();');assert.equal(e.run('[...S.selected].join()'),'alice');
});

test('pagination clamps invalid inputs and refreshes preserve both scroll coordinates',()=>{
 const e=environment();
 assert.equal(e.run('ProfilesScreen.pageIndex(999,501,50)'),10);
 assert.equal(e.run('ProfilesScreen.pageIndex(-8,501,50)'),0);
 assert.equal(e.run('ProfilesScreen.pageIndex("bad",501,50)'),0);
 assert.equal(e.run('ProfilesScreen.pageIndex(10,0,50)'),0);
 const wrap=e.makeNode('#view-profiles .table-wrap');wrap.scrollTop=180;wrap.scrollLeft=330;
 e.run('globalThis.context=ProfilesScreen.beforeRender();');wrap.scrollTop=0;wrap.scrollLeft=0;e.run('ProfilesScreen.afterRender(context)');
 assert.equal(wrap.scrollTop,180);assert.equal(wrap.scrollLeft,330);
 e.run('ProfilesScreen.afterRender(context,true)');assert.equal(wrap.scrollTop,0);assert.equal(wrap.scrollLeft,330);
});

test('loading is delayed, counts overlapping refreshes and retains a recoverable error state',async()=>{
 const e=environment(),banner=e.makeNode('#profiles-loading'),panel=e.makeNode('#view-profiles .profile-panel'),button=e.makeNode('#btn-refresh'),error=e.makeNode('#profiles-load-error');
 e.run('ProfilesScreen.loading(true);ProfilesScreen.loading(true)');assert.equal(banner.classList.contains('hidden'),true);
 await new Promise(resolve=>setTimeout(resolve,190));assert.equal(banner.classList.contains('hidden'),false);assert.equal(button.disabled,true);
 e.run('ProfilesScreen.loading(false)');assert.equal(panel['aria-busy'],'true');
 e.run('ProfilesScreen.loading(false);ProfilesScreen.loadError()');assert.equal(button.disabled,false);assert.equal(banner.classList.contains('hidden'),true);assert.equal(error.classList.contains('hidden'),false);
 e.run('ProfilesScreen.loading(true);ProfilesScreen.loading(false)');assert.equal(error.classList.contains('hidden'),true);
});

test('runtime number formatting is reused for every row and remains localized',()=>{
 const e=environment();e.run('for(let i=0;i<1000;i++)ProfileUI.runtimeHTML({runtime_seconds:3600});');assert.equal(e.formatterCount(),1);
 e.run('I18N.set("en");for(let i=0;i<250;i++)ProfileUI.runtimeHTML({runtime_seconds:1800});');assert.equal(e.formatterCount(),2);
});
