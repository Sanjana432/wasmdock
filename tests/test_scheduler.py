import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from wasmdock.models import JobSpec
from wasmdock.scheduler import QueueFull, Scheduler


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.schedulers = []

    def tearDown(self):
        for scheduler in self.schedulers:
            scheduler.close()
        self.temp.cleanup()

    def scheduler(self, **kwargs):
        scheduler = Scheduler(Path(self.temp.name)/f"{len(self.schedulers)}.db", **kwargs)
        self.schedulers.append(scheduler)
        return scheduler

    def test_process_execution_and_tenant_partition(self):
        scheduler = self.scheduler()
        alpha = scheduler.submit("alpha", JobSpec(sample_id="infinite-loop", fuel=50_000))
        beta = scheduler.submit("beta", JobSpec(sample_id="uppercase", stdin="healthy"))
        self.assertIsNone(scheduler.get("beta", alpha["id"]))
        alpha_result = scheduler.wait("alpha", alpha["id"])
        beta_result = scheduler.wait("beta", beta["id"])
        self.assertEqual(alpha_result["reason"], "fuel_exhausted", alpha_result)
        self.assertEqual(beta_result["output"], "HEALTHY", beta_result)
        self.assertEqual(len(scheduler.list("alpha")), 1)

    def test_round_robin_prevents_one_tenant_draining_queue(self):
        gate = threading.Event()
        entered = threading.Event()
        order = []
        def controlled(spec, tenant):
            order.append(tenant)
            if len(order) == 1:
                entered.set()
                gate.wait(timeout=3)
            return {"status":"succeeded", "reason":"completed", "metrics":{}}
        scheduler = self.scheduler(workers=1, executor=controlled)
        first = scheduler.submit("alpha", JobSpec(sample_id="uppercase"))
        self.assertTrue(entered.wait(2))
        more = [scheduler.submit("alpha", JobSpec(sample_id="uppercase")) for _ in range(3)]
        other = scheduler.submit("beta", JobSpec(sample_id="uppercase"))
        gate.set()
        scheduler.wait("beta", other["id"])
        for job in more:
            scheduler.wait("alpha", job["id"])
        self.assertEqual(order[:2], ["alpha", "beta"])

    def test_admission_backpressure(self):
        gate = threading.Event()
        entered = threading.Event()
        def controlled(spec, tenant):
            entered.set()
            gate.wait(timeout=3)
            return {"status":"succeeded", "reason":"completed", "metrics":{}}
        scheduler = self.scheduler(workers=1, max_queue=1, per_tenant_queue=1, executor=controlled)
        scheduler.submit("alpha", JobSpec(sample_id="uppercase"))
        self.assertTrue(entered.wait(2))
        scheduler.submit("alpha", JobSpec(sample_id="uppercase"))
        with self.assertRaises(QueueFull):
            scheduler.submit("beta", JobSpec(sample_id="uppercase"))
        gate.set()

    def test_unknown_sample_is_not_a_filesystem_path(self):
        scheduler = self.scheduler()
        with self.assertRaises(ValueError):
            scheduler.submit("alpha", JobSpec(sample_id="../../etc/passwd"))

    def test_shutdown_marks_pending_jobs_without_executing_them(self):
        gate, entered = threading.Event(), threading.Event()
        executions = []
        def controlled(spec, tenant):
            executions.append(tenant)
            entered.set()
            gate.wait(timeout=5)
            return {"status":"succeeded", "reason":"completed", "metrics":{}}
        scheduler = self.scheduler(workers=1, executor=controlled)
        running = scheduler.submit("alpha", JobSpec(sample_id="uppercase"))
        self.assertTrue(entered.wait(2))
        pending = scheduler.submit("beta", JobSpec(sample_id="uppercase"))
        closer = threading.Thread(target=scheduler.close)
        closer.start()
        try:
            result = scheduler.wait("beta", pending["id"], timeout=3)
            self.assertEqual(result["reason"], "server_shutdown")
        finally:
            gate.set()
            closer.join(timeout=5)
        self.assertFalse(closer.is_alive())
        self.assertEqual(executions, ["alpha"])
        self.assertEqual(scheduler.get("alpha", running["id"])["status"], "succeeded")
        with self.assertRaises(QueueFull):
            scheduler.submit("alpha", JobSpec(sample_id="uppercase"))

    def test_completed_history_survives_restart(self):
        scheduler = self.scheduler()
        job = scheduler.submit("alpha", JobSpec(sample_id="uppercase", stdin="persist"))
        scheduler.wait("alpha", job["id"])
        scheduler.close()
        self.schedulers.remove(scheduler)
        restored = Scheduler(scheduler.database)
        self.schedulers.append(restored)
        self.assertEqual(restored.get("alpha", job["id"])["output"], "PERSIST")


if __name__ == "__main__":
    unittest.main()
