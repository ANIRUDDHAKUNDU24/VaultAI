"""Streaming HI-Small benchmark sample and three-participant logistic FedAvg report.

The large source CSV is read in one pass. Only a seeded 1% sample is retained,
so no full-table data-science frame or source-row IDs are written to the project.
"""
from __future__ import annotations

import argparse
import csv
import heapq
import json
import math
import random
import re
import tempfile
from collections import defaultdict
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

SEED = 42
SAMPLE_FRACTION = 0.03
PARTICIPANTS = 3
ROUNDS = 12
LOCAL_STEPS = 2
COLUMNS = ("timestamp", "from_bank", "from_acc", "to_bank", "to_acc", "amt_received", "cur_received", "amt_paid", "cur_paid", "pay_format", "is_laundering")
PAYMENT_FORMATS = ("ACH", "Cash", "Cheque", "Credit Card", "Cross-border", "Reinvestment", "Wire")
FEATURE_NAMES = ("log_amount_received", "log_amount_paid", "same_currency", "same_account", "sender_perspective", "hour_of_day", "prior_transaction_count", "prior_mean_amount", "hours_since_prior", "prior_total_amount", "format_ach", "format_cash", "format_cheque", "format_credit_card", "format_cross_border", "format_reinvestment", "format_wire", "format_other")


def spool_source_by_day(csv_path: Path, fraction: float, work_dir: Path):
    """Count all valid source rows and spool them into daily files for bounded-memory sorting."""
    rng = random.Random(SEED)
    writers, handles = {}, {}
    bank_ids = set()
    total_rows = positive_rows = invalid_rows = sample_count = 0
    first_time = last_time = None
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream)
            header = next(reader, None)
            if header is None or len(header) != len(COLUMNS):
                raise ValueError("HI-Small CSV must have 11 columns; its duplicate Account headers are handled by position.")
            for row in reader:
                if len(row) != len(COLUMNS):
                    invalid_rows += 1
                    continue
                try:
                    stamp = row[0].strip()
                    label = int(row[10])
                    received, paid = float(row[5]), float(row[7])
                    if label not in (0, 1) or not math.isfinite(received) or not math.isfinite(paid):
                        raise ValueError
                    datetime.strptime(stamp, "%Y/%m/%d %H:%M")
                except (ValueError, IndexError):
                    invalid_rows += 1
                    continue
                total_rows += 1
                positive_rows += label
                first_time = stamp if first_time is None or stamp < first_time else first_time
                last_time = stamp if last_time is None or stamp > last_time else last_time
                bank_ids.update((row[1].strip(), row[3].strip()))
                selected = int(rng.random() < fraction)
                sample_count += selected
                day = stamp[:10].replace("/", "-")
                if day not in writers:
                    handle = (work_dir / f"{day}.csv").open("w", encoding="utf-8", newline="")
                    handles[day] = handle
                    writers[day] = csv.writer(handle)
                # Source row index provides a stable tiebreaker for same-minute rows.
                writers[day].writerow((total_rows - 1, selected, *row))
    finally:
        for handle in handles.values():
            handle.close()
    return {"total_rows": total_rows, "positive_rows": positive_rows,
            "invalid_rows": invalid_rows, "bank_ids": bank_ids,
            "first_timestamp": first_time, "last_timestamp": last_time,
            "sample_count": sample_count, "sample_fraction": sample_count / max(1, total_rows),
            "requested_sample_fraction": fraction,
            "daily_files": sorted(work_dir.glob("*.csv"))}


