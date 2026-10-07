#!/usr/bin/env python3
"""YOLO localization of small cross-tenor curve kinks vs numeric controls."""
from __future__ import annotations

import argparse
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
N_TENORS = 32
TENORS = np.geomspace(0.25, 30.0, N_TENORS)
IMAGE_SIZE = 640
TARGET_FPR = 0.02
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
YOLO_DEVICE = 0 if DEVICE.type == "cuda" else "cpu"
AMPLITUDES_BP = (0.5, 1.0, 2.0, 3.0, 4.0)
TRAIN_AMPLITUDE_BP = (0.5, 4.0)


def curve_pair(seed: int, domain: str = "train") -> tuple[np.ndarray, np.ndarray]:
    """Smooth parametric curve pair with >98% shared-factor correlation."""
    rng = np.random.default_rng(seed)
    x = np.log(TENORS)
    b0 = rng.uniform(120, 420)
    b1 = rng.uniform(-55, 55)
    b2 = rng.uniform(-22, 22)
    b3 = rng.uniform(-8, 8)
    shared = b0 + b1 * (1 - np.exp(-TENORS / 4)) / (TENORS / 4)
    shared += b2 * np.exp(-((x - rng.uniform(-0.2, 1.6)) / rng.uniform(0.6, 1.6)) ** 2)
    shared += b3 * x / max(abs(x))
    noise = 0.08 if domain == "train" else 0.12
    common_move = rng.normal(0, 0.8 if domain == "train" else 1.2)
    common_slope = rng.normal(0, 0.25 if domain == "train" else 0.4) * x
    base = shared + common_move + common_slope
    ref = base + rng.normal(0, noise, N_TENORS)
    primary = base + rng.normal(0, noise, N_TENORS)
    return primary.astype(np.float32), ref.astype(np.float32)


def inject_spike(primary: np.ndarray, ref: np.ndarray, amp_bp: float,
                 rng: np.random.Generator, index: int | None = None):
    x = primary.copy()
    index = int(index if index is not None else rng.integers(3, N_TENORS - 3))
    sign = float(rng.choice([-1, 1]))
    width = int(rng.choice([1, 1, 2]))
    for j in range(max(0, index - width + 1), index + 1):
        weight = 1.0 if j == index else 0.55
        x[j] += sign * amp_bp * weight
    return x, (index, index)


def render(primary: np.ndarray, ref: np.ndarray, path: Path,
           event: tuple[int, int] | None = None) -> None:
    image = Image.new("RGB", (IMAGE_SIZE, IMAGE_SIZE), "white")
    draw = ImageDraw.Draw(image)
    left, right, top, bottom = 54, IMAGE_SIZE - 18, 18, IMAGE_SIZE - 48
    draw.line((left, top, left, bottom, right, bottom), fill=(80, 80, 80), width=2)
    # Fixed bp scale preserves the same minimum-spike pixel size in every image.
    center = (top + bottom) / 2

    residual = primary - ref

    def points(values):
        return [(round(left + i * (right - left) / (N_TENORS - 1)),
                 round(center - float(np.clip(values[i], -16, 16)) * (bottom - top) / 32))
                for i in range(N_TENORS)]

    zero = [(left, round(center)), (right, round(center))]
    draw.line(zero, fill=(195, 76, 61), width=3)
    draw.line(points(residual), fill=(28, 94, 132), width=4)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=True)


def write_item(root: Path, split: str, idx: int, primary: np.ndarray,
               ref: np.ndarray, event: tuple[int, int] | None):
    image_path = root / "images" / split / f"{idx:06d}.png"
    label_path = root / "labels" / split / f"{idx:06d}.txt"
    label_path.parent.mkdir(parents=True, exist_ok=True)
    render(primary, ref, image_path, event)
    if event is None:
        label_path.write_text("", encoding="ascii")
        return
    lo, hi = event
    px = 54 + (lo + hi) / 2 * (IMAGE_SIZE - 72) / (N_TENORS - 1)
    residual = primary - ref
    py = (IMAGE_SIZE - 48 + 18) / 2 - float(np.clip(residual[lo], -16, 16)) * (IMAGE_SIZE - 66) / 32
    box_w, box_h = 32, 30
    label_path.write_text(
        f"0 {px / IMAGE_SIZE:.6f} {py / IMAGE_SIZE:.6f} "
        f"{box_w / IMAGE_SIZE:.6f} {box_h / IMAGE_SIZE:.6f}\n", encoding="ascii")


