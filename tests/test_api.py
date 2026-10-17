"""Integration checks for the local API routes and reproducible demo run."""
import json
import threading
import time
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import dev_server


class LocalApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(dev_server.SPAHandler, directory=str(dev_server.ROOT)))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, path, method="GET", body=None):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Origin": self.base}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = Request(self.base + path, data=data, headers=headers, method=method)
        try:
            response = urlopen(req, timeout=10)
        except HTTPError as exc:
            response = exc
        return response.code, json.loads(response.read())

    def test_health_describes_available_synthetic_and_missing_real_pipeline(self):
        status, health = self.request("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(health["synthetic_pipeline_available"])
        self.assertFalse(health["prediction_available"])
        self.assertIn("stage1.py", health["missing_stage_assets"])

    def test_rejects_unavailable_data_sources_and_filesystem_paths(self):
        status, error = self.request("/api/runs", "POST", {"source": "HI-Small"})
        self.assertEqual(status, 422)
        self.assertIn("synthetic demo", error["detail"])
        status, error = self.request("/api/runs", "POST", {"source": "synthetic-demo", "path": "C:/private/data.csv"})
        self.assertEqual(status, 422)
        self.assertIn("filesystem paths", error["detail"])

    def test_privacy_csv_sweep_accepts_local_upload_and_returns_metrics(self):
        from datetime import datetime, timedelta
        rows = ["timestamp,signal,amount,is_laundering"]
        start = datetime(2026, 1, 1)
        for index in range(180):
            label = int(index % 5 == 0)
            timestamp = (start + timedelta(hours=index)).strftime("%Y-%m-%dT%H:%M:%S")
            rows.append(f"{timestamp},{label},{(index % 11) / 11:.4f},{label}")
        status, job = self.request("/api/privacy-sweeps", "POST", {
            "csv_text": "\n".join(rows), "target": "is_laundering"})
        self.assertEqual(status, 202)
        deadline = time.time() + 30
        state = job
        while state["status"] in {"queued", "running"} and time.time() < deadline:
            time.sleep(.1)
            _, state = self.request(f"/api/privacy-sweeps/{job['run_id']}")
        self.assertEqual(state["status"], "completed", state)
        status, report = self.request(f"/api/privacy-sweeps/{job['run_id']}/results")
        self.assertEqual(status, 200)
        self.assertEqual((report["train_rows"], report["validation_rows"], report["test_rows"]), (108, 36, 36))
        self.assertEqual([row["epsilon"] for row in report["results"]], [None, .25, .5, 1.0, 2.0, 4.0])
        self.assertTrue(report["timestamp_sorted"])
        self.assertIn("formal privacy certification", report["privacy_caveat"])

    def test_privacy_csv_sweep_rejects_raw_identifier_features(self):
        csv_text = "account_id,signal,is_laundering\n" + "\n".join(
            f"acct-{i},{i / 100:.2f},{int(i % 3 == 0)}" for i in range(100))
        status, error = self.request("/api/privacy-sweeps", "POST", {
            "csv_text": csv_text, "target": "is_laundering"})
        self.assertEqual(status, 422)
        self.assertIn("Remove account IDs", error["detail"])

    def test_run_is_queued_then_results_are_retrievable(self):
        status, job = self.request("/api/runs", "POST", {"source": "synthetic-demo", "seed": 20261014, "sample_fraction": 1})
        self.assertEqual(status, 202)
        deadline = time.time() + 30
        state = job
        while state["status"] in {"queued", "running"} and time.time() < deadline:
            time.sleep(.1)
            _, state = self.request(f"/api/runs/{job['run_id']}")
        self.assertEqual(state["status"], "completed", state)
        status, report = self.request(f"/api/runs/{job['run_id']}/results")
        self.assertEqual(status, 200)
        self.assertTrue(report["synthetic"])
        self.assertEqual(report["sample_fraction"], 1.0)
        self.assertFalse(report["threshold_policy"]["validation_selected"])
        self.assertIsNone(report["threshold_policy"]["recall_at_validation_selected_fpr_1_percent"])


if __name__ == "__main__":
    unittest.main()
