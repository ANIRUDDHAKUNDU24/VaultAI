"""Local CSV privacy/utility demonstration using regularized logistic output perturbation.

Input must be a prepared feature table: binary target, numeric bounded/normalizable
features, and optionally a timestamp column. Raw account identifiers are not accepted
as features by policy: callers must remove them before selecting an experiment file.
"""
import csv
import math
import secrets
from datetime import datetime
from io import StringIO

EPSILONS = (0.25, 0.5, 1.0, 2.0, 4.0)
TARGET_VALUES = {"0": 0, "1": 1, "false": 0, "true": 1}
MAX_ROWS = 5000
MAX_FEATURES = 12
L2 = 1.0


def _timestamp(value):
    if not value or not value.strip():
        raise ValueError("Timestamp values cannot be empty.")
    value = value.strip()
    for fmt in ("%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    raise ValueError("Timestamp values must use YYYY/MM/DD HH:MM or an ISO date/time format.")


def parse_csv(csv_text, target):
    """Validate uploaded text and return ordered numeric rows plus clear metadata."""
    if not isinstance(csv_text, str) or not csv_text.strip():
        raise ValueError("Choose a non-empty CSV file.")
    try:
        reader = csv.DictReader(StringIO(csv_text.lstrip("\ufeff"), newline=""))
        fields = reader.fieldnames or []
        if len(fields) < 2 or len(fields) > MAX_FEATURES + 2 or len(set(fields)) != len(fields):
            raise ValueError(f"CSV must have unique headers, one target, and at most {MAX_FEATURES} numeric features.")
        if target not in fields:
            raise ValueError("The selected target column is not in this CSV.")
        time_col = next((name for name in fields if name.strip().casefold() in {"timestamp", "time", "datetime"}), None)
        feature_cols = [name for name in fields if name != target and name != time_col]
        if not feature_cols or len(feature_cols) > MAX_FEATURES:
            raise ValueError(f"CSV needs between 1 and {MAX_FEATURES} numeric feature columns (timestamp is optional).")
        sensitive_name = lambda name: any(token in name.casefold().replace("-", "_") for token in ("account", "customer", "name", "bank", "identifier")) or name.casefold().endswith("_id") or name.casefold() == "id"
        if any(sensitive_name(name) for name in feature_cols):
            raise ValueError("Remove account IDs, bank IDs, customer names, and other direct identifiers from feature columns before upload.")
        records = []
        for line_number, row in enumerate(reader, start=2):
            if line_number > MAX_ROWS + 1:
                raise ValueError(f"CSV is limited to {MAX_ROWS:,} data rows.")
            if None in row:
                raise ValueError(f"Row {line_number} has more values than the header.")
            label_text = (row.get(target) or "").strip().casefold()
            if label_text not in TARGET_VALUES:
                raise ValueError(f"Target '{target}' must contain only 0/1 or false/true values (row {line_number}).")
            try:
                values = [float(row[name]) for name in feature_cols]
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Feature columns must be numeric; check row {line_number}.") from exc
            if not all(math.isfinite(value) for value in values):
                raise ValueError(f"Feature values must be finite numbers (row {line_number}).")
            at = _timestamp(row[time_col]) if time_col else None
            records.append((at, values, TARGET_VALUES[label_text]))
        if len(records) < 60:
            raise ValueError("Provide at least 60 rows so train, validation, and test partitions have usable samples.")
        if time_col:
            records.sort(key=lambda record: record[0])
        cut_train, cut_val = int(len(records) * .6), int(len(records) * .8)
        if cut_train < 2 or cut_val - cut_train < 2 or len(records) - cut_val < 2:
            raise ValueError("The CSV is too small for chronological train, validation, and test partitions.")
        labels_by_part = [records[:cut_train], records[cut_train:cut_val], records[cut_val:]]
        for title, partition in zip(("training", "validation", "test"), labels_by_part):
            if len({row[2] for row in partition}) != 2:
                raise ValueError(f"Both target classes must appear in the chronological {title} partition.")
        return {"records": [(values, label) for _, values, label in records],
                "features": feature_cols, "target": target, "row_count": len(records),
                "timestamp_sorted": bool(time_col), "time_column": time_col}
    except csv.Error as exc:
        raise ValueError("Could not parse the CSV. Check its quoting and delimiter.") from exc


def _sigmoid(z):
    if z >= 0:
        exp = math.exp(-min(z, 700))
        return 1 / (1 + exp)
    exp = math.exp(max(z, -700))
    return exp / (1 + exp)


def _fit(rows, labels, dimensions):
    """Fit a deterministic, regularized logistic model to the training partition."""
    weights = [0.0] * dimensions
    step = 1.0 / (1.0 + .25 * dimensions)
    count = len(rows)
    for _ in range(250):
        gradient = [L2 * w for w in weights]
        for x, y in zip(rows, labels):
            error = _sigmoid(sum(w * value for w, value in zip(weights, x))) - y
            for index, value in enumerate(x):
                gradient[index] += error * value / count
        weights = [w - step * g for w, g in zip(weights, gradient)]
    return weights


def _private_weights(weights, epsilon, sensitivity, rng):
    """Sample isotropic L2-Laplace noise using a cryptographic system RNG."""
    dimensions = len(weights)
    direction = [rng.gauss(0, 1) for _ in range(dimensions)]
    norm = math.sqrt(sum(value * value for value in direction)) or 1.0
    radius = sum(-math.log(max(rng.random(), 1e-300)) for _ in range(dimensions)) * sensitivity / epsilon
    return [weight + radius * value / norm for weight, value in zip(weights, direction)]


def _scores(weights, rows):
    return [_sigmoid(sum(w * value for w, value in zip(weights, row))) for row in rows]


def _choose_threshold(scores, labels):
    candidates = sorted(set(scores), reverse=True)
    candidates.append(math.nextafter(max(scores), math.inf))
    negatives = max(1, sum(label == 0 for label in labels))
    positives = max(1, sum(labels))
    feasible = []
    for threshold in candidates:
        tp = sum(score >= threshold and label == 1 for score, label in zip(scores, labels))
        fp = sum(score >= threshold and label == 0 for score, label in zip(scores, labels))
        fpr = fp / negatives
        if fpr <= .01:
            feasible.append((tp / positives, -fpr, threshold))
    return max(feasible)[2]


def _metrics(scores, labels, threshold):
    tp = sum(score >= threshold and label == 1 for score, label in zip(scores, labels))
    fp = sum(score >= threshold and label == 0 for score, label in zip(scores, labels))
    fn = sum(score < threshold and label == 1 for score, label in zip(scores, labels))
    tn = sum(score < threshold and label == 0 for score, label in zip(scores, labels))
    positives = max(1, sum(labels))
    ranked = sorted(zip(scores, labels), reverse=True)
    seen_pos = 0
    average_precision = 0.0
    for rank, (_, label) in enumerate(ranked, start=1):
        if label:
            seen_pos += 1
            average_precision += (seen_pos / rank) / positives
    return {"recall": tp / max(1, tp + fn), "precision": tp / max(1, tp + fp),
            "fpr": fp / max(1, fp + tn), "prauc": average_precision,
            "threshold": threshold, "n": len(labels), "pos": sum(labels)}


def run_sweep(dataset):
    """Compare non-private and output-perturbed models on shared chronological splits."""
    records = dataset["records"]
    n = len(records)
    train_end, val_end = int(n * .6), int(n * .8)
    raw_train = records[:train_end]
    raw_val = records[train_end:val_end]
    raw_test = records[val_end:]
    feature_count = len(dataset["features"])
    mins = [min(row[0][j] for row in raw_train) for j in range(feature_count)]
    maxs = [max(row[0][j] for row in raw_train) for j in range(feature_count)]

    def transform(part):
        result, labels = [], []
        for values, label in part:
            normalized = [0.0 if maxs[j] == mins[j] else min(1.0, max(0.0, (values[j] - mins[j]) / (maxs[j] - mins[j]))) for j in range(feature_count)]
            result.append([1.0, *normalized])
            labels.append(label)
        return result, labels

    x_train, y_train = transform(raw_train)
    x_val, y_val = transform(raw_val)
    x_test, y_test = transform(raw_test)
    dimensions = feature_count + 1
    base = _fit(x_train, y_train, dimensions)
    settings = [{"epsilon": epsilon, "mechanism": "L2 output perturbation (isotropic Laplace)", "sensitivity_l2": 2 * math.sqrt(dimensions) / (len(x_train) * L2)} for epsilon in EPSILONS]
    models = [(None, base)]
    rng = secrets.SystemRandom()
    for setting in settings:
        models.append((setting, _private_weights(base, setting["epsilon"], setting["sensitivity_l2"], rng)))
    results = []
    for setting, weights in models:
        validation_scores = _scores(weights, x_val)
        threshold = _choose_threshold(validation_scores, y_val)
        result = _metrics(_scores(weights, x_test), y_test, threshold)
        result.update({"epsilon": setting["epsilon"] if setting else None,
                       "mechanism": setting["mechanism"] if setting else "No privacy noise (baseline)"})
        results.append(result)
    return {"target": dataset["target"], "features": dataset["features"],
            "rows": n, "train_rows": len(x_train), "validation_rows": len(x_val),
            "test_rows": len(x_test), "timestamp_sorted": dataset["timestamp_sorted"],
            "privacy_model": "Pure epsilon-DP output perturbation of an L2-regularized logistic objective; replace-one adjacency; normalized features clipped to [0,1]; cryptographic noise randomness.",
            "privacy_caveat": "The finite-iteration optimizer and displayed test metrics have not received formal privacy certification. Treat this as a local research demonstration, not a production DP guarantee or public release.",
            "threshold_policy": "Threshold chosen independently for each model on the validation partition at no more than 1% validation FPR; test labels are used only for final metrics.",
            "results": results}
