'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

function environment(){
 const calls=[],messages=[];
 let finish;
 const c=vm.createContext({console,Set,Map,Promise,document:{documentElement:{},addEventListener(){},querySelectorAll:()=>[],dispatchEvent(){}},CustomEvent:class{},setInterval(){},setTimeout(){},
  calls,messages,testRows:[{username:'alice',profile_name:'Work',proxy:'proxy.example:8080',has_proxy_rotation:true}],
  testApi:(method,path,body)=>{calls.push({method,path,body});return new Promise(resolve=>{finish=resolve;});}});
 for(const name of ['icons.js','i18n.js','profile-management.js','profiles-screen.js','profile-tools.js','workspace-operations.js','app.js'])
  vm.runInContext(fs.readFileSync('xgenius/web/static/'+name,'utf8'),c,{filename:name});
 vm.runInContext('api=testApi;renderTable=()=>{};refreshState=async()=>{};toast=(...args)=>messages.push(args);S.data={accounts:testRows};',c);
 return {c,calls,messages,run:code=>vm.runInContext(code,c),finish:result=>finish(result)};
}

test('rotation is never automatic; only profiles with a saved link expose the button',()=>{
 const e=environment();assert.equal(e.calls.length,0);
 assert.match(e.run('proxyCell(testRows[0])'),/data-act="proxy_rotate"/);
 assert.doesNotMatch(e.run('proxyCell({...testRows[0],has_proxy_rotation:false})'),/data-act="proxy_rotate"/);
});

test('double clicks share one request and disable both proxy actions until it completes',async()=>{
 const e=environment(),first=e.run('rotateProxy("alice")'),second=e.run('rotateProxy("alice")');
 assert.equal(first,second);assert.equal(e.calls.length,1);
 assert.equal(e.calls[0].path,'/api/accounts/alice/proxy/rotate');
 const html=e.run('proxyCell(testRows[0])');
 assert.match(html,/proxy_rotate" disabled/);assert.match(html,/proxy_check" disabled/);
 assert.match(html,/spinner/);
 e.finish({ok:true,ip:'8.8.4.4',changed:true});await first;
 assert.equal(e.messages[0][1],'ok');assert.match(e.messages[0][0],/8\.8\.4\.4/);
 assert.equal(e.run('S.proxyRotations.size'),0);
});

test('an unchanged or unverified IP produces a warning instead of a success claim',async()=>{
 for(const result of [{ok:true,ip:'8.8.8.8',changed:false},{ok:true,ip:'',check_error:'Still reconnecting'}]){
  const e=environment(),pending=e.run('rotateProxy("alice")');e.finish(result);await pending;
  assert.equal(e.messages[0][1],'warn');
 }
});

test('another window rotating the same profile disables the button without sending another request',async()=>{
 const e=environment();e.c.testRows[0].proxy_rotating=true;
 assert.match(e.run('proxyCell(testRows[0])'),/proxy_rotate" disabled/);
 await e.run('rotateProxy("alice")');assert.equal(e.calls.length,0);
 await e.run('checkProxy("alice")');assert.equal(e.calls.length,0);
});

test('proxy geography displays city, deduplicates the region, and escapes every value',()=>{
 const e=environment();e.c.testRows[0].proxy_status='ok';e.c.testRows[0].proxy_location={country_code:'DE',country:'Germany',region:'Berlin',city:'Berlin'};
 const html=e.run('proxyCell(testRows[0])');assert.match(html,/Germany · Berlin/);assert.doesNotMatch(html,/Berlin · Berlin/);
 e.c.testRows[0].proxy_location.city='<script>alert(1)</script>';
 assert.doesNotMatch(e.run('proxyCell(testRows[0])'),/<script>/);assert.match(e.run('proxyCell(testRows[0])'),/&lt;script&gt;/);
});

test('proxy transport and authentication failures are localized in all interface languages',()=>{
 const e=environment();
 for(const lang of ['ru','en','uk']){
  e.c.lang=lang;e.run('I18N.set(lang)');
  for(const [message,key] of [
   ['Cannot check the external IP through the proxy. Check its network access.','proxy_ip_unreachable'],
   ['SOCKS5 proxy authentication failed. Check login and password.','proxy_socks_auth'],
   ['HTTPS check failed through the proxy (certificate error).','proxy_ssl_error'],
   ['IP check did not return a valid public IP.','proxy_ip_invalid']]){
   e.c.message=message;e.c.key=key;assert.equal(e.run('I18N.error(message)'),e.run('t(key)'));
  }
  assert.equal(e.run('I18N.error("IP check returned HTTP 503 through the proxy.")'),e.run('t("proxy_ip_http",{code:"503"})'));
  assert.match(e.run('t("proxy_hint")'),/SOCKS5/);
 }
});
