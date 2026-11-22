'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const vm=require('node:vm');
const context=vm.createContext({S:{preferences:{}},Date,console});
vm.runInContext(readFileSync('xgenius/web/static/profile-management.js','utf8'),context);
const evaluate=code=>vm.runInContext(code,context);
test('search finds stable number, tags, notes, name and proxy',()=>{
  context.row={username:'internal',profile_name:'Название',index:108,tags:['Important'],notes:'Customer note',proxy:'host.test:80',proxy_location:{country:'Ukraine'},proxy_status:'ok'};
  for(const query of ['108','important','customer','название','host.test','ukraine','INTERNAL'])assert.equal(evaluate(`ProfileUI.matches(row,${JSON.stringify(query)})`),true,query);
  assert.equal(evaluate("ProfileUI.matches(row,'not present')"),false);
});
test('favorites sort globally and preserve relative order',()=>{
  context.rows=[{username:'a',favorite:false},{username:'b',favorite:true},{username:'c',favorite:true},{username:'d',favorite:false}];
  assert.equal(evaluate('ProfileUI.sort(rows).map(a=>a.username).join()'),'b,c,a,d');
  assert.equal(context.rows[0].username,'a');
});
test('column order survives validation while name cannot disappear',()=>{
  context.S.preferences.columns=['runtime','name','number'];
  assert.equal(evaluate('ProfileUI.columns().join()'),'runtime,name,number');
  context.S.preferences.columns=['proxy','proxy','invalid'];
  const columns=Array.from(evaluate('ProfileUI.columns()'));
  assert.ok(columns.includes('name'));
  assert.equal(new Set(columns).size,columns.length);
  assert.ok(!columns.includes('invalid'));
});
test('runtime includes only the current open interval',()=>{
  context.row={runtime_seconds:3600,runtime_checkpoint:'2026-11-22T10:00:00Z',has_browser:true};
  assert.equal(evaluate("ProfileUI.runtimeSeconds(row,Date.parse('2026-11-22T10:30:00Z'))"),5400);
  context.row.has_browser=false;
  assert.equal(evaluate("ProfileUI.runtimeSeconds(row,Date.parse('2026-11-22T10:30:00Z'))"),3600);
});
test('actual page scripts initialize and every toolbar action is callable',()=>{
  const page=vm.createContext({console,document:{addEventListener(){}},setInterval(){},setTimeout(){}});
  const html=readFileSync('xgenius/web/static/index.html','utf8');
  for(const match of html.matchAll(/<script src="([^"]+)"><\/script>/g))vm.runInContext(readFileSync('xgenius/web/static/'+match[1],'utf8'),page,{filename:match[1]});
  for(const name of ['login','close','bulk_edit','move','export_selected','stop_all','delete','folder_delete','columns','trash','history'])assert.equal(vm.runInContext(`typeof TOOL_ACTIONS.${name}`,page),'function',name);
});
