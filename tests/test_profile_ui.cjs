const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({console, Set, FormData: class {},
  document: {addEventListener(){}}, setTimeout(){},
  I18N:{error:x=>x}, t:(key, args)=>key + JSON.stringify(args||{}), I:()=>'<svg></svg>'});
for (const name of ['profile-management.js','workspace-operations.js','app.js'])
  vm.runInContext(fs.readFileSync('xgenius/web/static/'+name,'utf8'), context);
const run = source=>vm.runInContext(source,context);
run(`S.data={accounts:[
  {username:'alice',group:'Work',proxy:'host:80',proxy_status:'ok',proxy_ip:'8.8.8.8',proxy_location:{country_code:'US',country:'United States',region:'Florida'}},
  {username:'bob',group:'Personal',proxy:'host:80',proxy_status:'error'},
  {username:'carol',group:'Work',proxy:'',has_browser:true}
]};`);
run(`S.q='Florida'`);
assert.equal(run(`filteredRows().map(a=>a.username).join(',')`),'alice','search geography');
run(`S.q='USA'`);
assert.equal(run(`filteredRows().map(a=>a.username).join(',')`),'alice','search visible country label');
run(`S.q='';S.group='Work';S.proxyFilter='ok'`);
assert.equal(run(`filteredRows().map(a=>a.username).join(',')`),'alice','combined filters');
run(`selectFiltered()`);
assert.equal(run(`[...S.selected].join(',')`),'alice','select only matching profiles');
assert.equal(run(`category({opening:true,status_reason:'PREVIOUS ERROR'})`),'busy','transient state wins');
assert.match(run(`proxyCell(S.data.accounts[0])`), /flags\/us\.svg/,'real Windows-compatible flag');
assert.match(run(`proxyCell(S.data.accounts[0])`), /USA/);
assert.match(run(`proxyCell(S.data.accounts[0])`), /Florida/);
assert.doesNotMatch(run(`proxyCell({username:'bad',proxy_status:'error',proxy_location:{country_code:'US',region:'Florida'}})`), /Florida/,'no stale location on failure');
run(`globalThis.notices=[];toast=(...a)=>notices.push(a);notifyLaunchFailures({accounts:[{username:'alice',launch_error:'Proxy failed'}]});`);
assert.equal(run(`notices.length`),0,'initial state does not replay historical failures');
run(`notifyLaunchFailures({accounts:[{username:'alice',opening:true,launch_error:''}]});notifyLaunchFailures({accounts:[{username:'alice',launch_error:'Proxy failed'}]});`);
assert.equal(run(`notices.length`),1,'launch failure notifies once');
run(`notifyLaunchFailures({accounts:[{username:'alice',launch_error:'Proxy failed'}]});`);
assert.equal(run(`notices.length`),1);
run(`notifyJob({id:'job',kind:'import',status:'running'});notifyJob({id:'job',kind:'import',status:'completed',errors:2});`);
assert.equal(run(`notices.length`),2,'partial transfer notifies');
assert.equal(run(`notices[1][1]`),'warn');
assert.equal(run(`typeof notices[1][3].run`),'function','notification links to report');
run(`notifyJob({id:'job',kind:'import',status:'completed',errors:2});`);
assert.equal(run(`notices.length`),2,'completed jobs notify once');
run(`notifyLaunchFailures({accounts:[{username:'alice',launch_error:'Proxy failed',launch_error_seq:2}]});`);
assert.equal(run(`notices.length`),3,'a repeated fast failure notifies even if opening state was not observed');
console.log('Profile UI behavior checks passed');
(async()=>{
  context.fetch=async()=>({ok:true,status:202,json:async()=>({id:'fast-job',kind:'export',status:'completed'})});
  await run(`api('POST','/api/profiles/export',{})`);
  assert.equal(run(`S.seenJobs.has('fast-job')`),true,'fast jobs are tracked from creation response');
  let requests=0;
  context.fetch=async()=>{requests++;return {ok:true,status:200,json:async()=>({ok:true,ip:'8.8.8.8'})};};
  run(`renderTable=()=>{};refreshState=async()=>{};globalThis.first=checkProxy('join');globalThis.second=checkProxy('join',{silent:true});`);
  assert.equal(await run(`second`),await run(`first`),'batch joins a running check');
  assert.equal(requests,1,'joining checks share the request');
})().catch(error=>{console.error(error);process.exitCode=1;});
