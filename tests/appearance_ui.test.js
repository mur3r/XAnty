'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function environment(){
 const properties=new Map(),nodes=new Map(),events=[];
 const document={documentElement:{dataset:{theme:'dark'},style:{setProperty:(k,v)=>properties.set(k,v),removeProperty:k=>properties.delete(k)}},
  addEventListener(){},querySelectorAll:()=>[],dispatchEvent:e=>events.push(e)};
 const prefs={theme:'dark',custom_colors:{},session_autosave:true,autosave_seconds:60,folders_collapsed:false};
 const c=vm.createContext({document,CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail;}},
  console,S:{preferences:prefs},I:()=>'',t:key=>key,esc:String,run:fn=>fn(),toast(){},
  $:(selector,root)=>root.querySelector(selector),api:async(method,path,body)=>body?{...c.S.preferences,...body}:c.S.preferences});
 for(const key of ['accent','background','sidebar','surface','text','muted']){nodes.set(`[data-color-key="${key}"]`,{value:''});nodes.set(`[data-color-value="${key}"]`,{textContent:''});}
 nodes.set('[name=appearance_theme]',{value:'dark'});nodes.set('[data-colors-reset]',{});
 nodes.set('[name=session_autosave]',{checked:true});nodes.set('[name=autosave_seconds]',{value:'60'});nodes.set('form',{reportValidity:()=>true});
 const body={querySelector:s=>nodes.get(s)};
 let options,dialog;
 c.Dialogs={open(value){options=value;dialog={body,close(){value.onClose?.();}};return dialog;}};
 for(const name of ['appearance.js','profile-tools.js'])vm.runInContext(fs.readFileSync('xgenius/web/static/'+name,'utf8'),c);
 return {c,properties,nodes,document,events,body,run:source=>vm.runInContext(source,c),options:()=>options,dialog:()=>dialog};
}

test('custom colors apply consistently and use a readable button foreground',()=>{
 const e=environment();e.run('Appearance.apply({theme:"dark",custom_colors:{dark:{accent:"#FFFFFF",background:"#112233",sidebar:"#223344",surface:"#334455",text:"#F0F0F0",muted:"#AABBCC"}}})');
 for(const [property,value] of [['--color-bg','#112233'],['--color-sidebar','#223344'],['--color-card','#334455'],['--color-text','#F0F0F0'],['--color-primary','#FFFFFF'],['--color-on-primary','#000000']])assert.equal(e.properties.get(property),value);
 assert.equal(e.run('Appearance.foreground("#000000")'),'#FFFFFF');
});

test('switching themes isolates palettes and resetting removes overrides',()=>{
 const e=environment();
 e.run('globalThis.prefs={theme:"dark",custom_colors:{dark:{accent:"#00AAFF"},light:{accent:"#AA0000"}}};Appearance.apply(prefs)');
 assert.equal(e.properties.get('--color-accent'),'#00AAFF');
 e.run('Appearance.apply({...prefs,theme:"light"})');assert.equal(e.properties.get('--color-accent'),'#AA0000');
 e.run('Appearance.apply({theme:"dark",custom_colors:{}})');assert.equal(e.properties.size,0);assert.equal(e.document.documentElement.dataset.theme,'dark');
 e.run('Appearance.apply({custom_colors:{dark:{accent:"red;display:none"}}})');assert.equal(e.properties.size,0);
});

test('preview edits both theme palettes, resets one, and cancellation restores saved appearance',async()=>{
 const e=environment();await e.run('ProfileTools.settings()');
 const accent=e.nodes.get('[data-color-key="accent"]'),theme=e.nodes.get('[name=appearance_theme]');
 accent.oninput({target:{value:'#123456'}});assert.equal(e.properties.get('--color-accent'),'#123456');
 theme.value='light';theme.onchange();accent.oninput({target:{value:'#765432'}});
 assert.equal(e.properties.get('--color-accent'),'#765432');
 e.nodes.get('[data-colors-reset]').onclick();assert.equal(e.properties.size,0);
 theme.value='dark';theme.onchange();assert.equal(e.properties.get('--color-accent'),'#123456');
 e.dialog().close();assert.equal(e.properties.size,0);assert.deepEqual(e.c.S.preferences.custom_colors,{});
});

test('saving the settings persists selected colors and theme with existing session preferences',async()=>{
 const e=environment();await e.run('ProfileTools.settings()');
 const theme=e.nodes.get('[name=appearance_theme]');theme.value='light';theme.onchange();
 e.nodes.get('[data-color-key="accent"]').oninput({target:{value:'#abcdef'}});
 await e.options().buttons.at(-1).onClick(e.dialog());
 assert.equal(e.c.S.preferences.theme,'light');assert.equal(e.c.S.preferences.custom_colors.light.accent,'#ABCDEF');
 assert.equal(e.c.S.preferences.session_autosave,true);assert.equal(e.c.S.preferences.autosave_seconds,60);
 assert.equal(e.properties.get('--color-accent'),'#ABCDEF');
});
