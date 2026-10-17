"""Reproducible, dependency-free synthetic federated AML demonstration.

Run: python experiment.py
Writes data/experiment-results.json. The experiment is educational only: labels
are synthetic rule-generated targets, and no banking records or privacy guarantee
are represented.
"""
from __future__ import annotations
import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path

SEED = 20261014
BANKS = 3
RECORDS_PER_BANK = 6000
FEATURES = ("velocity", "amount_pattern", "fanout", "cycle_hint")
ROUNDS = 12
LOCAL_STEPS = 2
LEARNING_RATE = 0.13
POSITIVE_CLASS_WEIGHT = 16.0


def sigmoid(z: float) -> float:
    z = max(-30.0, min(30.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def make_data():
    rng = random.Random(SEED)
    partitions = [[] for _ in range(BANKS)]
    for bank in range(BANKS):
        for _ in range(RECORDS_PER_BANK):
            # Bounded, unit-scale synthetic behavior features with mild bank shift.
            x = [rng.random(), rng.random(), rng.random(), rng.random()]
            shift = (bank - 1) * 0.035
            x[0] = min(1.0, max(0.0, x[0] + shift))
            score = 2.5*x[0] + 1.8*x[1] + 2.2*x[2] + 2.0*x[3]
            # A fixed synthetic rule defines labels; it is not an AML ground truth.
            y = int(score > 6.35 and x[0] > .48 and (x[2] > .42 or x[3] > .68))
            partitions[bank].append((x, y))
    # Split each bank independently before model fitting. Test rows never enter updates.
    train, test = [], []
    split_rng = random.Random(SEED + 1)
    for part in partitions:
        order = list(part)
        split_rng.shuffle(order)
        cut = int(len(order) * .75)
        train.append(order[:cut])
        test.extend(order[cut:])
    return train, test


def gradient_step(weights, rows):
    grad = [0.0] * (len(FEATURES) + 1)
    for x, y in rows:
        error = (sigmoid(weights[0] + sum(w*v for w, v in zip(weights[1:], x))) - y)
        if y:
            error *= POSITIVE_CLASS_WEIGHT
        grad[0] += error
        for j, value in enumerate(x, 1):
            grad[j] += error * value
    n = max(1, len(rows))
    return [w - LEARNING_RATE * g/n for w, g in zip(weights, grad)]


def train_local(rows, epochs=28, initial=None):
    weights = list(initial) if initial is not None else [0.0] * (len(FEATURES) + 1)
    for _ in range(epochs):
        weights = gradient_step(weights, rows)
    return weights


def predict(weights, x):
    return sigmoid(weights[0] + sum(w*v for w, v in zip(weights[1:], x)))


def evaluate(name, weights, rows):
    ranked, tp, fp, fn, tn = [], 0, 0, 0, 0
    for x, y in rows:
        p = predict(weights, x)
        ranked.append((p, y))
        pred = p >= .5
        if pred and y: tp += 1
        elif pred: fp += 1
        elif y: fn += 1
        else: tn += 1
    ranked.sort(reverse=True)
    positives = sum(y for _, y in ranked)
    seen_tp = seen = 0
    ap = 0.0
    if positives:
        for _, y in ranked:
            seen += 1
            if y:
                seen_tp += 1
                ap += (seen_tp / seen) / positives
    return {"name": name, "recall": tp/max(1,tp+fn), "precision": tp/max(1,tp+fp),
            "prauc": ap, "fpr": fp/max(1,fp+tn), "threshold": .5,
            "n": len(rows), "pos": positives, "tp": tp, "fp": fp,
            "fn": fn, "tn": tn}


def run_experiment():
    """Run the current reproducible synthetic demo and return its JSON report.

    This is not the absent HI-Small Stage 1–3 pipeline. Its labels are generated
    from a fixed rule and its existing evaluation threshold is 0.50.
    """
    train, test = make_data()
    local_weights = [train_local(part) for part in train]
    local_names = ["Bank A isolated", "Bank B isolated", "Bank C isolated"]
    results = [evaluate(n, w, test) for n, w in zip(local_names, local_weights)]
    shared = [0.0] * (len(FEATURES) + 1)
    n_total = sum(map(len, train))
    for _ in range(ROUNDS):
        updates = [train_local(part, epochs=LOCAL_STEPS, initial=shared) for part in train]
        shared = [sum(w[j]*len(part) for w, part in zip(updates, train))/n_total
                  for j in range(len(shared))]
    results.append(evaluate("VaultAI federated", shared, test))
    out = {"run_id": "FL-043", "label": "Federated logistic-regression demonstration",
           "seed": SEED, "synthetic": True, "label_definition":
           "Rule-generated target: weighted synthetic behavior features exceed a fixed threshold.",
           "feature_names": list(FEATURES), "train_rows": n_total,
           "evaluation_rows": len(test), "evaluation_protocol":
           "Per-bank 75/25 split before training; common combined held-out test set; threshold 0.50.",
           "models": "Logistic regression; batch gradient descent; federated weighted model-parameter averaging.",
           "rounds": ROUNDS, "local_steps_per_round": LOCAL_STEPS,
           "class_weight_positive": POSITIVE_CLASS_WEIGHT,
           "evaluation_timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "results": results}
    return out


def write_results(out):
    """Save the experiment report for the static dashboard data loader."""
    dest = Path(__file__).parent / "data" / "experiment-results.json"
    dest.parent.mkdir(exist_ok=True)
    serialized = json.dumps(out, indent=2) + "\n"
    dest.write_text(serialized, encoding="utf-8")
    (dest.parent / "experiment-data.js").write_text(
        "window.VAULTAI_EXPERIMENT = " + json.dumps(out, separators=(",", ":")) + ";\n",
        encoding="utf-8")
    return dest


def main():
    out = run_experiment()
    dest = write_results(out)
    f, best = out["results"][-1], max(out["results"][:3], key=lambda r:r["recall"])
    print(f"Wrote {dest}")
    print(f"Held-out rows: {out['evaluation_rows']}; positives: {f['pos']}")
    print(f"Federated recall {f['recall']:.3f}, precision {f['precision']:.3f}, "
          f"PR-AUC {f['prauc']:.3f}, FPR {f['fpr']:.3f}")
    print(f"Best isolated recall {best['recall']:.3f}; FPR {best['fpr']:.3f}")


if __name__ == "__main__":
    main()
