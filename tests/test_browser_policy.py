"""Generated browser policy is local, portable and executes its actual decisions."""
import base64
import hashlib
import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('browser_policy_under_test', ROOT / 'xgenius/browser_policy.py')
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)


class Resources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for key in ('src', 'href'):
            if key in attrs:
                self.links.append(attrs[key])


class BrowserPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.profile = Path(self.temp.name) / 'profile'

    def extension(self, **settings):
        return policy.prepare_policy_extension(self.profile, settings)

    def node(self, directory, script, data=None):
        if not shutil.which('node'):
            self.fail('Node is required to execute the generated extension tests')
        result = subprocess.run(['node', '-e', script, str(directory)], input=json.dumps(data),
                                text=True, encoding='utf-8', capture_output=True, check=False, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_defaults_and_strict_booleans(self):
        expected = dict(block_images=False, block_media=False, block_fonts=False, phishing_protection=True)
        self.assertEqual(policy.policy_settings({}), expected)
        self.assertEqual(policy.policy_settings(dict(expected, ignored='value')), expected)
        for key in expected:
            for value in (None, 0, 1, 'false', [], {}):
                with self.subTest(key=key, value=value):
                    with self.assertRaisesRegex(ValueError, key):
                        policy.policy_settings({key: value})

    def test_all_disabled_does_not_create_an_extension(self):
        self.assertIsNone(self.extension(phishing_protection=False))
        self.assertFalse(self.profile.exists())

    def test_disabling_existing_copy_neutralizes_previous_rules(self):
        directory = self.extension(block_images=True)
        before = json.loads((directory / 'manifest.json').read_text())
        self.assertIsNone(self.extension(phishing_protection=False))
        self.assertEqual(json.loads((directory / 'rules.json').read_text()), [])
        after = json.loads((directory / 'manifest.json').read_text())
        self.assertNotEqual(before['version'], after['version'])
        self.assertNotIn('background', after)

    def test_generated_manifest_links_and_stable_identity(self):
        directory = self.extension(block_images=True, block_media=True, block_fonts=True)
        self.assertTrue(directory.is_relative_to(self.profile))
        manifest = json.loads((directory / 'manifest.json').read_text('utf-8'))
        self.assertEqual(manifest['manifest_version'], 3)
        self.assertLessEqual(int(manifest['minimum_chrome_version']), 128)
        digest = hashlib.sha256(base64.b64decode(manifest['key'])).hexdigest()[:32]
        identifier = ''.join(chr(ord('a') + int(c, 16)) for c in digest)
        rules = json.loads((directory / manifest['declarative_net_request']['rule_resources'][0]['path']).read_text())
        redirects = [r for r in rules if r['action']['type'] == 'redirect']
        self.assertTrue(redirects)
        for rule in redirects:
            self.assertTrue(rule['action']['redirect']['regexSubstitution'].startswith(
                f'chrome-extension://{identifier}/warning.html#'))
        resources = [manifest['background']['service_worker']]
        for group in manifest['web_accessible_resources']:
            resources.extend(group['resources'])
        parser = Resources()
        parser.feed((directory / 'warning.html').read_text('utf-8'))
        resources.extend(parser.links)
        for resource in resources:
            with self.subTest(resource=resource):
                self.assertFalse(Path(resource).is_absolute())
                self.assertNotIn('..', Path(resource).parts)
                self.assertTrue((directory / resource).is_file())
        (directory / 'worker.js').write_text('tampered', encoding='utf-8')
        self.assertEqual(self.extension(), directory)
        self.assertNotEqual((directory / 'worker.js').read_text(), 'tampered')
        self.assertEqual(json.loads((directory / 'manifest.json').read_text())['key'], manifest['key'])

    def test_selected_resource_types_are_blocked_independently(self):
        for selected, resource in (('block_images', 'image'), ('block_media', 'media'), ('block_fonts', 'font')):
            with self.subTest(selected=selected):
                directory = self.extension(phishing_protection=False, **{selected: True})
                rules = json.loads((directory / 'rules.json').read_text())
                self.assertEqual([r['action']['type'] for r in rules], ['block'])
                self.assertEqual(rules[0]['condition']['resourceTypes'], [resource])
                self.assertNotIn('webRequest', json.loads((directory / 'manifest.json').read_text())['permissions'])

    def test_actual_rules_and_js_agree_on_navigation_heuristics(self):
        directory = self.extension()
        urls = {
            'https://paypal.com/': None,
            'https://accounts.google.com/signin?next=https://paypal.com.evil.test': None,
            'https://example.test/paypal.com.evil.test': None,
            'https://notpaypal.com/': None,
            'https://paypal.com.evil.test/login?x=1&y=%23#part': 'brand-domain',
            'https://paypal.login.evil.test/': 'brand-subdomain',
            'https://secure.google.com.evil.test/': 'brand-domain',
            'https://name:secret@example.test/': 'userinfo',
            'https://раypal.com/': 'internationalized-host',
            'https://xn--bcher-kva.example/': 'internationalized-host',
            'ftp://paypal.com.evil.test/': None,
            'javascript:alert(1)': None,
        }
        result = self.node(directory, r'''
const fs = require('node:fs'), vm = require('node:vm'), path = require('node:path');
const root = process.argv[1], context = {URL};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(root, 'policy.js'), 'utf8'), context);
const rules = JSON.parse(fs.readFileSync(path.join(root, 'rules.json')));
const urls = JSON.parse(fs.readFileSync(0, 'utf8'));
const matches = (rule, value) => {
  const url = new URL(value), c = rule.condition;
  if (c.excludedRequestDomains?.some(d => url.hostname === d || url.hostname.endsWith('.' + d))) return false;
  return new RegExp(c.regexFilter, c.isUrlFilterCaseSensitive ? '' : 'i').test(url.href);
};
const result = Object.fromEntries(Object.keys(urls).map(value => [value, {
  reason: context.XGPolicy.assess(value)?.reason || null,
  redirect: rules.some(r => r.action.type === 'redirect' && matches(r, value))
}]));
process.stdout.write(JSON.stringify(result));
''', urls)
        for url, reason in urls.items():
            with self.subTest(url=url):
                self.assertEqual(result[url]['reason'], reason)
                self.assertEqual(result[url]['redirect'], reason is not None)

    def test_worker_preserves_original_and_consumes_tab_scoped_continue_once(self):
        directory = self.extension()
        result = self.node(directory, WORKER_HARNESS)
        self.assertEqual(result['view']['url'], result['original'])
        self.assertEqual(result['continued'], result['original'])
        self.assertEqual(result['allow']['action']['type'], 'allow')
        self.assertEqual(result['allow']['condition']['tabIds'], [7])
        self.assertEqual(result['allow']['condition']['resourceTypes'], ['main_frame'])
        self.assertTrue(result['exactMatch'])
        self.assertTrue(result['fragmentMatch'])
        self.assertFalse(result['otherURLMatch'])
        self.assertEqual(result['remaining'], [])
        self.assertEqual(result['untrusted'], {'ok': False})
        self.assertEqual(result['unsafe'], {'ok': False})
        self.assertEqual(result['subframe'], {'ok': False})
        self.assertEqual(result['errorRemaining'], [])
        self.assertEqual(result['closedRemaining'], [])
        self.assertTrue(result['wentBack'])
        self.assertEqual(result['restartedView']['url'], result['original'])

    def test_warning_uses_text_nodes_and_three_translations(self):
        directory = self.extension()
        result = self.node(directory, PAGE_HARNESS)
        self.assertEqual(result['en']['host'], 'paypal.com.evil.test')
        self.assertEqual(result['en']['url'], result['dangerous'])
        self.assertIn('Continue once', result['en']['continue'])
        self.assertIn('Продолжить', result['ru']['continue'])
        self.assertIn('Продовжити', result['uk']['continue'])
        self.assertEqual(result['en']['actions'], ['continue', 'back'])

    def test_rejects_linked_output_files(self):
        directory = self.extension()
        outside = Path(self.temp.name) / 'outside.js'
        outside.write_text('do not change')
        worker = directory / 'worker.js'
        worker.unlink()
        try:
            worker.symlink_to(outside)
        except OSError as exc:
            self.skipTest(f'Symbolic link privilege unavailable: {exc}')
        with self.assertRaises(ValueError):
            self.extension()
        self.assertEqual(outside.read_text(), 'do not change')


WORKER_HARNESS = r'''
const fs = require('node:fs'), vm = require('node:vm'), path = require('node:path');
const root = process.argv[1], manifest = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json')));
const id = [...require('node:crypto').createHash('sha256').update(Buffer.from(manifest.key, 'base64')).digest().subarray(0,16)]
 .map(b => String.fromCharCode(97+(b>>4),97+(b&15))).join('');
const events = {}, stored = {}, session = new Map(), updates = [];
const event = name => ({addListener: callback => { events[name] = callback; }});
const chrome = {
 runtime: {id, getURL: p => `chrome-extension://${id}/${p}`, onMessage:event('message')},
 storage: {session: {
   async set(value){Object.assign(stored,value);},
   async get(key){return key === null ? {...stored} : {[key]: stored[key]};},
   async remove(key){delete stored[key];}
 }},
 declarativeNetRequest: {
   async getSessionRules(){return [...session.values()];},
   async updateSessionRules(change){for(const id of change.removeRuleIds || [])session.delete(id);for(const r of change.addRules || [])session.set(r.id,r);}
 },
 webNavigation: {onBeforeNavigate:event('before'),onCommitted:event('commit'),onErrorOccurred:event('error')},
 tabs: {onRemoved:event('removed'),async update(tabId,value){updates.push({tabId,...value});},async goBack(){updates.push({back:true});}}
};
function start(){
 const context = {URL,chrome,console,setTimeout,clearTimeout};
 vm.createContext(context);
 context.importScripts = filename => vm.runInContext(fs.readFileSync(path.join(root,filename),'utf8'),context);
 vm.runInContext(fs.readFileSync(path.join(root,'worker.js'),'utf8'),context);
 return context;
}
async function send(message,sender){return new Promise(resolve => { if(events.message(message,sender,resolve)!==true)resolve(null); });}
(async()=>{
 start();
 const original = 'https://paypal.com.evil.test/login?token=a%26b&next=%23x#keep%20this&safe=<svg/onload=alert(1)>';
 await events.before({tabId:7,frameId:0,url:original});
 const canonical = new URL(original), network = new URL(canonical); network.hash='';
 const sender = {id,frameId:0,tab:{id:7},url:`chrome-extension://${id}/warning.html#${network.href}`};
 const view = await send({type:'view'},sender);
 start(); // A suspended MV3 worker can recover the exact fragment from session memory.
 const restartedView = await send({type:'view'},sender);
 const untrusted = await send({type:'continue'},{id,frameId:0,tab:{id:7},url:'https://evil.test/'});
 const unsafe = await send({type:'continue'},{id,frameId:0,tab:{id:7},url:`chrome-extension://${id}/warning.html#javascript:alert(1)`});
 const subframe = await send({type:'continue'},{...sender,frameId:2});
 await send({type:'continue'},sender);
 const allow = [...session.values()][0];
 const regex = new RegExp(allow.condition.regexFilter);
 const exactMatch=regex.test(network.href),fragmentMatch=regex.test(canonical.href),otherURLMatch=regex.test(network.href+'&extra=1');
 const continued=updates.at(-1).url;
 await events.commit({tabId:7,frameId:0,url:canonical.href});
 const remaining=[...session.values()];
 await send({type:'continue'},sender);
 await events.error({tabId:7,frameId:0,url:canonical.href});
 const errorRemaining=[...session.values()];
 await send({type:'continue'},sender);
 await events.removed(7);
 const closedRemaining=[...session.values()];
 await send({type:'back'},sender);
 const wentBack=updates.at(-1).back === true;
 process.stdout.write(JSON.stringify({original,view,restartedView,continued,allow,exactMatch,fragmentMatch,otherURLMatch,remaining,errorRemaining,closedRemaining,wentBack,untrusted,unsafe,subframe}));
})().catch(error=>{console.error(error);process.exitCode=1;});
'''


PAGE_HARNESS = r'''
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=process.argv[1],dangerous='https://paypal.com.evil.test/?q=<img/src=x/onerror=alert(1)>#%23&x=1';
async function render(language){
 const elements=new Map(),actions=[];
 const document={documentElement:{lang:''},title:'',getElementById(id){
  if(!elements.has(id))elements.set(id,{textContent:'',disabled:false,addEventListener(type,callback){this[type]=callback;},set innerHTML(value){throw new Error('Unsafe HTML insertion');}});
  return elements.get(id);
 }};
 const chrome={runtime:{async sendMessage(message){actions.push(message.type);if(message.type==='view')return {ok:true,url:dangerous,host:'paypal.com.evil.test',reason:'brand-domain'};return {ok:true};}}};
 const context={URL,document,chrome,navigator:{language},console};vm.createContext(context);
 vm.runInContext(fs.readFileSync(path.join(root,'warning.js'),'utf8'),context);
 await new Promise(resolve=>setImmediate(resolve));
 await elements.get('continue').click();await elements.get('back').click();
 return {host:elements.get('host').textContent,url:elements.get('url').textContent,continue:elements.get('continue').textContent,actions:actions.filter(t=>t!=='view')};
}
(async()=>process.stdout.write(JSON.stringify({dangerous,en:await render('en-US'),ru:await render('ru-RU'),uk:await render('uk-UA')})))().catch(e=>{console.error(e);process.exitCode=1;});
'''


if __name__ == '__main__':
    unittest.main()
