# VaultAI research prototype

VaultAI is a local AML/federated-learning research demo. Its current analysis uses generated synthetic rows. It is not a production banking, enforcement, or compliance system.

## Start the site and local API

Requires Python 3.10 or newer. The site and API use only Python's standard library; the included model experiment is also dependency-free.

```powershell
python dev_server.py
```

Then open `http://localhost:8000`. Sign in using the public demo account `demo@vaultai.dev` / `VaultAI@2026`, or create a local demo account. After signing in, choose **Run synthetic analysis** on the dashboard. The browser sends a same-origin `POST /api/runs`, receives a run ID, polls `GET /api/runs/{run_id}`, and fetches `GET /api/runs/{run_id}/results` when complete. The run is executed on a background worker so the request does not block while the model runs. The Infrastructure page and refresh button call `GET /api/health`.

API routes:

- `GET /api/health` reports API status and whether requested pipeline files / prediction artifacts are present.
- `POST /api/runs` accepts only `{ "source": "synthetic-demo", "seed": 20261014, "sample_fraction": 1 }`.
- `GET /api/runs/{run_id}` returns queued, running, completed, or failed state.
- `GET /api/runs/{run_id}/results` returns the completed experiment report.

Run records live in server memory and are cleared when the server restarts. Requests are limited and validated; browser-supplied paths and cross-origin run requests are rejected. API run results are in-memory and are not added to the bundled static results files.

## What this backend currently runs

`experiment.py` generates 18,000 synthetic behavior-feature rows across three simulated banks using seed `20261014`, applies a per-bank 75/25 split, trains three local logistic-regression baselines and runs 12 weighted model-averaging rounds. It evaluates against 4,500 held-out synthetic rows with a fixed 0.50 threshold. The API returns the same experiment report plus run metadata. You can also run it directly:

```powershell
python experiment.py
```

That command writes `data/experiment-results.json` and `data/experiment-data.js` for the bundled dashboard data loader. Labels come from a synthetic rule, not observed suspicious activity or banking ground truth.

The HI-Small files and `stage1.py`, `stage2.py`, `stage3.py` from the supplied integration brief are not in this workspace. Therefore this project does **not** yet implement that chronological 60/20/20 pipeline, validation-selected thresholds, recall at a validation-selected 1% FPR, its exact Stage 3 `protect(update)` FedAvg behavior, or HI-Small reporting. The health endpoint lists missing assets; the run endpoint does not pretend to execute those stages. No prediction route is exposed: `results.json` is not a trained inference model, and there is no matching inference feature pipeline or saved model artifact. Place the requested pipeline and approved data files in the project before integrating that real-data workflow. No AML data is sent to an external service.



## HI-Small benchmark results

The dashboard now includes a measured HI-Small run selector and opens that report by default when the report assets are present. The report was produced from the user-provided `HI-Small_Trans.csv` and `HI-Small_Patterns.txt`; the 475 MB transaction source is not copied into this repository. To reproduce it, run:

```powershell
python hi_small_experiment.py --data "PATH\TO\HI-Small_Trans.csv" --patterns "PATH\TO\HI-Small_Patterns.txt" --fraction 0.03
```

The command scans all valid source rows for overall counts and prior-only history, externally sorts timestamp-day chunks in the temporary directory, retains a seeded 3% sample for the model, and writes aggregate results to `data/hi-small-results.json` and `data/hi-small-data.js`. It maps the source bank codes into three simulated participants for the dashboard. The HI-Small pattern file reports 370 rings and 3,209 labeled pattern transactions. This is a development-sample result: the models are not trained on all 5,078,345 rows. The current run's validation-selected 1% FPR threshold produced zero detected positive examples on the held-out sample, so it is not a useful operational detector. `protect(update)` is identity; no privacy or secure-aggregation protection is applied. The investigation account graph remains a separate synthetic fixture.

## Privacy Lab CSV sweep

Open **Privacy Lab**, browse for a prepared CSV, choose its binary target column, and run the sweep. The browser posts the selected file contents to this same-origin local server; the server parses it in memory, starts a background job, and returns the run status/results over `/api/privacy-sweeps`. Source file paths are never sent or accepted. CSV content is limited to 5 MB and 5,000 rows, with 1?12 numeric feature columns and an optional timestamp. Rows are sorted by timestamp when provided; otherwise uploaded row order is kept for 60/20/20 splitting. Both target classes must appear in each partition. Remove direct identifiers and encode categorical fields before upload.

The sweep compares a regularized logistic model to five isotropic Laplace output-perturbation settings (epsilon 0.25, 0.5, 1, 2, and 4). It selects each model threshold on validation data under a 1% validation false-positive-rate cap, then displays held-out metrics. This is a single-model local research demonstration, not federated DP. The finite-iteration optimizer and displayed test metrics are not formally privacy-certified, so do not treat the results as a production guarantee or public release. The uploaded CSV is not written to disk and is not sent to external services; the in-memory job and results disappear when the server restarts. Do not upload real personal or banking information.

## Local demo authentication and stored data

Authentication is intentionally client-side demo authentication, not backend authentication. The demo credential is public; local account/session storage is user-controlled. Use no real password, customer detail, or banking data. Password recovery sends no email. Investigation notes/status and synthetic account fixtures remain browser-local. Replace the auth service and add server-side identity/authorization before real users or sensitive data.

## Checks

```powershell
python -m unittest tests.test_api -v
node --test tests/auth-service.test.js
```

Privacy sweep results, scalability telemetry, cryptographic secure aggregation, differential privacy, real bank connections, and verified IBM LinuxONE deployment are not implemented or claimed.