def build_bank_features_from_full_history(source):
    """External-sort daily chunks and featurize sampled rows from complete prior history."""
    mapping = {bank_id: f"bank_{(index % PARTICIPANTS) + 1}"
               for index, bank_id in enumerate(sorted(source["bank_ids"]))}
    group_rows = {f"bank_{i + 1}": [] for i in range(PARTICIPANTS)}
    history = {}
    sample_index = 0
    train_end = int(source["sample_count"] * .6)
    validation_end = int(source["sample_count"] * .8)
    for daily_file in source["daily_files"]:
        sorted_chunks = []
        with daily_file.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.reader(stream)
            while True:
                chunk = []
                try:
                    for _ in range(15000):
                        chunk.append(next(reader))
                except StopIteration:
                    pass
                if not chunk:
                    break
                chunk.sort(key=lambda row: (row[2], int(row[0])))
                chunk_path = daily_file.with_name(daily_file.stem + f"-sorted-{len(sorted_chunks):03d}.csv")
                with chunk_path.open("w", encoding="utf-8", newline="") as chunk_stream:
                    csv.writer(chunk_stream).writerows(chunk)
                sorted_chunks.append(chunk_path)
                if len(chunk) < 15000:
                    break
        daily_file.unlink()
        with ExitStack() as stack:
            iterators = []
            for chunk_path in sorted_chunks:
                chunk_stream = stack.enter_context(chunk_path.open("r", encoding="utf-8", newline=""))
                iterators.append(csv.reader(chunk_stream))
            merged = heapq.merge(*iterators, key=lambda row: (row[2], int(row[0])))
            current_stamp = None
            current_at = None
            history_updates = []
            for stored in merged:
                stamp = stored[2]
                if current_stamp is not None and stamp != current_stamp:
                    for account_key, amount in history_updates:
                        count, total, _ = history.get(account_key, (0, 0.0, None))
                        history[account_key] = (count + 1, total + amount, current_at)
                    history_updates = []
                if stamp != current_stamp:
                    current_stamp = stamp
                    current_at = datetime.strptime(stamp, "%Y/%m/%d %H:%M")
                chosen = bool(int(stored[1]))
                row = stored[2:]
                _, from_bank, from_acc, to_bank, to_acc, rec_amt, rec_cur, paid_amt, paid_cur, payment, label = row
                rec_amt, paid_amt, label = float(rec_amt), float(paid_amt), int(label)
                sender_key, receiver_key = (from_bank, from_acc), (to_bank, to_acc)
                sender_group, receiver_group = mapping[from_bank], mapping[to_bank]
                perspectives = [(sender_group, sender_key, receiver_key, 1)]
                if receiver_group != sender_group:
                    perspectives.append((receiver_group, receiver_key, sender_key, 0))
                if chosen:
                    split = "train" if sample_index < train_end else "validation" if sample_index < validation_end else "test"
                    hour = current_at.hour / 23.0
                    fmt = payment.casefold()
                    known_formats = {name.casefold() for name in PAYMENT_FORMATS}
                    for bank_group, account_key, _counterparty_key, is_sender in perspectives:
                        state = history.get(account_key)
                        prior_count, total_amount, last_at = state if state else (0, 0.0, None)
                        gap_hours = min(1.0, math.log1p(max(0.0, (current_at - last_at).total_seconds() / 3600)) / 12.0) if last_at else 1.0
                        mean_amount = total_amount / prior_count if prior_count else 0.0
                        x = [min(1.0, math.log1p(max(0.0, rec_amt)) / 16.0),
                             min(1.0, math.log1p(max(0.0, paid_amt)) / 16.0),
                             float(rec_cur.casefold() == paid_cur.casefold()), float(sender_key == receiver_key),
                             float(is_sender), hour, min(1.0, math.log1p(prior_count) / 12.0),
                             min(1.0, math.log1p(mean_amount) / 16.0), gap_hours,
                             min(1.0, math.log1p(total_amount) / 20.0)]
                        x.extend(float(fmt == name.casefold()) for name in PAYMENT_FORMATS)
                        x.append(float(fmt not in known_formats))
                        group_rows[bank_group].append((sample_index, x, label, split))
                    sample_index += 1
                history_updates.append((sender_key, paid_amt))
                if receiver_key != sender_key:
                    history_updates.append((receiver_key, rec_amt))
            if current_stamp is not None:
                for account_key, amount in history_updates:
                    count, total, _ = history.get(account_key, (0, 0.0, None))
                    history[account_key] = (count + 1, total + amount, current_at)
        for chunk_path in sorted_chunks:
            chunk_path.unlink()
    if sample_index != source["sample_count"]:
        raise RuntimeError("Sample row count changed while reading the temporary chronological files.")
    return group_rows

def read_pattern_summary(pattern_path: Path):
    """Count laundering-pattern rings without including their account identifiers."""
    ring_types = defaultdict(lambda: {"rings": 0, "transactions": 0})
    active = None
    for line in pattern_path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("BEGIN LAUNDERING ATTEMPT"):
            match = re.search(r"ATTEMPT\s*-\s*([A-Z0-9_-]+)", stripped)
            active = match.group(1) if match else "OTHER"
            ring_types[active]["rings"] += 1
        elif stripped.startswith("END LAUNDERING ATTEMPT"):
            active = None
        elif active and stripped:
            ring_types[active]["transactions"] += 1
    return {"ring_count": sum(item["rings"] for item in ring_types.values()),
            "labeled_pattern_transactions": sum(item["transactions"] for item in ring_types.values()),
            "types": dict(sorted(ring_types.items()))}


