"""Background operations whose progress survives closing an interface dialog."""
from __future__ import annotations

import asyncio
import copy
import threading
import time
import uuid


class Job:
    def __init__(self, kind):
        self.id = uuid.uuid4().hex
        self.kind = kind
        self.status = 'running'
        self.phase = 'starting'
        self.total = 0
        self.processed = 0
        self.report = []
        self.error = ''
        self.result = None
        self.file_path = None
        self.created_at = time.time()
        self.cancel_event = threading.Event()
        self.lock = threading.Lock()
        self.task = None

    def cancelled(self):
        return self.cancel_event.is_set()

    def update(self, **values):
        with self.lock:
            for key, value in values.items():
                if key == 'report':
                    value = copy.deepcopy(value)
                setattr(self, key, value)

    def snapshot(self, details=True):
        with self.lock:
            result = {key: getattr(self, key) for key in
                      ('id', 'kind', 'status', 'phase', 'total', 'processed', 'error', 'created_at')}
            result.update({name: sum(row.get('status') == status for row in self.report)
                           for name, status in (('added', 'added'), ('imported', 'imported'),
                                                ('exported', 'exported'), ('skipped', 'skipped'), ('errors', 'error'))})
            result['warnings'] = sum(bool(row.get('warnings')) for row in self.report)
            result['download_ready'] = self.status == 'completed' and self.file_path is not None
            if isinstance(self.result,dict):
                for key in ('integrity','integrity_algorithm','verified_files'):
                    if key in self.result:
                        result[key]=self.result[key]
            if details:
                result['report'] = copy.deepcopy(self.report)
            return result


class JobManager:
    def __init__(self):
        self.jobs = {}

    def start(self, kind, worker):
        if any(job.status == 'running' for job in self.jobs.values()):
            raise ValueError('Another transfer operation is running')
        job = Job(kind)
        self.jobs[job.id] = job

        async def run():
            try:
                result = await worker(job)
                job.update(result=result, status='cancelled' if job.cancelled() else 'completed', phase='finished')
            except asyncio.CancelledError:
                job.update(status='cancelled', phase='finished')
            except Exception as exc:
                job.update(status='cancelled' if job.cancelled() else 'failed', error=str(exc), phase='finished')

        job.task = asyncio.create_task(run())
        return job

    def get(self, job_id):
        job = self.jobs.get(job_id)
        if job is None:
            raise ValueError('Transfer operation not found')
        return job

    def snapshots(self):
        return [job.snapshot(details=False) for job in reversed(list(self.jobs.values()))][:20]

    async def shutdown(self):
        pending = []
        for job in self.jobs.values():
            if job.status == 'running':
                job.cancel_event.set()
                pending.append(job.task)
        if pending:
            await asyncio.gather(*[asyncio.shield(task) for task in pending], return_exceptions=True)
