'use strict';
const Appearance=(()=>{
 const defaults={
  dark:{accent:'#9165F7',background:'#0C0A14',sidebar:'#171225',surface:'#241C38',text:'#F4F0FF',muted:'#A59BB9'},
  light:{accent:'#673BC9',background:'#F7F5FC',sidebar:'#F0EBF8',surface:'#FFFFFF',text:'#241A35',muted:'#695B7B'}
 };
 const presets=[
  {id:'amethyst',dark:defaults.dark,light:defaults.light},
  {id:'ocean',
   dark:{accent:'#38BDF8',background:'#08131F',sidebar:'#0E2030',surface:'#162D41',text:'#EAF6FF',muted:'#9CB4C8'},
   light:{accent:'#0969A8',background:'#F3F8FC',sidebar:'#E5EFF7',surface:'#FFFFFF',text:'#102D43',muted:'#46647A'}},
  {id:'forest',
   dark:{accent:'#34D399',background:'#0B1512',sidebar:'#10261F',surface:'#19382D',text:'#EDF9F2',muted:'#A3BDB0'},
   light:{accent:'#087A51',background:'#F2F8F4',sidebar:'#E4F0E8',surface:'#FFFFFF',text:'#163529',muted:'#4C6C5B'}},
  {id:'graphite',
   dark:{accent:'#B6C2D1',background:'#101214',sidebar:'#181C20',surface:'#242A30',text:'#F4F6F8',muted:'#AEB8C2'},
   light:{accent:'#465767',background:'#F5F6F7',sidebar:'#E9ECEF',surface:'#FFFFFF',text:'#202A33',muted:'#56616E'}},
  {id:'amber',
   dark:{accent:'#F6B958',background:'#18120B',sidebar:'#261D12',surface:'#382B1A',text:'#FFF6E8',muted:'#C5B296'},
   light:{accent:'#9B5B08',background:'#FCF8F0',sidebar:'#F4EAD8',surface:'#FFFFFF',text:'#3C2A12',muted:'#7B6341'}},
  {id:'rose',
   dark:{accent:'#F08EB3',background:'#1A0E17',sidebar:'#2A1825',surface:'#3C2334',text:'#FFF0F6',muted:'#C5A4B7'},
   light:{accent:'#AF3269',background:'#FCF4F8',sidebar:'#F6E6ED',surface:'#FFFFFF',text:'#441E32',muted:'#80536A'}}
 ];
 const keys=Object.keys(defaults.dark),valid=color=>typeof color==='string'&&/^#[0-9a-f]{6}$/i.test(color);
 const rgb=hex=>[1,3,5].map(index=>parseInt(hex.slice(index,index+2),16));
 const mix=(first,second,ratio)=>'#'+rgb(first).map((channel,index)=>Math.round(channel+(rgb(second)[index]-channel)*ratio).toString(16).padStart(2,'0')).join('').toUpperCase();
 const foreground=color=>{
  const channels=rgb(color).map(value=>{value/=255;return value<=.04045?value/12.92:((value+.055)/1.055)**2.4;});
  const luminance=channels[0]*.2126+channels[1]*.7152+channels[2]*.0722;
  return (luminance+.05)/.05>=1.05/(luminance+.05)?'#000000':'#FFFFFF';
 };
 function palette(theme,colors={}){const result={...defaults[theme==='light'?'light':'dark']};for(const key of keys)if(valid(colors?.[theme]?.[key]))result[key]=colors[theme][key].toUpperCase();return result;}
 function properties(p){const light=mix(p.accent,'#FFFFFF',.32),dark=mix(p.accent,'#000000',.25),ink=foreground(p.accent),contrastTarget=ink==='#000000'?'#FFFFFF':'#000000';return {
  '--color-bg':p.background,'--color-rail':mix(p.sidebar,p.background,.35),'--color-sidebar':p.sidebar,
  '--color-card':p.surface,'--color-control':mix(p.surface,p.background,.35),'--color-hover':mix(p.surface,p.accent,.12),
  '--color-border':mix(p.surface,p.text,.24),'--color-border-subtle':mix(p.surface,p.text,.12),
  '--color-text':p.text,'--color-text-secondary':p.muted,'--color-text-muted':p.muted,
  '--color-accent':p.accent,'--color-accent-light':light,'--color-accent-dark':dark,'--color-accent-ink':mix(p.accent,p.text,.2),
  '--color-accent-soft':p.accent+'1A','--color-accent-border':p.accent+'60',
  '--color-primary':p.accent,'--color-primary-hover':mix(p.accent,contrastTarget,.1),'--color-primary-active':mix(p.accent,contrastTarget,.18),'--color-on-primary':ink,
  '--color-highlight':p.accent+'0A','--color-thumb':mix(p.surface,p.text,.3),
  '--shadow-focus':`0 0 0 3px ${p.accent}33`,'--shadow-primary':`0 3px 12px ${p.accent}33`,
  '--shadow-logo':`0 4px 14px ${p.accent}33`,'--gradient-brand':`linear-gradient(145deg,${light},${p.accent},${dark})`,
  '--gradient-page':`radial-gradient(ellipse at 70% 0%,${p.accent}0C,transparent 52%)`,
  '--select-chevron':`url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' fill='none' stroke='%23${p.muted.slice(1)}' stroke-width='1.6'%3E%3Cpath d='m4 6 4 4 4-4'/%3E%3C/svg%3E")`
 };}
 const overridden=Object.keys(properties(defaults.dark));
 function apply(preferences={}){
  const root=document.documentElement,theme=preferences.theme==='light'?'light':'dark';
  root.dataset.theme=theme;
  for(const key of overridden)root.style.removeProperty(key);
  const custom=preferences.custom_colors?.[theme];
  if(custom&&keys.some(key=>valid(custom[key])))for(const [key,value] of Object.entries(properties(palette(theme,preferences.custom_colors))))root.style.setProperty(key,value);
  document.dispatchEvent(new CustomEvent('appearancechange',{detail:preferences}));
 }
 function selectedPreset(theme,colors){const current=palette(theme,colors);return presets.find(p=>keys.every(key=>p[theme][key]===current[key]));}
 function miniature(p,mode){return `<span class="appearance-miniature" data-preview-mode="${mode}" aria-hidden="true" style="--preset-bg:${p.background};--preset-side:${p.sidebar};--preset-surface:${p.surface};--preset-accent:${p.accent};--preset-text:${p.text};--preset-muted:${p.muted}"><span class="appearance-mini-rail"><i></i><i></i><i></i></span><span class="appearance-mini-workspace"><span class="appearance-mini-header"><i></i><b></b></span><span class="appearance-mini-row"><i></i><span></span><b></b></span><span class="appearance-mini-row"><i></i><span></span><b></b></span></span></span>`;}
 function fields(preferences){
  const theme=preferences.theme==='light'?'light':'dark',colors=palette(theme,preferences.custom_colors),selected=selectedPreset(theme,preferences.custom_colors);
  return `<section class="settings-group appearance-settings" data-appearance-mode="${theme}"><h3>${I('sun',16)}<span>${t('appearance_title')}</span></h3><p class="hint appearance-intro">${t('appearance_presets_hint')}</p><label class="field"><span>${t('appearance_mode')}</span><select name="appearance_theme"><option value="dark" ${theme==='dark'?'selected':''}>${t('appearance_dark')}</option><option value="light" ${theme==='light'?'selected':''}>${t('appearance_light')}</option></select></label><div class="appearance-presets" role="group" aria-label="${t('appearance_presets')}">${presets.map(p=>`<button type="button" class="appearance-preset" data-appearance-preset="${p.id}" aria-pressed="${selected?.id===p.id}">${miniature(p.dark,'dark')}${miniature(p.light,'light')}<span class="appearance-preset-label"><span>${t('appearance_preset_'+p.id)}</span><span class="appearance-preset-check" aria-hidden="true">${I('check',13)}</span></span></button>`).join('')}</div><p class="appearance-selection" data-preset-status role="status" aria-live="polite">${selected?t('appearance_selected',{name:t('appearance_preset_'+selected.id)}):t('appearance_custom_selected')}</p><details class="appearance-custom" ${selected?'':'open'}><summary>${t('appearance_customize')}</summary><div class="appearance-colors">${keys.map(key=>`<label class="appearance-color"><span>${t('appearance_'+key)}</span><input type="color" name="color_${key}" data-color-key="${key}" value="${colors[key]}" aria-label="${t('appearance_'+key)}"><output data-color-value="${key}">${colors[key]}</output></label>`).join('')}</div><button type="button" class="btn small" data-colors-reset>${t('appearance_reset')}</button></details><p class="hint">${t('appearance_preview')}</p></section>`;
 }
 function bind(dialog,preferences){
  const draft=JSON.parse(JSON.stringify(preferences.custom_colors||{})),root=dialog.body,themeInput=root.querySelector('[name=appearance_theme]');
  const buttons=[...root.querySelectorAll('[data-appearance-preset]')];
  const refresh=()=>{
   const theme=themeInput.value,colors=palette(theme,draft),selected=selectedPreset(theme,draft);
   root.querySelector('[data-appearance-mode]').dataset.appearanceMode=theme;
   for(const key of keys){root.querySelector(`[data-color-key="${key}"]`).value=colors[key];root.querySelector(`[data-color-value="${key}"]`).textContent=colors[key];}
   for(const button of buttons)button.setAttribute('aria-pressed',String(button.dataset.appearancePreset===selected?.id));
   root.querySelector('[data-preset-status]').textContent=selected?t('appearance_selected',{name:t('appearance_preset_'+selected.id)}):t('appearance_custom_selected');
  };
  const preview=()=>apply({...preferences,theme:themeInput.value,custom_colors:draft});
  for(const button of buttons)button.onclick=()=>{
   const preset=presets.find(p=>p.id===button.dataset.appearancePreset);if(!preset)return;
   draft.dark={...preset.dark};draft.light={...preset.light};refresh();preview();
  };
  themeInput.onchange=()=>{refresh();preview();};
  for(const key of keys)root.querySelector(`[data-color-key="${key}"]`).oninput=event=>{const color=event.target.value;if(!valid(color))return;draft[themeInput.value]||={};draft[themeInput.value][key]=color.toUpperCase();refresh();preview();};
  root.querySelector('[data-colors-reset]').onclick=()=>{delete draft[themeInput.value];refresh();preview();};
  refresh();
  return {values:()=>({theme:themeInput.value,custom_colors:draft})};
 }
 return {apply,fields,bind,palette,foreground};
})();