def build_bank_features(sample, bank_ids):
    """Construct past-only account features, with cross-bank rows in both views."""
    mapping = {bank_id: f"bank_{(index % PARTICIPANTS) + 1}" for index, bank_id in enumerate(sorted(bank_ids))}
    group_rows = {f"bank_{i + 1}": [] for i in range(PARTICIPANTS)}
    # State contains only prior observed transaction counts, amounts and counterparties.
    history = {}
    previous_time = None
    split_index = {int(len(sample) * .6): "validation", int(len(sample) * .8): "test"}
    for index, row in enumerate(sample):
        stamp, from_bank, from_acc, to_bank, to_acc, received, recv_cur, paid, paid_cur, payment, label = row
        at = datetime.strptime(stamp, "%Y/%m/%d %H:%M")
        if previous_time is not None and at < previous_time:
            raise ValueError("Sample timestamps did not sort chronologically.")
        previous_time = at
        mapped_from, mapped_to = mapping[from_bank], mapping[to_bank]
        perspectives = [(mapped_from, from_acc, to_acc, 1)]
        if mapped_to != mapped_from:
            perspectives.append((mapped_to, to_acc, from_acc, 0))
        hour = at.hour / 23.0
        fmt = payment.casefold()
        for group, account, counterparty, is_sender in perspectives:
            key = (group, account)
            state = history.get(key)
            count = state[0] if state else 0
            amount_sum = state[1] if state else 0.0
            last_at = state[2] if state else None
            prior_counterparties = state[3] if state else set()
            gap_hours = min(1.0, math.log1p(max(0.0, (at - last_at).total_seconds() / 3600)) / 12.0) if last_at else 1.0
            mean_amount = amount_sum / count if count else 0.0
            x = [min(1.0, math.log1p(max(0.0, received)) / 16.0),
                 min(1.0, math.log1p(max(0.0, paid)) / 16.0),
                 float(recv_cur.casefold() == paid_cur.casefold()), float(from_acc == to_acc),
                 float(is_sender), hour, min(1.0, math.log1p(count) / 12.0),
                 min(1.0, math.log1p(mean_amount) / 16.0), gap_hours,
                 min(1.0, math.log1p(len(prior_counterparties)) / 10.0)]
            x.extend(float(fmt == name.casefold()) for name in PAYMENT_FORMATS)
            x.append(float(fmt not in {name.casefold() for name in PAYMENT_FORMATS}))
            split = "train" if index < int(len(sample) * .6) else "validation" if index < int(len(sample) * .8) else "test"
            group_rows[group].append((index, x, label, split))
            if state is None:
                state = [0, 0.0, None, set()]
                history[key] = state
            state[0] += 1
            state[1] += paid if is_sender else received
            state[2] = at
            state[3].add(counterparty)
    return group_rows


def sigmoid(value):
    value = max(-35.0, min(35.0, value))
    return 1.0 / (1.0 + math.exp(-value))


def fit_logistic(rows, initial=None, epochs=24):
    """Fit one regularized model; positive-class weight is derived from training rows."""
    if not rows:
        raise ValueError("A simulated bank has no rows in the training split.")
    dimensions = len(FEATURE_NAMES) + 1
    weights = list(initial) if initial is not None else [0.0] * dimensions
    positives = sum(item[2] for item in rows)
    negatives = len(rows) - positives
    if positives == 0:
        raise ValueError("A bank's 1% sample has no positive training examples. Use a larger sample fraction.")
    positive_weight = min(100.0, negatives / positives)
    learning_rate = 0.16 / math.sqrt(dimensions)
    for _ in range(epochs):
        gradient = [0.001 * weight for weight in weights]
        for _, features, label, _split in rows:
            vector = (1.0, *features)
            error = sigmoid(sum(weight * value for weight, value in zip(weights, vector))) - label
            if label:
                error *= positive_weight
            for column, value in enumerate(vector):
                gradient[column] += error * value / len(rows)
        weights = [weight - learning_rate * value for weight, value in zip(weights, gradient)]
    return weights


def model_update_protection(update):
    """Stage 3 hook. Current implementation leaves updates unchanged; no privacy is claimed."""
    return update


