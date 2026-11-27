'use strict';
const Appearance=(()=>{
 const defaults={
  dark:{accent:'#9165F7',background:'#0C0A14',sidebar:'#171225',surface:'#241C38',text:'#F4F0FF',muted:'#A59BB9'},
  light:{accent:'#673BC9',background:'#F7F5FC',sidebar:'#F0EBF8',surface:'#FFFFFF',text:'#241A35',muted:'#695B7B'}
 };
 const keys=Object.keys(defaults.dark),valid=color=>typeof color==='string'&&/^#[0-9a-f]{6}$/i.test(color);
 const rgb=hex=>[1,3,5].map(index=>parseInt(hex.slice(index,index+2),16));
 const mix=(first,second,ratio)=>'#'+rgb(first).map((channel,index)=>Math.round(channel+(rgb(second)[index]-channel)*ratio).toString(16).padStart(2,'0')).join('').toUpperCase();
 const foreground=color=>{
  const channels=rgb(color).map(value=>{value/=255;return value<=.04045?value/12.92:((value+.055)/1.055)**2.4;});
  const luminance=channels[0]*.2126+channels[1]*.7152+channels[2]*.0722;
  return (luminance+.05)/.05>=1.05/(luminance+.05)?'#000000':'#FFFFFF';
 };
 function palette(theme,colors={}){const result={...defaults[theme==='light'?'light':'dark']};for(const key of keys)if(valid(colors?.[theme]?.[key]))result[key]=colors[theme][key].toUpperCase();return result;}
 function properties(p){const light=mix(p.accent,'#FFFFFF',.32),dark=mix(p.accent,'#000000',.25),ink=foreground(p.accent);return {
  '--color-bg':p.background,'--color-rail':mix(p.sidebar,p.background,.35),'--color-sidebar':p.sidebar,
  '--color-card':p.surface,'--color-control':mix(p.surface,p.background,.35),'--color-hover':mix(p.surface,p.accent,.12),
  '--color-border':mix(p.surface,p.text,.24),'--color-border-subtle':mix(p.surface,p.text,.12),
  '--color-text':p.text,'--color-text-secondary':p.muted,'--color-text-muted':p.muted,
  '--color-accent':p.accent,'--color-accent-light':light,'--color-accent-dark':dark,'--color-accent-ink':mix(p.accent,p.text,.2),
  '--color-accent-soft':p.accent+'1A','--color-accent-border':p.accent+'60',
  '--color-primary':p.accent,'--color-primary-hover':mix(p.accent,ink,.12),'--color-primary-active':dark,'--color-on-primary':ink,
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
 function fields(preferences){const theme=preferences.theme==='light'?'light':'dark',colors=palette(theme,preferences.custom_colors);return `<section class="settings-group appearance-settings"><h3>${I('sun',16)}<span>${t('appearance_title')}</span></h3><label class="field"><span>${t('theme')}</span><select name="appearance_theme"><option value="dark" ${theme==='dark'?'selected':''}>${t('appearance_dark')}</option><option value="light" ${theme==='light'?'selected':''}>${t('appearance_light')}</option></select></label><div class="appearance-colors">${keys.map(key=>`<label class="appearance-color"><span>${t('appearance_'+key)}</span><input type="color" name="color_${key}" data-color-key="${key}" value="${colors[key]}" aria-label="${t('appearance_'+key)}"><output data-color-value="${key}">${colors[key]}</output></label>`).join('')}</div><button type="button" class="btn small" data-colors-reset>${t('appearance_reset')}</button><p class="hint">${t('appearance_preview')}</p></section>`;}
 function bind(dialog,preferences){
  const draft=JSON.parse(JSON.stringify(preferences.custom_colors||{})),root=dialog.body,themeInput=root.querySelector('[name=appearance_theme]');
  const refresh=()=>{const colors=palette(themeInput.value,draft);for(const key of keys){root.querySelector(`[data-color-key="${key}"]`).value=colors[key];root.querySelector(`[data-color-value="${key}"]`).textContent=colors[key];}};
  const preview=()=>apply({...preferences,theme:themeInput.value,custom_colors:draft});
  themeInput.onchange=()=>{refresh();preview();};
  for(const key of keys)root.querySelector(`[data-color-key="${key}"]`).oninput=event=>{const color=event.target.value;if(!valid(color))return;draft[themeInput.value]||={};draft[themeInput.value][key]=color.toUpperCase();root.querySelector(`[data-color-value="${key}"]`).textContent=color.toUpperCase();preview();};
  root.querySelector('[data-colors-reset]').onclick=()=>{delete draft[themeInput.value];refresh();preview();};
  return {values:()=>({theme:themeInput.value,custom_colors:draft})};
 }
 return {apply,fields,bind,palette,foreground};
})();
