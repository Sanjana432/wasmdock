"""Bounded round-robin admission and process-per-job execution."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
from time import monotonic, perf_counter
import uuid
from .models import JobSpec
from .samples import sample_wat

ROOT = Path(__file__).resolve().parents[1]
TENANTS = ("alpha", "beta")


def now():
    return datetime.now(timezone.utc).isoformat()


class QueueFull(ValueError):
    pass


class Scheduler:
    def __init__(self, database=".data/jobs.sqlite3", workers=2, max_queue=24, per_tenant_queue=12, executor=None):
        self.database = str(database)
        Path(database).parent.mkdir(parents=True, exist_ok=True)
        self.workers, self.max_queue, self.per_tenant_queue = workers, max_queue, per_tenant_queue
        self._condition = threading.Condition()
        self._queues = {tenant: deque() for tenant in TENANTS}
        self._running = {tenant: 0 for tenant in TENANTS}
        self._order = deque(TENANTS)
        self._closing = False
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="wasmdock-job")
        self._executor = executor or self._execute_child
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, tenant TEXT NOT NULL, created TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL)")
            rows = conn.execute("SELECT id,payload FROM jobs WHERE status IN ('queued','running')").fetchall()
            for job_id, payload in rows:
                job = json.loads(payload)
                job.update(status="failed", reason="server_restarted", error="Server restarted before this job completed. Submit it again.", completed_at=now())
                conn.execute("UPDATE jobs SET status=?,payload=? WHERE id=?", ("failed", json.dumps(job), job_id))
        self._dispatcher = threading.Thread(target=self._dispatch, name="wasmdock-dispatch", daemon=True)
        self._dispatcher.start()

    def _save(self, job):
        with closing(sqlite3.connect(self.database, timeout=10)) as conn, conn:
            conn.execute("INSERT INTO jobs VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,payload=excluded.payload", (job["id"], job["tenant"], job["created_at"], job["status"], json.dumps(job)))
            # Keep metadata bounded; queued and running jobs are never removed.
            conn.execute("DELETE FROM jobs WHERE status IN ('succeeded','failed') AND id NOT IN (SELECT id FROM jobs ORDER BY created DESC LIMIT 500)")

    def submit(self, tenant, spec: JobSpec):
        if tenant not in TENANTS:
            raise ValueError("Unknown tenant.")
        if spec.sample_id:
            # Resolve the fixed catalogue before admission, never accept a client-supplied path.
            spec = spec.model_copy(update={"wat": sample_wat(spec.sample_id), "sample_id": None})
        with self._condition:
            if self._closing:
                raise QueueFull("The scheduler is shutting down.")
            queued = sum(len(queue) for queue in self._queues.values())
            if queued >= self.max_queue or len(self._queues[tenant]) >= self.per_tenant_queue:
                raise QueueFull("Queue budget reached. Wait for an existing job to finish.")
            job = {"id": str(uuid.uuid4()), "tenant": tenant, "status": "queued", "created_at": now(),
                   "started_at": None, "completed_at": None, "output": "", "stderr": "", "error": "", "reason": "queued",
                   "metrics": {}, "budgets": {k: getattr(spec,k) for k in ("fuel", "memory_mb", "timeout_ms", "output_limit", "workspace")},
                   "events": ["Accepted within tenant and global queue limits."]}
            self._save(job)
            self._queues[tenant].append((job, spec, perf_counter()))
            self._condition.notify_all()
            return dict(job)

    def get(self, tenant, job_id):
        with closing(sqlite3.connect(self.database)) as conn:
            row = conn.execute("SELECT payload FROM jobs WHERE id=? AND tenant=?", (job_id, tenant)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, tenant, limit=50):
        with closing(sqlite3.connect(self.database)) as conn:
            rows = conn.execute("SELECT payload FROM jobs WHERE tenant=? ORDER BY created DESC LIMIT ?", (tenant, min(limit, 100))).fetchall()
        return [json.loads(row[0]) for row in rows]

    def stats(self):
        with self._condition, closing(sqlite3.connect(self.database)) as conn:
            rows = conn.execute("SELECT tenant,status,COUNT(*) FROM jobs GROUP BY tenant,status").fetchall()
            counts = {tenant: {"queued":0, "running":0, "completed":0} for tenant in TENANTS}
            for tenant, status, count in rows:
                counts[tenant][status if status in {"queued", "running"} else "completed"] += count
            recent = [json.loads(r[0]) for r in conn.execute("SELECT payload FROM jobs ORDER BY created DESC LIMIT 12")]
            return {"workers":self.workers, "max_queue":self.max_queue,
                    "queued":sum(v["queued"] for v in counts.values()), "running":sum(v["running"] for v in counts.values()),
                    "completed":sum(v["completed"] for v in counts.values()), "tenants":counts, "recent":recent}

    def _take(self):
        if sum(self._running.values()) >= self.workers:
            return None
        for _ in TENANTS:
            tenant = self._order[0]
            self._order.rotate(-1)
            # Reserve a worker slot for each tenant by limiting each to one running job.
            if self._queues[tenant] and self._running[tenant] == 0:
                self._running[tenant] += 1
                return self._queues[tenant].popleft()
        return None

    def _dispatch(self):
        while True:
            with self._condition:
                item = self._take()
                if item is None:
                    if self._closing and not any(self._queues.values()) and not any(self._running.values()):
                        return
                    self._condition.wait(timeout=.2)
                    continue
            self._pool.submit(self._work, *item)

    def _work(self, job, spec, queued_at):
        job.update(status="running", reason="running", started_at=now())
        queue_ms = round((perf_counter()-queued_at)*1000, 3)
        job["events"].append("Round-robin dispatch: a fresh child process will execute this job.")
        self._save(job)
        try:
            outcome = self._executor(spec, job["tenant"])
            job.update(outcome)
            job["metrics"]["queue_ms"] = queue_ms
        except Exception:
            job.update(status="failed", reason="worker_error", error="The child process failed unexpectedly.")
        finally:
            job["completed_at"] = now()
            self._save(job)
            with self._condition:
                self._running[job["tenant"]] -= 1
                self._condition.notify_all()

    @staticmethod
    def _execute_child(spec, tenant):
        started = perf_counter()
        try:
            # Timeout includes a separate two-second interpreter/compilation allowance.
            completed = subprocess.run([sys.executable, "-m", "wasmdock.worker"],
                input=json.dumps({"spec":spec.model_dump(), "tenant":tenant}).encode("utf-8"),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT,
                timeout=spec.timeout_ms/1000+2, check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            if completed.returncode or len(completed.stdout) > 450_000:
                diagnostic = completed.stderr.decode("utf-8", errors="replace")[-1500:]
                return {"status":"failed", "reason":"worker_error",
                        "error":f"Child process exited with code {completed.returncode}. {diagnostic}",
                        "output":"", "stderr":"", "metrics":{"process_ms":round((perf_counter()-started)*1000, 3)},
                        "events":["Worker exited unexpectedly; bounded host diagnostic recorded."]}
            result = json.loads(completed.stdout)
            result["metrics"]["process_ms"] = round((perf_counter()-started)*1000, 3)
            return result
        except subprocess.TimeoutExpired:
            return {"status":"failed", "reason":"process_timeout", "error":"Hard process deadline reached (guest budget plus startup allowance).", "output":"", "stderr":"", "metrics":{"process_ms":round((perf_counter()-started)*1000, 3)}, "events":["Child process terminated by the host deadline."]}

    def wait(self, tenant, job_id, timeout=15):
        deadline = monotonic()+timeout
        while monotonic() < deadline:
            job = self.get(tenant, job_id)
            if job and job["status"] in {"succeeded", "failed"}:
                return job
            with self._condition:
                self._condition.wait(timeout=.05)
        raise TimeoutError("Job did not finish within the caller's wait budget.")

    def close(self):
        with self._condition:
            self._closing = True
            for queue in self._queues.values():
                while queue:
                    job, _, _ = queue.popleft()
                    job.update(status="failed", reason="server_shutdown", error="Server stopped while this job was queued.", completed_at=now())
                    self._save(job)
            self._condition.notify_all()
        self._dispatcher.join(timeout=12)
        self._pool.shutdown(wait=True, cancel_futures=False)