def predict(weights, rows):
    return [sigmoid(weights[0] + sum(weight * value for weight, value in zip(weights[1:], features)))
            for _, features, _label, _split in rows]


def select_threshold(scores, rows, max_fpr=0.01):
    """Select highest-recall validation threshold under the stated FPR limit."""
    ranked = sorted(((score, row[2]) for score, row in zip(scores, rows)), reverse=True)
    negatives = sum(not label for _, label in ranked)
    if not negatives:
        return math.inf
    allowed_fp = math.floor(max_fpr * negatives)
    tp = fp = 0
    best_tp, best_threshold = -1, math.inf
    index = 0
    while index < len(ranked):
        threshold = ranked[index][0]
        while index < len(ranked) and ranked[index][0] == threshold:
            if ranked[index][1]:
                tp += 1
            else:
                fp += 1
            index += 1
        if fp <= allowed_fp and tp > best_tp:
            best_tp, best_threshold = tp, threshold
    return best_threshold


def evaluate(weights, rows, threshold):
    scores = predict(weights, rows)
    labels = [row[2] for row in rows]
    tp = sum(score >= threshold and label for score, label in zip(scores, labels))
    fp = sum(score >= threshold and not label for score, label in zip(scores, labels))
    fn = sum(score < threshold and label for score, label in zip(scores, labels))
    tn = sum(score < threshold and not label for score, label in zip(scores, labels))
    positives = max(1, sum(labels))
    ranked = sorted(zip(scores, labels), reverse=True)
    seen = seen_positive = average_precision = 0
    for _, label in ranked:
        seen += 1
        if label:
            seen_positive += 1
            average_precision += seen_positive / seen / positives
    return {"recall": tp / max(1, tp + fn), "precision": tp / max(1, tp + fp),
            "prauc": average_precision, "fpr": fp / max(1, fp + tn),
            "threshold": threshold if math.isfinite(threshold) else 1.0,
            "n": len(rows), "pos": sum(labels), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "unique_transactions": len({row[0] for row in rows})}


def evaluate_model(name, weights, validation, test):
    threshold = select_threshold(predict(weights, validation), validation)
    return {"name": name, **evaluate(weights, test, threshold),
            "validation_threshold_fpr_limit": 0.01}


def run_models(group_rows):
    """Train three local baselines and 12 rounds of weighted flat-vector FedAvg."""
    names = sorted(group_rows)
    train_by_bank = {name: [row for row in group_rows[name] if row[3] == "train"] for name in names}
    val_by_bank = {name: [row for row in group_rows[name] if row[3] == "validation"] for name in names}
    test_by_bank = {name: [row for row in group_rows[name] if row[3] == "test"] for name in names}
    local = {name: fit_logistic(train_by_bank[name], epochs=24) for name in names}
    results = []
    for name in names:
        results.append(evaluate_model(f"{name} isolated", local[name], val_by_bank[name], test_by_bank[name]))
    shared = [0.0] * (len(FEATURE_NAMES) + 1)
    for _round in range(ROUNDS):
        updates, counts = [], []
        for name in names:
            # Each participant starts this round from the same shared model vector.
            local_weights = fit_logistic(train_by_bank[name], initial=shared, epochs=LOCAL_STEPS)
            update = [new - old for new, old in zip(local_weights, shared)]
            update = model_update_protection(update)
            updates.append(update)
            counts.append(len(train_by_bank[name]))
        denominator = sum(counts)
        shared = [old + sum(update[j] * count for update, count in zip(updates, counts)) / denominator
                  for j, old in enumerate(shared)]
    validation_all = [row for name in names for row in val_by_bank[name]]
    test_all = [row for name in names for row in test_by_bank[name]]
    results.append(evaluate_model("VaultAI federated", shared, validation_all, test_all))
    return results, {"train_examples_by_bank": {k: len(v) for k, v in train_by_bank.items()},
                     "validation_examples_by_bank": {k: len(v) for k, v in val_by_bank.items()},
                     "test_examples_by_bank": {k: len(v) for k, v in test_by_bank.items()}}