class CurveCNN1D(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv1d(2, 32, 5, padding=2), nn.GELU(),
            nn.Conv1d(32, 48, 5, padding=2), nn.GELU(),
            nn.Conv1d(48, 32, 3, padding=1), nn.GELU(),
            nn.Conv1d(32, 1, 1),
        )

    def forward(self, x):
        return self.net(x).squeeze(1)


def fit_cnn(x: np.ndarray, y: np.ndarray, seed: int, epochs: int):
    torch.manual_seed(seed)
    model = CurveCNN1D().to(DEVICE)
    loader = DataLoader(TensorDataset(torch.from_numpy(x), torch.from_numpy(y)),
                        batch_size=128, shuffle=True)
    optimizer = torch.optim.AdamW(model.parameters(), lr=8e-4, weight_decay=1e-4)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([12.0], device=DEVICE))
    for _ in range(epochs):
        model.train()
        for xb, yb in loader:
            xb, yb = xb.to(DEVICE), yb.to(DEVICE)
            optimizer.zero_grad(set_to_none=True)
            loss = loss_fn(model(xb), yb)
            loss.backward()
            optimizer.step()
    model.eval()
    return model


def numeric_features(primary: np.ndarray, ref: np.ndarray):
    # Compare the highly correlated curve pair in basis points; the second
    # channel captures local tenor curvature in the cross-curve residual.
    residual = primary - ref
    curvature = np.gradient(np.gradient(residual, axis=1), axis=1)
    return np.stack([residual, curvature], axis=1).astype(np.float32)


def cheap_shape_score(primary: np.ndarray, ref: np.ndarray):
    residual = np.atleast_2d(primary - ref)
    padded = np.pad(residual, ((0, 0), (1, 1)), mode="edge")
    smooth = 0.25 * padded[:, :-2] + 0.5 * padded[:, 1:-1] + 0.25 * padded[:, 2:]
    return np.abs(residual - smooth)


def paired_score(primary: np.ndarray, ref: np.ndarray):
    return np.abs(primary - ref)


def threshold(scores: np.ndarray):
    allowed = int(math.floor(TARGET_FPR * len(scores)))
    return float(np.sort(scores)[max(0, len(scores) - allowed - 1)])


def fit_yolo(data_root: Path, output: Path, epochs: int, seed: int):
    model = YOLO("yolo11n.pt")
    model.train(data=str(data_root / "dataset.yaml"), epochs=epochs,
                imgsz=IMAGE_SIZE, batch=16, workers=0, device=YOLO_DEVICE,
                project=str(output / "yolo_runs"), name=f"curve_spikes_{seed}",
                pretrained=True, patience=5, seed=seed, deterministic=True,
                mosaic=0.0, mixup=0.0, fliplr=0.0, flipud=0.0,
                degrees=0.0, translate=0.0, scale=0.0,
                hsv_h=0.0, hsv_s=0.0, hsv_v=0.0, plots=False, verbose=False)
    return Path(model.trainer.best).resolve()


def yolo_scores(model: YOLO, pairs: list[tuple[np.ndarray, np.ndarray]], root: Path,
                family: str):
    paths = []
    for i, (p, r) in enumerate(pairs):
        path = root / family / f"{i:06d}.png"
        render(p, r, path)
        paths.append(path)
    results = []
    for start in range(0, len(paths), 32):
        preds = model.predict([str(x) for x in paths[start:start + 32]],
                              imgsz=IMAGE_SIZE, conf=0.001, verbose=False)
        for result in preds:
            if result.boxes is None or not len(result.boxes):
                results.append((0.0, None))
            else:
                k = int(result.boxes.conf.argmax())
                x = float(result.boxes.xywhn[k, 0]) * (N_TENORS - 1)
                results.append((float(result.boxes.conf[k]), int(round(x))))
    return results


