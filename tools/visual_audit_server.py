"""Loopback-only visual fixtures. Does not import XAnty storage or read user data."""
import argparse
import asyncio
import json
import math
import sys
from pathlib import Path

from aiohttp import web

STATIC = Path(__file__).resolve().parents[1] / 'xgenius' / 'web' / 'static'


class Fixture:
    def __init__(self, theme='dark', language='ru', updates=False, count=120):
        self.preferences = dict(theme=theme, language=language, session_autosave=True, autosave_seconds=60)
        self.folders = ['Research', 'Команда Design', 'Довга назва папки для перевірки інтерфейсу', 'Empty QA']
        self.accounts = []
        self.requests = []
        self.clients = set()
        for i in range(count):
            self.accounts.append(dict(
                username=f'qa_{i:03}', index=i + 1, profile_id=f'synthetic-{i}',
                profile_name='Дослідження · Україна — розширена назва робочого профілю' if i == 2 else ['Research', 'Маркетинг', 'Команда'][i % 3] + f' {i + 1:03}',
                group=self.folders[i % 3], profile_status=['active', 'new', 'review', 'unused'][i % 4],
                favorite=i % 31 == 0, important=False, tags=['Важливо', 'team', 'review'] if i % 5 == 0 else ['team'],
                notes='Synthetic interface audit. No real account data.' if i % 5 == 0 else '',
                proxy='proxy.example:8080', proxy_status='ok', proxy_ip=f'203.0.113.{i % 200 + 1}',
                proxy_location=dict(country='Germany', country_code='DE', region='Berlin', city='Berlin'),
                proxy_rotation_url='https://provider.example/rotate?demo=1', has_proxy_rotation=True,
                has_browser=i in (3, 7), opening=False, closing=False, auto_login=i % 2 == 0,
                restore_tabs=True, phishing_protection=True, block_images=False, block_media=False, block_fonts=False,
                last_launch='2026-11-23T12:00:00Z', runtime_seconds=3600 + i * 60,
                profile_size=dict(bytes=120000000 + i * 1000), reminder_at=None, browser_language='',
                browser_timezone='', window_width=1280, window_height=800, icon_text='', extension_set='',
                password='', auth_token='', ct0_token=''))
        if len(self.accounts) > 2:
            self.accounts[2].update(proxy_status='error', proxy_error='Synthetic proxy timeout')
        self.jobs = [
            dict(id='qa-export', kind='export', status='completed', phase='completed', total=8, processed=8,
                 exported=8, skipped=0, errors=0, integrity='verified', download_ready=False,
                 report=[dict(username='qa_001', status='completed', message='Synthetic report', cookies=0)]),
            dict(id='qa-import', kind='dolphin', status='running', phase='importing', total=20, processed=7,
                 added=6, skipped=0, errors=1, report=[dict(username='qa_002', status='error', message='Synthetic warning')])]
        self.trash = [dict(username='qa_archived', profile_name='Archived QA', profile_number=151,
                           deleted_at='2026-11-20T10:00:00Z', delete_after='2026-12-20T10:00:00Z', retention_days=30)]
        self.history = [dict(username='qa_001', profile_name='Research 002', actor='QA', action='updated',
                             at='2026-11-23T12:00:00Z', changes=dict(
                                 profile_name=dict(before='Research', after='Research 002'),
                                 profile_status=dict(before='new', after='active')))]
        self.extensions = [dict(id='qa-ext', name='Productivity', extensions=[dict(name='Demo extension', version='1.0')],
                                directories=['D:/Demo/Extension'])]
        self.workspace = dict(
            chromium=dict(installed=[dict(version='bundled', selected=True, available=True),
                                     dict(version='130.0.6723.58', available=True)]),
            backups=dict(enabled=True, directory='D:/Demo/Backups', interval_hours=24, keep=7, last_status='completed',
                         last_success_at='2026-11-23T10:00:00Z', next_due_at='2026-11-24T10:00:00Z'),
            window_sets=[dict(id='qa-set', name='Робочі профілі', usernames=['qa_001', 'qa_002'], missing=[])],
            errors=[dict(username='qa_002', profile_name='Команда 003', category='proxy', detail='Synthetic connection timeout')])
        notes = '## Premium Purple Dark\n- Цілісна дизайн-система\n- Клавіатура, теми та діалоги\n\n## Quality\n- Interface checks\n- Safe profile settings'
        self.updates = dict(configured=True, current_version='2026.11.23.4', status='available' if updates else 'current',
                            downloaded=0, can_install=True,
                            release=dict(version='2026.11.24.1', size=100, notes=notes,
                                         page_url='https://github.com/mur3r/XAnty/releases') if updates else None,
                            installed_release=dict(version='2026.11.23.4', notes=notes, pending=False))

    def snapshot(self):
        return dict(phase='ready', version='2026.11.23.4', base_dir='QA · Synthetic workspace', folders=self.folders,
                    accounts=self.accounts, summary=dict(all=len(self.accounts), browsers=sum(a['has_browser'] for a in self.accounts), error=1))

    def metric(self, i=99):
        return dict(cpu=dict(total=25 + math.sin(i / 6) * 12), mem=dict(used_gb=7.2, total_gb=16, pct=45 + math.sin(i / 9) * 4),
                    chrome=dict(rss_gb=1.2), loop_lag_ms=3,
                    accounts=[dict(username=a['username'], procs=4, threads=20, cpu=2.1, rss_mb=160) for a in self.accounts[:5]])

    async def broadcast(self):
        for client in list(self.clients):
            if not client.closed:
                await client.send_json(dict(type='state', data=self.snapshot()))

    async def finish_action(self, names, opened):
        await asyncio.sleep(.7)
        for a in self.accounts:
            if a['username'] in names:
                a.update(has_browser=opened, opening=False, closing=False)
        await self.broadcast()