def run(data_path: Path, patterns_path: Path, fraction: float):
    """Run a seeded sample using complete chronological history, then clean temp files."""
    with tempfile.TemporaryDirectory(prefix="vaultai-hi-small-") as temp_name:
        source = spool_source_by_day(data_path, fraction, Path(temp_name))
        group_rows = build_bank_features_from_full_history(source)
        results, partition_counts = run_models(group_rows)
        pattern_summary = read_pattern_summary(patterns_path)
        sample_labels = {}
        for participant_rows in group_rows.values():
            for transaction_index, _features, label, split in participant_rows:
                sample_labels.setdefault(transaction_index, (label, split))
        sample_positive = sum(label for label, _split in sample_labels.values())
        split_counts = {
            name: {"rows": sum(split == name for _label, split in sample_labels.values()),
                   "positives": sum(label for label, split in sample_labels.values() if split == name)}
            for name in ("train", "validation", "test")
        }
    report = {"run_id": "HI-SMALL-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            "label": "HI-Small transaction benchmark - seeded development sample",
            "dataset": "HI-Small_Trans.csv", "dataset_type": "user-provided labeled transaction benchmark",
            "full_data_analyzed_for_counts": True, "full_data_model_training": False,
            "sample_fraction": source["sample_fraction"], "requested_sample_fraction": fraction,
            "seed": SEED, "source_rows": source["total_rows"], "source_positive_rows": source["positive_rows"],
            "source_laundering_rate": source["positive_rows"] / max(1, source["total_rows"]),
            "invalid_rows_skipped": source["invalid_rows"], "sample_rows": source["sample_count"],
            "sample_positive_rows": sample_positive, "sample_split_counts": split_counts,
            "first_timestamp": source["first_timestamp"], "last_timestamp": source["last_timestamp"],
            "source_bank_id_count": len(source["bank_ids"]), "simulated_participants": PARTICIPANTS,
            "pattern_summary": pattern_summary,
            "train_rows": int(source["sample_count"] * .6),
            "validation_rows": int(source["sample_count"] * .8) - int(source["sample_count"] * .6),
            "evaluation_rows": source["sample_count"] - int(source["sample_count"] * .8),
            "split_policy": f"Seeded {fraction:.1%} Bernoulli development sample; features use full chronological source history with same-timestamp rows withheld; sampled rows then split 60/20/20 by timestamp.",
            "feature_names": list(FEATURE_NAMES),
            "feature_policy": "No raw account IDs, bank IDs, or labels in features. Per-account prior counts, amounts, and elapsed time use only earlier timestamps from the full source file.",
            "models": "Class-weighted logistic regression; local models use 24 full-batch gradient epochs; flat-vector weighted FedAvg uses 12 rounds x 2 local steps.",
            "protect_update": "identity; updates are not clipped, noised, masked, or securely aggregated.",
            "threshold_policy": "Each model threshold selected on its validation data at no more than 1% validation FPR; test labels only used for final evaluation.",
            "partition_counts": partition_counts, "results": results,
            "evaluation_timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    return report

def write_report(report, json_path: Path, js_path: Path):
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text("window.VAULTAI_HISMALL = " + json.dumps(report, separators=(",", ":")) + ";\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Run a bounded-memory HI-Small benchmark analysis")
    parser.add_argument("--data", type=Path, required=True, help="path to HI-Small_Trans.csv")
    parser.add_argument("--patterns", type=Path, required=True, help="path to HI-Small_Patterns.txt")
    parser.add_argument("--fraction", type=float, default=SAMPLE_FRACTION, help="seeded Bernoulli sample fraction (default 0.01)")
    parser.add_argument("--json", type=Path, default=Path("data/hi-small-results.json"))
    parser.add_argument("--javascript", type=Path, default=Path("data/hi-small-data.js"))
    args = parser.parse_args()
    if not 0 < args.fraction <= 1:
        parser.error("--fraction must be > 0 and <= 1")
    report = run(args.data, args.patterns, args.fraction)
    write_report(report, args.json, args.javascript)
    print(f"Source rows: {report['source_rows']:,}; labeled positives: {report['source_positive_rows']:,} ({report['source_laundering_rate']:.4%})")
    print(f"Model sample: {report['sample_rows']:,} rows ({report['sample_fraction']:.3%}); split train/validation/test: {report['train_rows']:,}/{report['validation_rows']:,}/{report['evaluation_rows']:,}")
    for result in report["results"]:
        print(f"{result['name']}: recall={result['recall']:.4f}, precision={result['precision']:.4f}, PR-AUC={result['prauc']:.4f}, test FPR={result['fpr']:.4f}, threshold={result['threshold']:.6f}, test rows={result['n']:,}, positives={result['pos']:,}")
    print(f"Report: {args.json}")


if __name__ == "__main__":
    main()

