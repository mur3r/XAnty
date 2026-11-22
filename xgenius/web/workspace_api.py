"""Local workspace tools. Disk work runs in lifecycle-tracked workers."""
from pathlib import Path

from xgenius.backups import BackupManager
from xgenius.chromium_versions import ChromiumVersionManager
from xgenius.error_messages import launch_diagnostic
from xgenius.workspace_operations import obsolete_files, clean_obsolete_files, profile_size
from xgenius.browser_workspace import clear_cache
from xgenius.web.actions import ActionError


class WorkspaceApiMixin:
    def _workspace_idle(self):
        actions = self._require_engine()
        if (actions._busy or actions._closing or actions._transferring or actions._profile_operations
                or any(not t.done() for t in actions._launch_tasks)
                or any(st.browser for st in actions.am.accounts.values())):
            raise ActionError('Close all profiles and wait for current operations to finish.')
        return actions

    def _backup_manager(self):
        self._require_engine()
        if not hasattr(self.engine, 'backups'):
            self.engine.backups = BackupManager(self.engine.config)
        return self.engine.backups

    def _window_set_rows(self):
        am = self._require_engine().am
        names = {a.get('profile_id'): a['username'] for a in am.load_accounts()}
        return [{**record, 'usernames': [names[p] for p in record['profile_ids'] if p in names],
                 'missing': sum(p not in names for p in record['profile_ids'])} for record in am.window_sets()]

    async def api_workspace(self, request):
        actions = self._require_engine()
        config = self.engine.config
        chromium = await actions._run_profile_worker(ChromiumVersionManager(config).snapshot)
        errors = []
        if not Path(config.chrome_path).is_file() or not Path(config.chromedriver_path).is_file():
            errors.append({'username':'', 'profile_name':'Chromium', 'category':'missing_browser',
                           'detail':'The selected Chrome / ChromeDriver pair is missing. Install a compatible pair in Chromium versions.'})
        if chromium.get('selection_error'):
            errors.append({'username':'', 'profile_name':'Chromium', 'category':'configuration', 'detail':chromium['selection_error']})
        for account in actions.am.load_accounts():
            state = actions.am.accounts.get(account['username'])
            if state is None:
                continue
            message = getattr(state,'launch_error','') or getattr(state,'proxy_error','') or getattr(state,'session_save_error','') or getattr(state,'status_reason','')
            if message:
                errors.append({'username':account['username'], 'profile_name':account.get('profile_name') or account['username'],
                               **launch_diagnostic(message,account)})
        return self._json({'chromium':chromium, 'backups':self._backup_manager().snapshot(),
                           'window_sets':self._window_set_rows(), 'errors':errors})

    async def api_chromium_available(self, request):
        actions = self._require_engine()
        return self._json(await actions._run_profile_worker(ChromiumVersionManager(self.engine.config).available))

    async def api_chromium_install(self, request):
        actions = self._require_engine()
        body = await request.json()
        version = body.get('version')
        if not isinstance(version,str) or not version:
            raise ActionError('Choose a Chromium channel or version')
        manager = ChromiumVersionManager(self.engine.config)
        async def worker(job):
            def progress(event):
                values = dict(event)
                values['processed'] = event.get('downloaded',event.get('extracted',0))
                job.update(**values)
            result = await actions._run_profile_worker(manager.install,version,progress,job.cancelled)
            self.engine.notify()
            return result
        job = self.jobs.start('chromium',worker)
        return self._json(job.snapshot(),status=202)

    async def api_chromium_select(self, request):
        actions = self._workspace_idle()
        if any(j.status == 'running' for j in self.jobs.jobs.values()):
            raise ActionError('Wait for current background jobs to finish')
        body = await request.json()
        # Recheck after reading a request body, before reserving the workspace.
        self._workspace_idle()
        names = {a['username'] for a in actions.am.load_accounts()}
        actions._version_switching = True
        actions._transferring.update(names)
        try:
            manager = ChromiumVersionManager(self.engine.config)
            if request.method == 'DELETE':
                await actions._run_profile_worker(manager.delete,body.get('version'))
                result = await actions._run_profile_worker(manager.snapshot)
            else:
                result = await actions._run_profile_worker(manager.select,body.get('version'))
            self.engine.config.refresh_browser_paths()
            self.engine.notify()
            return self._json({'ok':True,**result})
        finally:
            actions._transferring.difference_update(names)
            actions._version_switching = False

    async def api_backups(self, request):
        actions = self._require_engine()
        manager = self._backup_manager()
        if request.method == 'PUT':
            if manager.snapshot()['running']:
                raise ActionError('Wait for the backup to finish')
            body = await request.json()
            await actions._run_profile_worker(manager.configure,body)
            self.engine.notify()
        return self._json(manager.snapshot())

    async def api_backup_run(self, request):
        self._workspace_idle()
        async def worker(job):
            return await self.engine.run_backup(job.update,job.cancelled)
        return self._json(self.jobs.start('backup',worker).snapshot(),status=202)

    def _cleanup_protected(self):
        protected = [getattr(self.updates,'path',None)]
        if protected[0]:
            protected.append(Path(protected[0]).with_suffix('.part'))
        if self._transfer_storage:
            protected.append(self._transfer_storage.name)
        return [p for p in protected if p]

    async def api_storage(self, request):
        actions = self._require_engine()
        if request.method == 'GET':
            return self._json(await actions._run_profile_worker(obsolete_files,self.engine.config,self.updates.root,self._cleanup_protected()))
        body = await request.json()
        operation = body.get('operation')
        if operation == 'sizes':
            names = [a['username'] for a in actions.am.load_accounts()]
            def measure():
                return {u:profile_size(self.engine.config,u) for u in names}
            self.engine._profile_sizes = await actions._run_profile_worker(measure)
            self.engine.notify()
            return self._json({'sizes':self.engine._profile_sizes})
        if operation == 'cleanup':
            if any(j.status == 'running' for j in self.jobs.jobs.values()):
                raise ActionError('Wait for background jobs before cleaning temporary files')
            result = await actions._run_profile_worker(clean_obsolete_files,self.engine.config,self.updates.root,self._cleanup_protected())
            return self._json(result)
        if operation == 'cache':
            names = list(dict.fromkeys(self._usernames(body)))
            if not names:
                raise ActionError('Select profiles first')
            for name in names:
                actions._idle_profile(name,require_closed=True)
            actions._profile_operations.update(names)
            try:
                def clean():
                    return [{'username':name,**clear_cache(self.engine.config,name)} for name in names]
                rows = await actions._run_profile_worker(clean)
                return self._json({'results':rows,'bytes':sum(r['bytes'] for r in rows),'files':sum(r['files'] for r in rows)})
            finally:
                actions._profile_operations.difference_update(names)
        raise ActionError('Unknown storage operation')

    async def api_window_sets(self, request):
        actions = self._require_engine()
        if request.method != 'GET':
            body = await request.json()
            if request.method == 'DELETE':
                actions.am.delete_window_set(body.get('id'))
            else:
                saved = actions.am.save_window_set(body.get('name'),self._usernames(body),body.get('id'))
                self.engine.notify()
                return self._json({'ok':True,'set':saved})
            self.engine.notify()
        return self._json({'sets':self._window_set_rows()})

    async def api_window_set_open(self, request):
        body = await request.json()
        result = await self._require_engine().open_window_set(request.match_info['set_id'],body.get('exact',True),body.get('confirm_close',False))
        return self._json({'ok':True,**result})
