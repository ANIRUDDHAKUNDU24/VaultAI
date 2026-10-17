"""Local same-origin static server and API for the existing synthetic experiment.

This server does not implement user authentication. It starts only the synthetic
experiment currently present in this repository; the HI-Small Stage 1–3 pipeline
described in the project brief is not included here.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import uuid
from urllib.parse import urlsplit

import experiment
import privacy_sweep

ROOT = Path(__file__).resolve().parent
SPA_ROUTES = {"/", "/index.html", "/login", "/signup", "/dashboard", "/forgot-password",
              "/compare", "/privacy", "/investigate", "/infrastructure"}
AVAILABLE_STAGE_FILES = ("stage1.py", "stage2.py", "stage3.py", "HI-Small_Trans.csv")
jobs = {}
jobs_lock = threading.Lock()
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vaultai-experiment")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_results(run_id, sample_fraction):
    """Run the included repeatable synthetic model and clearly mark its limits."""
    report = experiment.run_experiment()
    report["api_run_id"] = run_id
    report["sample_fraction"] = sample_fraction
    report["data_source"] = "generated synthetic fixture; no source transaction file"
    report["threshold_policy"] = {
        "method": "fixed 0.50 threshold from the existing demo experiment",
        "validation_selected": False,
        "validation_data_available": False,
        "recall_at_validation_selected_fpr_1_percent": None,
        "note": "The repository has no validation split or Stage 1–3 pipeline.",
    }
    return report


def execute_run(run_id, sample_fraction):
    """Run model work outside the HTTP request thread and store its result."""
    with jobs_lock:
        jobs[run_id]["status"] = "running"
        jobs[run_id]["started_at_utc"] = utc_now()
    try:
        results = create_results(run_id, sample_fraction)
        with jobs_lock:
            jobs[run_id].update(status="completed", completed_at_utc=utc_now(), results=results)
    except Exception as exc:  # Keep internal details out of the public API response.
        with jobs_lock:
            jobs[run_id].update(status="failed", completed_at_utc=utc_now(),
                                error="The synthetic experiment failed. Check the server console.")
        print(f"VaultAI run {run_id} failed: {type(exc).__name__}: {exc}")


def execute_privacy_sweep(run_id, dataset):
    """Run the privacy comparison away from the HTTP request thread."""
    with jobs_lock:
        jobs[run_id]["status"] = "running"
        jobs[run_id]["started_at_utc"] = utc_now()
    try:
        report = privacy_sweep.run_sweep(dataset)
        with jobs_lock:
            jobs[run_id].update(status="completed", completed_at_utc=utc_now(), results=report)
    except Exception as exc:
        with jobs_lock:
            jobs[run_id].update(status="failed", completed_at_utc=utc_now(),
                                error="Privacy sweep failed. Check the local server console.")
        print(f"VaultAI privacy sweep {run_id} failed: {type(exc).__name__}: {exc}")


class SPAHandler(SimpleHTTPRequestHandler):
    """Serve frontend routes and JSON API endpoints from one local origin."""

    server_version = "VaultAI-Local-Demo"
    sys_version = ""

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_json(self, status, body):
        payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def api_health(self):
        missing = [name for name in AVAILABLE_STAGE_FILES if not (ROOT / name).is_file()]
        return {"status": "ok", "service": "vaultai-local-demo-api",
                "analysis_mode": "synthetic-demo", "synthetic_pipeline_available": True,
                "requested_stage_1_3_pipeline_available": not missing,
                "missing_stage_assets": missing,
                "prediction_available": False,
                "prediction_reason": "No trained inference artifact and matching feature pipeline are present.",
                "dataset_upload_supported": False,
                "privacy_csv_sweep_supported": True,
                "timestamp_utc": utc_now()}

    def read_json_body(self, max_bytes=4096):
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise ValueError("Send request data as application/json.")
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid Content-Length.") from exc
        if size < 0 or size > max_bytes:
            raise ValueError("Request body exceeds the allowed size.")
        try:
            body = json.loads(self.rfile.read(size) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("Request body must contain valid JSON.") from exc
        if not isinstance(body, dict):
            raise ValueError("Request body must be a JSON object.")
        return body

    def same_origin_post(self):
        """Reject cross-origin run requests; the app and API are served together."""
        origin = self.headers.get("Origin")
        if not origin:
            return True
        parsed = urlsplit(origin)
        return bool(parsed.netloc and parsed.netloc.lower() == self.headers.get("Host", "").lower()
                    and parsed.scheme in {"http", "https"})

    def do_GET(self):
        parsed = urlsplit(self.path)
        path = parsed.path
        if path == "/api/health":
            self.send_json(200, self.api_health())
            return
        if path.startswith(("/api/runs/", "/api/privacy-sweeps/")):
            parts = path.strip("/").split("/")
            is_privacy = parts[1] == "privacy-sweeps"
            if len(parts) not in (3, 4) or (len(parts) == 4 and parts[3] != "results"):
                self.send_json(404, {"detail": "API route not found."})
                return
            run_id = parts[2]
            with jobs_lock:
                job = jobs.get(run_id)
                snapshot = dict(job) if job else None
            if not snapshot:
                self.send_json(404, {"detail": "Run was not found in this server session."})
                return
            if len(parts) == 4:
                if snapshot["status"] != "completed":
                    self.send_json(409, {"detail": "Run results are not ready.", "status": snapshot["status"]})
                    return
                self.send_json(200, snapshot["results"])
                return
            snapshot.pop("results", None)
            self.send_json(200, snapshot)
            return
        if path.startswith("/api/"):
            self.send_json(404, {"detail": "API route not found."})
            return
        if path in SPA_ROUTES:
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        path = urlsplit(self.path).path
        if path not in {"/api/runs", "/api/privacy-sweeps"}:
            self.send_json(404, {"detail": "API route not found."})
            return
        if not self.same_origin_post():
            self.send_json(403, {"detail": "Cross-origin request rejected."})
            return
        try:
            body = self.read_json_body(10 * 1024 * 1024 if path == "/api/privacy-sweeps" else 4096)
        except ValueError as exc:
            self.send_json(400, {"detail": str(exc)})
            return
        if path == "/api/privacy-sweeps":
            if set(body) != {"csv_text", "target"}:
                self.send_json(422, {"detail": "Choose a CSV file and a binary target column. File paths are never accepted."})
                return
            csv_text, target = body.get("csv_text"), body.get("target")
            if not isinstance(csv_text, str) or len(csv_text.encode("utf-8")) > 5 * 1024 * 1024:
                self.send_json(413, {"detail": "CSV content must be 5 MB or smaller."})
                return
            if not isinstance(target, str) or len(target) > 128:
                self.send_json(422, {"detail": "Select a valid target column."})
                return
            try:
                dataset = privacy_sweep.parse_csv(csv_text, target)
            except ValueError as exc:
                self.send_json(422, {"detail": str(exc)})
                return
            run_id = "privacy-" + uuid.uuid4().hex[:12]
            job = {"run_id": run_id, "status": "queued", "created_at_utc": utc_now(),
                   "source": "local CSV in memory", "row_count": dataset["row_count"]}
            with jobs_lock:
                jobs[run_id] = job
            executor.submit(execute_privacy_sweep, run_id, dataset)
            self.send_json(202, job)
            return

        allowed_keys = {"source", "seed", "sample_fraction"}
        if set(body) - allowed_keys:
            self.send_json(422, {"detail": "Only source, seed, and sample_fraction are accepted; filesystem paths and uploads are not supported."})
            return
        source = body.get("source", "synthetic-demo")
        seed = body.get("seed", experiment.SEED)
        fraction = body.get("sample_fraction", 1.0)
        if source != "synthetic-demo":
            self.send_json(422, {"detail": "Only the included synthetic demo experiment is available in this repository."})
            return
        if type(seed) is not int or seed != experiment.SEED:
            self.send_json(422, {"detail": f"The included reproducible experiment uses the fixed seed {experiment.SEED}."})
            return
        if type(fraction) not in (int, float) or fraction != 1.0:
            self.send_json(422, {"detail": "The current synthetic experiment runs its complete generated dataset; sample_fraction must be 1.0."})
            return
        run_id = "api-" + uuid.uuid4().hex[:12]
        job = {"run_id": run_id, "status": "queued", "created_at_utc": utc_now(),
               "sample_fraction": 1.0, "source": source}
        with jobs_lock:
            jobs[run_id] = job
        executor.submit(execute_run, run_id, 1.0)
        self.send_json(202, job)


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer((host, port), partial(SPAHandler, directory=str(ROOT)))
    display_host = "localhost" if host in {"127.0.0.1", "0.0.0.0"} else host
    print(f"VaultAI app/API: http://{display_host}:{port}/login (Ctrl+C to stop)")
    print(f"API health: http://{display_host}:{port}/api/health")
    server.serve_forever()
