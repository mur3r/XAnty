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
 nodes.set('[data-appearance-mode]',{dataset:{}});nodes.set('[data-preset-status]',{textContent:''});
 const presets=['amethyst','ocean','forest','graphite','amber','rose'].map(id=>({dataset:{appearancePreset:id},attributes:{},setAttribute(k,v){this.attributes[k]=v;}}));
 nodes.set('[name=session_autosave]',{checked:true});nodes.set('[name=autosave_seconds]',{value:'60'});nodes.set('form',{reportValidity:()=>true});
 const body={querySelector:s=>nodes.get(s),querySelectorAll:s=>s==='[data-appearance-preset]'?presets:[]};
 let options,dialog;
 c.Dialogs={open(value){options=value;dialog={body,close(){value.onClose?.();}};return dialog;}};
 for(const name of ['appearance.js','profile-tools.js'])vm.runInContext(fs.readFileSync('xgenius/web/static/'+name,'utf8'),c);
 return {c,properties,nodes,presets,document,events,body,run:source=>vm.runInContext(source,c),options:()=>options,dialog:()=>dialog};
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

test('a preset previews both modes and saving keeps the chosen palette after reopening',async()=>{
 const e=environment();await e.run('ProfileTools.settings()');
 assert.equal((e.options().body.match(/data-appearance-preset=/g)||[]).length,6);
 e.presets.find(p=>p.dataset.appearancePreset==='forest').onclick();
 assert.equal(e.properties.get('--color-accent'),'#34D399');
 assert.deepEqual(e.c.S.preferences.custom_colors,{});
 const theme=e.nodes.get('[name=appearance_theme]');theme.value='light';theme.onchange();
 assert.equal(e.properties.get('--color-accent'),'#087A51');
 assert.equal(e.presets.filter(p=>p.attributes['aria-pressed']==='true')[0].dataset.appearancePreset,'forest');
 await e.options().buttons.at(-1).onClick(e.dialog());
 assert.equal(e.c.S.preferences.custom_colors.dark.accent,'#34D399');
 assert.equal(e.c.S.preferences.custom_colors.light.accent,'#087A51');
 assert.equal(e.c.S.preferences.theme,'light');
 await e.run('ProfileTools.settings()');
 assert.equal(e.presets.find(p=>p.dataset.appearancePreset==='forest').attributes['aria-pressed'],'true');
});

test('editing or resetting one preset mode preserves the other and marks custom colors',async()=>{
 const e=environment();await e.run('ProfileTools.settings()');
 e.presets.find(p=>p.dataset.appearancePreset==='ocean').onclick();
 e.nodes.get('[data-color-key="accent"]').oninput({target:{value:'#112233'}});
 assert.equal(e.presets.filter(p=>p.attributes['aria-pressed']==='true').length,0);
 assert.equal(e.nodes.get('[data-preset-status]').textContent,'appearance_custom_selected');
 e.nodes.get('[data-colors-reset]').onclick();
 assert.equal(e.presets.find(p=>p.dataset.appearancePreset==='amethyst').attributes['aria-pressed'],'true');
 const theme=e.nodes.get('[name=appearance_theme]');theme.value='light';theme.onchange();
 assert.equal(e.properties.get('--color-accent'),'#0969A8');
 assert.equal(e.presets.find(p=>p.dataset.appearancePreset==='ocean').attributes['aria-pressed'],'true');
});

test('canceling a preset or a failed save restores the original custom colors',async()=>{
 const e=environment();e.c.S.preferences.custom_colors={dark:{accent:'#778899'},light:{accent:'#665544'}};
 await e.run('ProfileTools.settings()');
 e.presets.find(p=>p.dataset.appearancePreset==='rose').onclick();
 e.c.api=async()=>{throw Error('save failed');};
 await assert.rejects(e.options().buttons.at(-1).onClick(e.dialog()),/save failed/);
 assert.equal(e.c.S.preferences.custom_colors.dark.accent,'#778899');
 e.dialog().close();
 assert.equal(e.properties.get('--color-accent'),'#778899');
 assert.equal(e.c.S.preferences.custom_colors.light.accent,'#665544');
});

function contrast(first,second){
 const luminance=hex=>{const c=[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);return c[0]*.2126+c[1]*.7152+c[2]*.0722;};
 const values=[luminance(first),luminance(second)].sort((a,b)=>b-a);return (values[0]+.05)/(values[1]+.05);
}
test('all six presets keep text and primary controls readable in both modes',async()=>{
 const e=environment();await e.run('ProfileTools.settings()');
 const themes=e.nodes.get('[name=appearance_theme]'),signatures={dark:new Set(),light:new Set()};
 for(const preset of e.presets){
  preset.onclick();
  for(const mode of ['dark','light']){
   themes.value=mode;themes.onchange();
   const color=name=>e.properties.get('--color-'+name);
   signatures[mode].add(color('bg')+color('accent'));
   for(const text of ['text','text-secondary','accent-ink'])for(const background of ['bg','sidebar','card','control','hover']){
    assert.ok(contrast(color(text),color(background))>=4.5,`${preset.dataset.appearancePreset} ${mode} ${text} on ${background}`);
   }
   for(const background of ['primary','primary-hover','primary-active'])assert.ok(contrast(color('on-primary'),color(background))>=4.5,`${preset.dataset.appearancePreset} ${mode} ${background}`);
  }
 }
 assert.equal(signatures.dark.size,6);assert.equal(signatures.light.size,6);
});
