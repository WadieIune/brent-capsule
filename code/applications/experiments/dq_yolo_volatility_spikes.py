#!/usr/bin/env python3
"""Paired YOLO and temporal CNN test for spikes in mean-reverting log-volatility.

The same synthetic windows feed YOLO as fixed-scale line-chart images and a
1D CNN as numeric arrays. Thresholds are calibrated on clean validation data.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw
from torch import nn
from torch.utils.data import DataLoader, TensorDataset
from ultralytics import YOLO


ROOT = Path(__file__).resolve().parents[3]
WINDOW = 128
IMG_SIZE = 320
SPIKE_SIGMAS = (1, 2, 3, 4, 5, 8)
TARGET_FPR = 0.02


def sample_window(seed: int, spike_sigma: float | None = None):
    rng = np.random.default_rng(seed)
    phi = float(rng.uniform(0.84, 0.96))
    innovation = float(rng.uniform(0.055, 0.085))
    x = np.empty(WINDOW, dtype=np.float32)
    x[0] = rng.normal(0, innovation / math.sqrt(1 - phi * phi))
    for t in range(1, WINDOW):
        x[t] = phi * x[t - 1] + rng.normal(0, innovation)
    # Fixed scale is shared across train/validation/test; no per-window rescaling.
    x /= 0.20
    position = None
    if spike_sigma is not None:
        position = int(rng.integers(16, WINDOW - 16))
        x[position] += float(spike_sigma)
    return x, position


def render_series(values: np.ndarray, path: Path):
    image = Image.new("RGB", (IMG_SIZE, IMG_SIZE), "white")
    draw = ImageDraw.Draw(image)
    left, right, top, bottom = 12, IMG_SIZE - 12, 12, IMG_SIZE - 12
    points = []
    for i, value in enumerate(values):
        px = left + i * (right - left) / (len(values) - 1)
        py = bottom - (float(np.clip(value, -8, 8)) + 8) * (bottom - top) / 16
        points.append((round(px), round(py)))
    draw.line(points, fill=(24, 74, 105), width=2)
    image.save(path, format="PNG", optimize=True)


def write_yolo_item(root: Path, split: str, item: int, values: np.ndarray,
                    position: int | None):
    image_dir = root / "images" / split
    label_dir = root / "labels" / split
    image_dir.mkdir(parents=True, exist_ok=True)
    label_dir.mkdir(parents=True, exist_ok=True)
    name = f"{item:06d}"
    render_series(values, image_dir / f"{name}.png")
    label_path = label_dir / f"{name}.txt"
    if position is None:
        label_path.write_text("", encoding="ascii")
        return
    x = 12 + position * (IMG_SIZE - 24) / (WINDOW - 1)
    y = IMG_SIZE - 12 - (float(np.clip(values[position], -8, 8)) + 8) * (IMG_SIZE - 24) / 16
    # Box covers the spike vertex and its immediate line context.
    width, height = 18.0, 22.0
    label_path.write_text(
        f"0 {x / IMG_SIZE:.6f} {y / IMG_SIZE:.6f} "
        f"{width / IMG_SIZE:.6f} {height / IMG_SIZE:.6f}\n", encoding="ascii")


def build_dataset(root: Path, n_train: int, n_val: int, n_test: int, seed: int):
    for split, count, offset in (("train", n_train, 10_000),
                                 ("val", n_val, 30_000),
                                 ("test", n_test, 50_000)):
        for i in range(count):
            s = seed + offset + i
            positive = split != "test" and (i % 2) == 1
            amp = float(np.random.default_rng(s + 3).uniform(2.0, 6.0)) if positive else None
            x, pos = sample_window(s, amp)
            write_yolo_item(root, split, i, x, pos)
    yaml = root / "dataset.yaml"
    yaml.write_text(
        f"path: {root.resolve()}\ntrain: images/train\nval: images/val\n"
        "names:\n  0: volatility_spike\n", encoding="utf-8")


class SpikeCNN1D(nn.Module):
    def __init__(self):
        super().__init__()
        self.body = nn.Sequential(
            nn.Conv1d(1, 32, 7, padding=3), nn.GELU(),
            nn.Conv1d(32, 48, 5, padding=2), nn.GELU(),
            nn.Conv1d(48, 48, 3, padding=1), nn.GELU(),
        )
        self.head = nn.Conv1d(48, 1, 1)

    def forward(self, x):
        return self.head(self.body(x[:, None, :])).squeeze(1)


def causal_3sigma_score(values: np.ndarray, lookback: int = 32):
    result = np.zeros(len(values), dtype=np.float32)
    delta = np.diff(values, prepend=values[0])
    for i in range(lookback, len(values)):
        history = delta[i - lookback:i]
        sd = max(float(history.std(ddof=1)), 1e-6)
        result[i] = abs((delta[i] - float(history.mean())) / sd)
    return result


def make_cnn_data(count: int, seed: int, amplitudes: tuple[float, ...] | None = None):
    xs, ys, positions, amps = [], [], [], []
    for i in range(count):
        s = seed + i
        amp = None
        if amplitudes is None:
            if i % 2:
                amp = float(np.random.default_rng(s + 3).uniform(2.0, 6.0))
        else:
            amp = amplitudes[i % len(amplitudes)]
        x, pos = sample_window(s, amp)
        y = np.zeros(WINDOW, dtype=np.float32)
        if pos is not None:
            y[pos] = 1.0
        xs.append(x); ys.append(y); positions.append(pos); amps.append(amp)
    return (np.asarray(xs), np.asarray(ys), np.asarray(positions, dtype=object),
            np.asarray(amps, dtype=object))


def make_clean_windows(count: int, seed: int):
    return np.asarray([sample_window(seed + i)[0] for i in range(count)], dtype=np.float32)


def fit_cnn(x: np.ndarray, y: np.ndarray, seed: int, epochs: int):
    torch.manual_seed(seed)
    model = SpikeCNN1D()
    loader = DataLoader(TensorDataset(torch.from_numpy(x), torch.from_numpy(y)),
                        batch_size=64, shuffle=True)
    optimizer = torch.optim.AdamW(model.parameters(), lr=8e-4, weight_decay=1e-4)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([32.0]))
    for _ in range(epochs):
        model.train()
        for xb, yb in loader:
            optimizer.zero_grad(set_to_none=True)
            loss = loss_fn(model(xb), yb)
            loss.backward()
            optimizer.step()
    model.eval()
    return model


def cnn_scores(model: SpikeCNN1D, x: np.ndarray):
    with torch.no_grad():
        return torch.sigmoid(model(torch.from_numpy(x))).numpy()


def threshold_at_fpr(scores: np.ndarray, target: float):
    allowed = int(math.floor(target * len(scores)))
    return float(np.sort(scores)[max(0, len(scores) - allowed - 1)])


def yolo_scores(model: YOLO, paths: list[Path]):
    output = []
    batch_size = 32
    for start in range(0, len(paths), batch_size):
        results = model.predict(source=[str(p) for p in paths[start:start + batch_size]],
                                imgsz=IMG_SIZE, conf=0.001, verbose=False,
                                augment=False, stream=False)
        for result in results:
            boxes = result.boxes
            if boxes is None or len(boxes) == 0:
                output.append((0.0, None))
                continue
            idx = int(boxes.conf.argmax())
            output.append((float(boxes.conf[idx]), boxes.xywhn[idx].cpu().numpy()))
    return output


def evaluate(root: Path, out: Path, seed: int, epochs: int, n_train: int,
             n_val: int, n_test: int, weights: Path | None = None):
    build_dataset(root / "yolo_dataset", n_train, n_val, n_test, seed)
    data_root = root / "yolo_dataset"
    train_x, train_y, _, _ = make_cnn_data(n_train, seed + 10_000)
    model_1d = fit_cnn(train_x, train_y, seed, epochs)

    if weights is None:
        detector = YOLO("yolo11n.pt")
        detector.train(data=str(data_root / "dataset.yaml"), epochs=epochs,
                       imgsz=IMG_SIZE, batch=16, workers=0, device="cpu",
                       project=str((root / "yolo_runs").resolve()), name="volatility_spike",
                       pretrained=True, patience=10, seed=seed, deterministic=True,
                       mosaic=0.0, mixup=0.0, fliplr=0.0, flipud=0.0,
                       degrees=0.0, translate=0.0, scale=0.0, hsv_h=0.0,
                       hsv_s=0.0, hsv_v=0.0, plots=False, save=True, verbose=False)
        best = root / "yolo_runs" / "volatility_spike" / "weights" / "best.pt"
    else:
        best = weights.resolve()
    detector = YOLO(str(best))
    metrics_path = best.parents[1] / "results.csv"
    yolo_epochs_completed = 0
    if metrics_path.exists():
        with metrics_path.open(encoding="utf-8-sig", newline="") as handle:
            yolo_epochs_completed = sum(1 for _ in csv.DictReader(handle))
    model_dir = out / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    saved_yolo = model_dir / "yolo11n_volatility_spikes_best.pt"
    if best.resolve() != saved_yolo.resolve():
        shutil.copy2(best, saved_yolo)
    torch.save(model_1d.state_dict(), model_dir / "cnn1d_volatility_spikes.pt")

    val_x, _, _, _ = make_cnn_data(n_val, seed + 30_000)
    val_1d = cnn_scores(model_1d, val_x).max(axis=1)
    val_1d_clean = val_1d[np.arange(n_val) % 2 == 0]
    cnn_threshold = threshold_at_fpr(val_1d_clean, TARGET_FPR)
    val_clean_x = val_x[np.arange(n_val) % 2 == 0]
    val_3sigma = np.asarray([causal_3sigma_score(x).max() for x in val_clean_x])
    sigma_threshold = threshold_at_fpr(val_3sigma, TARGET_FPR)
    val_paths = [data_root / "images" / "val" / f"{i:06d}.png" for i in range(n_val)]
    val_yolo = yolo_scores(detector, val_paths)
    yolo_clean_scores = np.asarray([s for i, (s, _) in enumerate(val_yolo) if i % 2 == 0])
    yolo_threshold = threshold_at_fpr(yolo_clean_scores, TARGET_FPR)
    validation_fpr = {
        "cnn1d": float(np.mean(val_1d_clean > cnn_threshold)),
        "yolo": float(np.mean(yolo_clean_scores > yolo_threshold)),
        "3sigma_window_max_calibrated": float(np.mean(val_3sigma > sigma_threshold)),
    }

    # Paired clean and corrupted test paths; independent base trajectory per event.
    test_clean_x = make_clean_windows(n_test, seed + 50_000)
    test_clean_paths = [data_root / "images" / "test" / f"{i:06d}.png" for i in range(n_test)]
    clean_cnn_max = cnn_scores(model_1d, test_clean_x).max(axis=1)
    clean_yolo = yolo_scores(detector, test_clean_paths)
    clean_3sigma = np.asarray([causal_3sigma_score(x).max() for x in test_clean_x])
    clean_fpr = {
        "cnn1d": float(np.mean(clean_cnn_max > cnn_threshold)),
        "yolo": float(np.mean([s > yolo_threshold for s, _ in clean_yolo])),
        "3sigma_fixed": float(np.mean(clean_3sigma > 3.0)),
        "3sigma_window_max_calibrated": float(np.mean(clean_3sigma > sigma_threshold)),
    }

    per_amplitude = {}
    for amplitude in SPIKE_SIGMAS:
        xs, true_pos, paths = [], [], []
        for i in range(n_test):
            x, pos = sample_window(seed + 70_000 + i, float(amplitude))
            xs.append(x); true_pos.append(pos)
            item = n_test + (amplitude * n_test) + i
            # Test injected images are stored in a parallel directory to keep
            # the training split untouched and the paired data easy to audit.
            img_dir = root / "injected_test" / str(amplitude)
            img_dir.mkdir(parents=True, exist_ok=True)
            p = img_dir / f"{i:06d}.png"
            render_series(x, p)
            paths.append(p)
        xx = np.asarray(xs, dtype=np.float32)
        scores_1d = cnn_scores(model_1d, xx)
        score_yolo = yolo_scores(detector, paths)
        score_3 = np.asarray([causal_3sigma_score(x) for x in xx])
        rec_1d, rec_yolo, rec_3, rec_3_calibrated = [], [], [], []
        for i, position in enumerate(true_pos):
            time_1d = int(scores_1d[i].argmax())
            rec_1d.append(bool(scores_1d[i].max() > cnn_threshold and abs(time_1d - position) <= 3))
            conf, box = score_yolo[i]
            time_yolo = None if box is None else int(round(float(box[0]) * (WINDOW - 1)))
            rec_yolo.append(bool(conf > yolo_threshold and time_yolo is not None
                                 and abs(time_yolo - position) <= 3))
            lo, hi = max(0, position - 3), min(WINDOW, position + 4)
            rec_3.append(bool(np.max(score_3[i, lo:hi]) > 3.0))
            rec_3_calibrated.append(bool(np.max(score_3[i, lo:hi]) > sigma_threshold))
        per_amplitude[str(amplitude)] = {
            "cnn1d_event_recall_located": float(np.mean(rec_1d)),
            "yolo_event_recall_located": float(np.mean(rec_yolo)),
            "3sigma_fixed_event_recall": float(np.mean(rec_3)),
            "3sigma_event_recall_located_fpr_calibrated": float(np.mean(rec_3_calibrated)),
        }

    report = {
        "protocol": {
            "task": "localize isolated spikes in mean-reverting log-volatility",
            "window": WINDOW, "train_windows": n_train, "validation_windows": n_val,
            "test_windows_per_amplitude": n_test, "cnn1d_epochs": epochs,
            "yolo_epochs_completed": yolo_epochs_completed,
            "seed": seed, "target_clean_fpr": TARGET_FPR,
            "localization_tolerance_sessions": 3,
            "injections_train_sigma": [2, 6], "test_amplitudes_sigma": list(SPIKE_SIGMAS),
            "yolo_pretrained_weights": "yolo11n.pt (Ultralytics COCO initialization; fine-tuned here)",
            "augmentation": "disabled to preserve time/value coordinates",
            "limitations": ["synthetic mean-reverting series; not observed market defect labels",
                            "YOLO sees rendered fixed-scale images; CNN1D sees numeric windows",
                            "3sigma_fixed is not FPR-matched; window-max baselines are calibrated to target 2%"],
        },
        "thresholds": {"cnn1d": cnn_threshold, "yolo": yolo_threshold,
                       "3sigma_fixed": 3.0,
                       "3sigma_window_max_calibrated_to_target_fpr": sigma_threshold},
        "clean_test_fpr": clean_fpr,
        "recall_by_spike_sigma": per_amplitude,
        "validation_fpr": validation_fpr,
        "artifacts": {"yolo_best": str(saved_yolo),
                      "cnn1d_state": str(model_dir / "cnn1d_volatility_spikes.pt"),
                      "dataset": str(data_root)},
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "results/reports/dq_yolo_volatility")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--train", type=int, default=1200)
    parser.add_argument("--val", type=int, default=400)
    parser.add_argument("--test", type=int, default=250)
    parser.add_argument("--weights", type=Path,
                        help="Use an already trained YOLO checkpoint and skip YOLO training")
    args = parser.parse_args()
    report = evaluate(args.out, args.out, args.seed, args.epochs,
                      args.train, args.val, args.test, args.weights)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