STATE = web.AppKey('visual-fixture', Fixture)


async def api(request):
    s = request.app[STATE]
    path, method = request.path, request.method
    body = await request.json() if request.can_read_body and request.content_type == 'application/json' else {}
    s.requests.append(dict(path=path, method=method, body=body))
    result = dict(ok=True)
    if path == '/api/preferences':
        if method == 'PUT':
            s.preferences.update(body)
        result = s.preferences
    elif path == '/api/state':
        result = s.snapshot()
    elif path == '/api/workspace':
        result = s.workspace
    elif path == '/api/extension-sets':
        result = dict(sets=s.extensions)
    elif path == '/api/history':
        result = dict(events=s.history)
    elif path == '/api/trash':
        result = dict(profiles=s.trash)
    elif path.startswith('/api/trash/'):
        if path.endswith('/restore'):
            s.trash.clear()
    elif path == '/api/jobs':
        result = dict(jobs=s.jobs)
    elif path.startswith('/api/jobs/'):
        result = next((j for j in s.jobs if j['id'] == path.split('/')[3]), s.jobs[0])
        if path.endswith('/cancel'):
            result['status'] = 'cancelled'
    elif path == '/api/sysmon':
        result = dict(latest=s.metric())
    elif path.startswith('/api/updates'):
        if path.endswith('/download'):
            s.updates.update(status='downloading', downloaded=10)
        elif path == '/api/updates' and s.updates['status'] == 'downloading':
            s.updates['downloaded'] = min(100, s.updates['downloaded'] + 20)
            if s.updates['downloaded'] == 100:
                s.updates['status'] = 'ready'
        elif path.endswith('/install'):
            s.updates['status'] = 'installing'
        result = s.updates
    elif path == '/api/accounts' and method == 'POST':
        result = dict(s.accounts[0], **body)
        result.update(index=len(s.accounts) + 1, profile_id='qa-new', has_browser=False)
        s.accounts.append(result)
    elif path in ('/api/accounts/bulk_edit', '/api/accounts/metadata', '/api/accounts/move', '/api/accounts/auto_login'):
        for a in s.accounts:
            if a['username'] in body.get('usernames', []):
                a.update(body.get('metadata', {}))
                a.update(body.get('settings', {}))
                if 'group' in body:
                    a['group'] = body['group']
                if 'folder' in body:
                    a['group'] = body['folder']
                if 'enabled' in body:
                    a['auto_login'] = body['enabled']
    elif path.startswith('/api/actions/'):
        names = body.get('usernames', [])
        if path.endswith(('/login', '/close')):
            opened = path.endswith('/login')
            for a in s.accounts:
                if a['username'] in names:
                    a.update(opening=opened, closing=not opened)
            await s.broadcast()
            asyncio.create_task(s.finish_action(names, opened))
    elif path.startswith('/api/accounts/'):
        name = path.split('/')[3]
        a = next((a for a in s.accounts if a['username'] == name), None)
        if path.endswith('/tools/cookies'):
            result = dict(cookies=[dict(name='demo', value='synthetic', domain='.example.test', path='/', secure=True)], source='snapshot', warnings=[])
        elif path.endswith('/tools/cookies_import'):
            result = dict(imported=1)
        elif path.endswith('/tools/diagnostics'):
            result = dict(ip='203.0.113.1', webrtc=dict(status='matched', public_ips=['203.0.113.1']),
                          dns=dict(status='inconclusive', expected=3, lookups=2, resolvers=[]))
        elif path.endswith(('/proxy/check', '/proxy/rotate')):
            await asyncio.sleep(.5)
            result = dict(ok=True, ip='203.0.113.77', changed=True)
            if a:
                a.update(proxy_ip=result['ip'], proxy_status='ok')
        elif path.endswith('/cookies'):
            result = dict(cookies=[])
        elif a:
            if method == 'PUT':
                if body.get('profile_name') == '[QA validation error]':
                    return web.json_response(dict(error='Synthetic validation error'), status=400)
                a.update(body)
            result = a
    elif path == '/api/folders' and method == 'POST':
        s.folders.append(body['name'])
    elif path in ('/api/profiles/export', '/api/dolphin/import-all'):
        result = s.jobs[0]
    elif path == '/api/chromium/available':
        result = dict(channels=dict(Stable=dict(version='130.0.6723.58')), versions=[])
    return web.json_response(result)


