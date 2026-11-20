from pathlib import Path
import tempfile
import time
import unittest
from fastapi.testclient import TestClient
from wasmdock.app import create_app


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.context = TestClient(create_app(Path(self.temp.name)/"jobs.db"))
        self.client = self.context.__enter__()

    def tearDown(self):
        self.context.__exit__(None, None, None)
        self.temp.cleanup()

    def test_api_flow_tenant_isolation_and_stats(self):
        response = self.client.post("/api/jobs", json={"sample_id":"uppercase", "stdin":"hello"}, headers={"X-Tenant":"alpha"})
        self.assertEqual(response.status_code, 202)
        job_id = response.json()["id"]
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}", headers={"X-Tenant":"beta"}).status_code, 404)
        for _ in range(100):
            job = self.client.get(f"/api/jobs/{job_id}").json()
            if job["status"] in {"succeeded", "failed"}:
                break
            time.sleep(.05)
        self.assertEqual(job["output"], "HELLO")
        self.assertEqual(self.client.get("/api/stats", headers={"X-Tenant":"beta"}).json()["recent"], [])
        self.assertIn("wasmdock_worker_slots 2", self.client.get("/metrics").text)

    def test_invalid_inputs_and_tenant(self):
        self.assertEqual(self.client.post("/api/jobs", json={"sample_id":"uppercase", "memory_mb":999}).status_code, 422)
        self.assertEqual(self.client.post("/api/jobs", json={"sample_id":"unknown"}).status_code, 400)
        self.assertEqual(self.client.get("/api/jobs", headers={"X-Tenant":"outsider"}).status_code, 400)
        self.assertEqual(self.client.post("/api/jobs", content=b"x"*270_000).status_code, 413)

    def test_static_ui_and_local_host_boundary(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("WasmDock", response.text)
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(self.client.get("/healthz", headers={"Host":"attacker.example"}).status_code, 400)
        self.assertEqual(len(self.client.get("/api/samples").json()), 6)


if __name__ == "__main__":
    unittest.main()
