'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
test('profile tools no longer render color/frame controls',()=>{
 const c=vm.createContext({document:{addEventListener(){}},t:x=>x,esc:x=>String(x??'')});
 vm.runInContext(fs.readFileSync('xgenius/web/static/profile-tools.js','utf8'),c);
 const html=vm.runInContext('ProfileTools.fields({frame_color:"#ff0000"})',c);
 assert.doesNotMatch(html,/frame_color|window_frames|type="color"/);
 assert.match(html,/restore_tabs/);assert.match(html,/extension_set/);
});
