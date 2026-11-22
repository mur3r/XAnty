import asyncio
import tempfile
import unittest
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from xgenius.config import Config
from xgenius.profile_leases import ProfileLease
from xgenius.web.engine import Engine


class EngineOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_keeps_writer_lease_until_cancelled_maintenance_thread_finishes(self):
        with tempfile.TemporaryDirectory() as directory:
            config=Config(Path(directory));lease=ProfileLease.acquire_workspace(config)
            engine=Engine.__new__(Engine);engine.loop=asyncio.get_running_loop();engine._workspace_futures=set()
            engine.account_manager=SimpleNamespace(workspace_lease=lease,shutdown_all_browsers=lambda:None)
            engine.logger=SimpleNamespace(error=lambda *a:None)
            entered=threading.Event();release=threading.Event()
            def checkpoint():
                entered.set();release.wait(5)
            try:
                worker=asyncio.create_task(engine._run_workspace_worker(checkpoint))
                engine._tasks=[worker]
                await asyncio.to_thread(entered.wait,2)
                shutdown=asyncio.create_task(engine.shutdown());await asyncio.sleep(0.02)
                self.assertFalse(shutdown.done())
                from xgenius.profile_leases import ProfileInUseError
                with self.assertRaises(ProfileInUseError):
                    ProfileLease.acquire_workspace(config)
                release.set();await shutdown
                fresh=ProfileLease.acquire_workspace(config);fresh.release()
            finally:
                release.set();lease.release()

    async def test_failed_engine_setup_releases_workspace_writer_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            config=Config(Path(directory))
            with patch('xgenius.web.engine.Logger',return_value=SimpleNamespace(error=lambda *a:None)), \
                    patch('xgenius.web.engine.FolderStore.sync',side_effect=ValueError('Invalid folders')), \
                    patch('threading.Thread.start'):
                with self.assertRaises(ValueError):
                    Engine(asyncio.get_running_loop(),config.base_dir)
            lease=ProfileLease.acquire_workspace(config);lease.release()
