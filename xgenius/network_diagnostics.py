"""Measure this Chrome profile's network route without changing its user tabs."""
import ipaddress
from datetime import datetime, timezone
from xgenius.browser_workspace import browser_lock

MEASURE_JS = r"""
const done=arguments[arguments.length-1];
(async()=>{
 const result={rtc:[],rtc_error:'',dns:null,dns_error:'',ip:''};
 try{const r=await fetch('https://api.ipify.org?format=json',{cache:'no-store',signal:AbortSignal.timeout(7000)});result.ip=(await r.json()).ip||'';}catch(e){}
 try{
  const pc=new RTCPeerConnection({iceServers:[{urls:'stun:stun.l.google.com:19302'}]});
  await new Promise(async resolve=>{
   const timer=setTimeout(resolve,5000);
   pc.onicecandidate=e=>{if(e.candidate){const a=e.candidate.address||e.candidate.candidate.split(' ')[4];if(a)result.rtc.push(a);}else{clearTimeout(timer);resolve();}};
   try{pc.createDataChannel('xanty-diagnostic');await pc.setLocalDescription(await pc.createOffer());}catch(e){clearTimeout(timer);result.rtc_error='WebRTC measurement unavailable';resolve();}
  });pc.close();
 }catch(e){result.rtc_error='WebRTC is unavailable';}
 try{
  const fresh=await(await fetch('/api/new',{headers:{Accept:'application/json'},signal:AbortSignal.timeout(7000)})).json();
  if(!/^[a-zA-Z0-9_-]{1,128}$/.test(fresh.testId)||!Array.isArray(fresh.hostnames)||fresh.hostnames.length>100)throw Error('Invalid DNS test response');
  const hosts=fresh.hostnames.filter(h=>typeof h==='string'&&/^[a-zA-Z0-9-]+\.t\.dnsleak\.dev$/.test(h));
  if(!hosts.length||hosts.length!==fresh.hostnames.length)throw Error('Invalid DNS test hostnames');
  result.dns_expected=hosts.length;
  await Promise.all(hosts.map(h=>fetch('https://'+h+'/',{mode:'no-cors',cache:'no-store',signal:AbortSignal.timeout(2500)}).catch(()=>{})));
  for(let i=0;i<3;i++){
   await new Promise(r=>setTimeout(r,700));
   result.dns=await(await fetch('/api/result/'+encodeURIComponent(fresh.testId),{headers:{Accept:'application/json'},signal:AbortSignal.timeout(7000)})).json();
   if((result.dns.lookups||0)>=hosts.length)break;
  }
 }catch(e){result.dns_error='DNS measurement unavailable';}
 return result;
})().then(done).catch(()=>done({dns_error:'Diagnostics unavailable',rtc_error:'Diagnostics unavailable'}));
"""


def classify_webrtc(expected_ip, candidates):
    public = set()
    for value in candidates:
        try:
            ip = ipaddress.ip_address(value)
            if ip.is_global:
                public.add(str(ip))
        except (ValueError, TypeError):
            continue
    mismatches = sorted(public - {expected_ip}) if expected_ip else []
    return {'status': 'warning' if mismatches else 'matched' if public and expected_ip else 'inconclusive',
            'public_ips': sorted(public), 'mismatches': mismatches}


def summarize_dns(report, expected=0):
    report = report if isinstance(report, dict) else {}
    verdict = report.get('verdict') or {}
    status = verdict.get('status')
    complete = isinstance(report.get('lookups'), int) and report['lookups'] >= expected
    measured = 'warning' if status == 'split' else 'observed' if status == 'no_leak' and complete else 'inconclusive'
    resolvers = []
    for item in (report.get('resolvers') or [])[:100]:
        if not isinstance(item, dict) or item.get('role') == 'observer':
            continue
        resolvers.append({k: item.get(k) for k in ('ip','country','countryCode','org','operator','hostname','status')})
    return {'status': measured, 'lookups': report.get('lookups',0), 'expected': expected,
            'resolvers': resolvers, 'detail': str(verdict.get('detail') or '')[:2000]}


def diagnose(browser, expected_ip=''):
    with browser_lock(browser):
        original = browser.current_window_handle
        handle = None
        try:
            browser.switch_to.new_window('tab')
            handle = browser.current_window_handle
            ignored = getattr(browser, '_xg_ignored_targets', set())
            browser._xg_ignored_targets = ignored
            ignored.add(handle.removeprefix('CDwindow-'))
            browser.get('https://dnsleak.dev/')
            browser.set_script_timeout(45)
            data = browser.execute_async_script(MEASURE_JS) or {}
            try:
                actual_ip = str(ipaddress.ip_address(data.get('ip')))
            except (ValueError,TypeError):
                actual_ip = ''
            rtc = classify_webrtc(actual_ip, data.get('rtc') or [])
            dns = summarize_dns(data.get('dns'), data.get('dns_expected',0))
            if data.get('rtc_error'):
                rtc.update(status='inconclusive', error=data['rtc_error'])
            if data.get('dns_error'):
                dns.update(status='inconclusive', error=data['dns_error'])
            return {'checked_at': datetime.now(timezone.utc).isoformat(), 'ip': actual_ip,
                    'ip_status':'measured' if actual_ip else 'inconclusive',
                    'expected_ip': expected_ip, 'ip_mismatch': bool(data.get('ip') and expected_ip and data['ip'] != expected_ip),
                    'webrtc': rtc, 'dns': dns}
        finally:
            try:
                if handle and handle in browser.window_handles:
                    browser.switch_to.window(handle); browser.close()
                if original in browser.window_handles:
                    browser.switch_to.window(original)
                browser.set_script_timeout(30)
            finally:
                if handle:
                    getattr(browser, '_xg_ignored_targets', set()).discard(handle.removeprefix('CDwindow-'))