def run(out: Path, work: Path, seed: int, train_n: int, val_n: int,
        test_n: int, epochs: int, yolo_epochs: int):
    print(f"device={DEVICE}; yolo_device={YOLO_DEVICE}")
    rng = np.random.default_rng(seed)
    clean_train = [curve_pair(seed + i, "train") for i in range(train_n)]
    val_pairs = [curve_pair(seed + 100_000 + i, "ood") for i in range(val_n)]
    test_pairs = [curve_pair(seed + 200_000 + i, "ood") for i in range(test_n)]
    x_train, y_train = [], []
    for i, (p, r) in enumerate(clean_train):
        x_train.append((p, r)); y_train.append(None)
        if i % 2 == 0:
            amp = float(rng.uniform(*TRAIN_AMPLITUDE_BP))
            altered, event = inject_spike(p, r, amp, rng)
            x_train.append((altered, r)); y_train.append(event)
    features = numeric_features(np.array([p for p, _ in x_train]), np.array([r for _, r in x_train]))
    labels = np.zeros((len(x_train), N_TENORS), dtype=np.float32)
    for i, event in enumerate(y_train):
        if event is not None:
            labels[i, max(0, event[0] - 1):min(N_TENORS, event[1] + 2)] = 1
    cnn = fit_cnn(features, labels, seed, epochs)

    data_root = work / "curve_yolo"
    for i, (p, r) in enumerate(x_train):
        write_item(data_root, "train", i, p, r, y_train[i])
    val_rng = np.random.default_rng(seed + 1)
    val_for_yolo = []
    for i, (p, r) in enumerate(val_pairs):
        if i % 2:
            p, event = inject_spike(p, r, float(val_rng.uniform(*TRAIN_AMPLITUDE_BP)), val_rng)
        else:
            event = None
        val_for_yolo.append((p, r, event))
        write_item(data_root, "val", i, p, r, event)
    (data_root / "dataset.yaml").write_text(
        f"path: {data_root.resolve()}\ntrain: images/train\nval: images/val\nnames:\n  0: tenor_spike\n",
        encoding="utf-8")
    best = fit_yolo(data_root, out, yolo_epochs, seed)
    model = YOLO(str(best))

    clean_val_features = numeric_features(np.array([p for p, _ in val_pairs]), np.array([r for _, r in val_pairs]))
    with torch.no_grad():
        val_cnn = torch.sigmoid(cnn(torch.from_numpy(clean_val_features).to(DEVICE))).cpu().numpy()
    val_pair_score = np.array([paired_score(p[None], r[None]).max() for p, r in val_pairs])
    val_shape_score = np.array([cheap_shape_score(p[None], r[None]).max() for p, r in val_pairs])
    val_yolo = yolo_scores(model, val_pairs, work / "eval", "validation_clean")
    thresholds = {"cnn1d": threshold(val_cnn.max(axis=1)),
                  "paired_residual": threshold(val_pair_score),
                  "local_shape_residual": threshold(val_shape_score),
                  "yolo": threshold(np.array([c for c, _ in val_yolo]))}

    clean_yolo = yolo_scores(model, test_pairs, work / "eval", "test_clean")
    test_features = numeric_features(np.array([p for p, _ in test_pairs]), np.array([r for _, r in test_pairs]))
    with torch.no_grad():
        clean_cnn = torch.sigmoid(cnn(torch.from_numpy(test_features).to(DEVICE))).cpu().numpy()
    clean_pair_score = np.array([paired_score(p[None], r[None]).max() for p, r in test_pairs])
    clean_shape_score = np.array([cheap_shape_score(p[None], r[None]).max() for p, r in test_pairs])
    clean_fpr = {"cnn1d": float(np.mean(clean_cnn.max(axis=1) > thresholds["cnn1d"])),
                 "paired_residual": float(np.mean(clean_pair_score > thresholds["paired_residual"])),
                 "local_shape_residual": float(np.mean(clean_shape_score > thresholds["local_shape_residual"])),
                 "yolo": float(np.mean([c > thresholds["yolo"] for c, _ in clean_yolo]))}

    recall = {}
    test_rng = np.random.default_rng(seed + 2)
    for amp in AMPLITUDES_BP:
        pairs, events = [], []
        for p, r in test_pairs:
            altered, event = inject_spike(p, r, amp, test_rng)
            pairs.append((altered, r)); events.append(event)
        feat = numeric_features(np.array([p for p, _ in pairs]), np.array([r for _, r in pairs]))
        with torch.no_grad():
            cnn_scores = torch.sigmoid(cnn(torch.from_numpy(feat).to(DEVICE))).cpu().numpy()
        pair_scores = np.array([paired_score(p[None], r[None])[0] for p, r in pairs])
        shape_scores = np.array([cheap_shape_score(p[None], r[None])[0] for p, r in pairs])
        visual = yolo_scores(model, pairs, work / "eval", f"test_amp_{amp:g}bp")
        hits = {k: [] for k in thresholds}
        for i, (lo, hi) in enumerate(events):
            region = set(range(max(0, lo - 1), min(N_TENORS, hi + 2)))
            hits["cnn1d"].append(cnn_scores[i].max() > thresholds["cnn1d"] and int(cnn_scores[i].argmax()) in region)
            hits["paired_residual"].append(pair_scores[i].max() > thresholds["paired_residual"] and int(pair_scores[i].argmax()) in region)
            hits["local_shape_residual"].append(shape_scores[i].max() > thresholds["local_shape_residual"] and int(shape_scores[i].argmax()) in region)
            conf, loc = visual[i]
            hits["yolo"].append(conf > thresholds["yolo"] and loc is not None and loc in region)
        recall[str(amp)] = {k: float(np.mean(v)) for k, v in hits.items()}

    out.mkdir(parents=True, exist_ok=True)
    model_dir = out / "models"; model_dir.mkdir(exist_ok=True)
    weights = model_dir / "yolo11n_curve_tenor_spikes.pt"
    shutil.copy2(best, weights)
    torch.save(cnn.state_dict(), model_dir / "cnn1d_curve_tenor_spikes.pt")
    report = {
        "protocol": {"seed": seed, "tenors_years": TENORS.tolist(), "train": train_n,
                     "validation_clean": val_n, "test_clean": test_n,
                     "target_validation_fpr": TARGET_FPR, "yolo_epochs": yolo_epochs,
                     "cnn_epochs": epochs, "amplitudes_bp": list(AMPLITUDES_BP),
                     "training_amplitude_range_bp": list(TRAIN_AMPLITUDE_BP),
                     "curve_generator": "smooth parametric curve pair with shared factors and independent sub-bp quote noise",
                     "test_domain": "wider shared-factor and noise ranges than train",
                     "limitations": ["all generated curves and defect labels are synthetic", "single seed pilot"]},
        "thresholds": thresholds, "clean_test_fpr": clean_fpr,
        "localized_event_recall_by_amplitude_bp": recall,
        "weights": str(weights), "interpretation": "Pilot only; no operational DQ claim.",
    }
    (out / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "results/reports/dq_yolo_curve_tenor_spikes")
    parser.add_argument("--work", type=Path, default=Path("/tmp/dq_yolo_curve_tenor_spikes"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train", type=int, default=1500)
    parser.add_argument("--val", type=int, default=300)
    parser.add_argument("--test", type=int, default=500)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--yolo-epochs", type=int, default=20)
    a = parser.parse_args()
    print(json.dumps(run(a.out, a.work, a.seed, a.train, a.val, a.test, a.epochs, a.yolo_epochs), indent=2))


if __name__ == "__main__":
    main()