async def websocket(request):
    s = request.app[STATE]
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    s.clients.add(ws)
    try:
        await ws.send_json(dict(type='logs', lines=['INFO Synthetic workspace connected']))
        for i in range(100):
            await ws.send_json(dict(type='sysmon', data=s.metric(i)))
        async for _ in ws:
            pass
    finally:
        s.clients.discard(ws)
    return ws


async def reset(request):
    request.app[STATE] = Fixture(request.query.get('theme', 'dark'), request.query.get('language', 'ru'),
                                request.query.get('updates') == '1', min(5000, max(0, int(request.query.get('count', '120')))))
    return web.json_response(dict(ok=True))


async def recorded(request):
    return web.json_response(request.app[STATE].requests)


def create_app():
    app = web.Application()
    app[STATE] = Fixture()
    app.router.add_post('/__qa/reset', reset)
    app.router.add_get('/__qa/requests', recorded)
    app.router.add_route('*', '/api/{tail:.*}', api)
    app.router.add_get('/ws', websocket)
    app.router.add_get('/', lambda _: web.FileResponse(STATIC / 'index.html'))
    app.router.add_static('/', STATIC)
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=18769)
    args = parser.parse_args()
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    web.run_app(create_app(), host='127.0.0.1', port=args.port,
                print=lambda _: print(f'READY http://127.0.0.1:{args.port}', flush=True), access_log=None)
