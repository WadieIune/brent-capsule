#!/usr/bin/env python3
"""Generative augmentation + YOLO/CNN/AE benchmark for volatility DQ.

Train uses synthetic mean-reverting volatility. Validation/test use an
independent heavy-tailed, switching-volatility generator. YOLO and a numeric
1D CNN are compared with and without VAE-generated training augmentation.
"""
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
LENGTH = 128
IMAGE_SIZE = 320
FAMILIES = ("spike", "stale_block", "level_shift")
AMPLITUDES = (1.0, 2.0, 4.0, 6.0)
TARGET_FPR = 0.02
TORCH_DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
YOLO_DEVICE = 0 if TORCH_DEVICE.type == "cuda" else "cpu"


def sample_clean(seed: int, domain: str = "train") -> np.ndarray:
    rng = np.random.default_rng(seed)
    if domain == "train":
        phi = rng.uniform(0.86, 0.95)
        sig_low, sig_high = rng.uniform(0.045, 0.065), rng.uniform(0.08, 0.12)
        df = None
    elif domain == "ood":
        phi = rng.uniform(0.80, 0.98)
        sig_low, sig_high = rng.uniform(0.04, 0.07), rng.uniform(0.11, 0.18)
        df = 5.0
    else:
        raise ValueError(domain)
    state = int(rng.integers(0, 2))
    x = np.zeros(LENGTH, dtype=np.float32)
    for t in range(1, LENGTH):
        if rng.random() < (0.018 if domain == "train" else 0.035):
            state = 1 - state
        sigma = sig_high if state else sig_low
        if df is None:
            eps = rng.normal()
        else:
            eps = rng.standard_t(df) / math.sqrt(df / (df - 2))
        x[t] = phi * x[t - 1] + sigma * eps
    return (x / 0.20).astype(np.float32)


def inject(values: np.ndarray, family: str, rng: np.random.Generator,
           amplitude: float | None = None):
    x = values.copy()
    amp = float(amplitude if amplitude is not None else rng.uniform(2.0, 6.0))
    start = int(rng.integers(16, LENGTH - 24))
    if family == "spike":
        x[start] += float(rng.choice([-1, 1])) * amp
        return x, (start, start)
    if family == "hump":
        width = int(rng.integers(4, 10))
        x[start:start + width] += np.hanning(width).astype(np.float32) * amp
        return x, (start, start + width - 1)
    if family == "stale_block":
        width = int(rng.integers(5, 13))
        x[start:start + width] = x[start - 1]
        return x, (start, start + width - 1)
    if family == "level_shift":
        x[start:] += float(rng.choice([-1, 1])) * amp
        return x, (start, LENGTH - 1)
    raise ValueError(family)


class ConvVAE(nn.Module):
    def __init__(self, latent_dim: int = 16):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Conv1d(1, 16, 5, stride=2, padding=2), nn.GELU(),
            nn.Conv1d(16, 32, 5, stride=2, padding=2), nn.GELU(),
            nn.Conv1d(32, 64, 5, stride=2, padding=2), nn.GELU(),
            nn.Flatten(),
        )
        self.mu = nn.Linear(64 * 16, latent_dim)
        self.logvar = nn.Linear(64 * 16, latent_dim)
        self.decode_in = nn.Linear(latent_dim, 64 * 16)
        self.decoder = nn.Sequential(
            nn.ConvTranspose1d(64, 32, 4, stride=2, padding=1), nn.GELU(),
            nn.ConvTranspose1d(32, 16, 4, stride=2, padding=1), nn.GELU(),
            nn.ConvTranspose1d(16, 1, 4, stride=2, padding=1),
        )

    def encode(self, x):
        h = self.encoder(x[:, None, :])
        return self.mu(h), self.logvar(h).clamp(-8, 8)

    def decode(self, z):
        return self.decoder(self.decode_in(z).view(-1, 64, 16)).squeeze(1)

    def forward(self, x):
        mu, logvar = self.encode(x)
        z = mu + torch.randn_like(mu) * torch.exp(0.5 * logvar)
        return self.decode(z), mu, logvar


def fit_vae(clean: np.ndarray, seed: int, epochs: int):
    torch.manual_seed(seed)
    model = ConvVAE().to(TORCH_DEVICE)
    loader = DataLoader(TensorDataset(torch.from_numpy(clean)), batch_size=64, shuffle=True)
    opt = torch.optim.AdamW(model.parameters(), lr=8e-4, weight_decay=1e-5)
    for _ in range(epochs):
        model.train()
        for (batch,) in loader:
            batch = batch.to(TORCH_DEVICE)
            opt.zero_grad(set_to_none=True)
            recon, mu, logvar = model(batch)
            mse = (recon - batch).square().mean()
            kl = -0.5 * (1 + logvar - mu.square() - logvar.exp()).mean()
            loss = mse + 0.01 * kl
            loss.backward()
            opt.step()
    model.eval()
    return model


def _device_of(model: nn.Module) -> torch.device:
    """Device donde vive el modelo, no el global.

    `fit_vae` mueve el modelo a `TORCH_DEVICE`, pero un modelo construido a mano
    —como en los tests— se queda en CPU. Alinear la entrada con el global en vez
    de con el modelo rompe en cuanto hay GPU disponible.
    """
    return next(model.parameters()).device


def vae_generate(model: ConvVAE, n: int, seed: int):
    generator = torch.Generator().manual_seed(seed)
    z = torch.randn(n, 16, generator=generator).to(_device_of(model))
    with torch.no_grad():
        return model.decode(z).cpu().numpy().astype(np.float32)


def vae_reconstruct(model: ConvVAE, x: torch.Tensor):
    with torch.no_grad():
        x = x.to(_device_of(model))
        mu, _ = model.encode(x)
        return model.decode(mu).cpu()


def autocorr(x: np.ndarray, lag: int):
    a, b = x[:, :-lag].ravel(), x[:, lag:].ravel()
    return float(np.corrcoef(a, b)[0, 1])


def generation_diagnostics(real: np.ndarray, generated: np.ndarray):
    return {
        "std_ratio_generated_to_reference": float(generated.std() / real.std()),
        "acf_lag1_generated": autocorr(generated, 1),
        "acf_lag1_reference": autocorr(real, 1),
        "acf_lag5_generated": autocorr(generated, 5),
        "acf_lag5_reference": autocorr(real, 5),
        "q01_generated": float(np.quantile(generated, 0.01)),
        "q01_reference": float(np.quantile(real, 0.01)),
        "q99_generated": float(np.quantile(generated, 0.99)),
        "q99_reference": float(np.quantile(real, 0.99)),
    }


def render(values: np.ndarray, path: Path):
    image = Image.new("RGB", (IMAGE_SIZE, IMAGE_SIZE), "white")
    draw = ImageDraw.Draw(image)
    margin = 12
    points = []
    for i, value in enumerate(values):
        px = margin + i * (IMAGE_SIZE - 2 * margin) / (LENGTH - 1)
        py = IMAGE_SIZE - margin - (float(np.clip(value, -8, 8)) + 8) * (IMAGE_SIZE - 2 * margin) / 16
        points.append((round(px), round(py)))
    draw.line(points, fill=(24, 74, 105), width=2)
    image.save(path, format="PNG", optimize=True)


def write_item(root: Path, split: str, index: int, values: np.ndarray,
               event: tuple[int, int] | None):
    images, labels = root / "images" / split, root / "labels" / split
    images.mkdir(parents=True, exist_ok=True); labels.mkdir(parents=True, exist_ok=True)
    stem = f"{index:06d}"
    render(values, images / f"{stem}.png")
    label = labels / f"{stem}.txt"
    if event is None:
        label.write_text("", encoding="ascii")
        return
    lo, hi = event
    x0 = 12 + lo * (IMAGE_SIZE - 24) / (LENGTH - 1)
    x1 = 12 + hi * (IMAGE_SIZE - 24) / (LENGTH - 1)
    start_y = IMAGE_SIZE - 12 - (float(np.clip(values[lo], -8, 8)) + 8) * (IMAGE_SIZE - 24) / 16
    end_y = IMAGE_SIZE - 12 - (float(np.clip(values[hi], -8, 8)) + 8) * (IMAGE_SIZE - 24) / 16
    xc, yc = (x0 + x1) / 2, (start_y + end_y) / 2
    width = max(18.0, x1 - x0 + 12.0)
    height = max(22.0, abs(end_y - start_y) + 22.0)
    width, height = min(width, IMAGE_SIZE - 24), min(height, IMAGE_SIZE - 24)
    label.write_text(f"0 {xc / IMAGE_SIZE:.6f} {yc / IMAGE_SIZE:.6f} "
                      f"{width / IMAGE_SIZE:.6f} {height / IMAGE_SIZE:.6f}\n", encoding="ascii")


class DenseCNN(nn.Module):
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


def fit_dense_cnn(x: np.ndarray, y: np.ndarray, seed: int, epochs: int):
    torch.manual_seed(seed)
    model = DenseCNN().to(TORCH_DEVICE)
    loader = DataLoader(TensorDataset(torch.from_numpy(x), torch.from_numpy(y)),
                        batch_size=64, shuffle=True)
    optimizer = torch.optim.AdamW(model.parameters(), lr=8e-4, weight_decay=1e-4)
    loss = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([20.0], device=TORCH_DEVICE))
    for _ in range(epochs):
        model.train()
        for xb, yb in loader:
            xb, yb = xb.to(TORCH_DEVICE), yb.to(TORCH_DEVICE)
            optimizer.zero_grad(set_to_none=True)
            value = loss(model(xb), yb)
            value.backward(); optimizer.step()
    model.eval()
    return model


def causal_score(x: np.ndarray, lookback: int = 32):
    delta = np.diff(x, prepend=x[0])
    score = np.zeros(len(x), dtype=np.float32)
    for t in range(lookback, len(x)):
        hist = delta[t - lookback:t]
        score[t] = abs((delta[t] - hist.mean()) / max(hist.std(ddof=1), 1e-6))
    return score


def threshold(scores: np.ndarray):
    allowed = int(math.floor(TARGET_FPR * len(scores)))
    return float(np.sort(scores)[max(0, len(scores) - allowed - 1)])


def yolo_detect(model: YOLO, paths: list[Path]):
    found = []
    for start in range(0, len(paths), 32):
        batch = model.predict(source=[str(p) for p in paths[start:start + 32]],
                              imgsz=IMAGE_SIZE, conf=0.001, verbose=False)
        for result in batch:
            boxes = result.boxes
            if boxes is None or not len(boxes):
                found.append((0.0, None))
            else:
                k = int(boxes.conf.argmax())
                found.append((float(boxes.conf[k]),
                              int(round(float(boxes.xywhn[k, 0]) * (LENGTH - 1)))))
    return found


def fit_detector(data_root: Path, model_name: str, project: Path, run_name: str,
                 epochs: int, seed: int):
    model = YOLO(model_name)
    model.train(data=str(data_root / "dataset.yaml"), epochs=epochs, imgsz=IMAGE_SIZE,
                batch=16, workers=0, device=YOLO_DEVICE, project=str(project.resolve()),
                name=run_name, pretrained=True, patience=5, seed=seed,
                deterministic=True, mosaic=0.0, mixup=0.0, fliplr=0.0,
                flipud=0.0, degrees=0.0, translate=0.0, scale=0.0,
                hsv_h=0.0, hsv_s=0.0, hsv_v=0.0, plots=False,
                save=True, verbose=False)
    return Path(model.trainer.best).resolve()


def prepare_train(clean: np.ndarray, generated: np.ndarray, family_seed: int,
                  use_vae: bool):
    n = len(clean)
    if use_vae:
        chosen = np.concatenate([clean[:n // 2], generated[:n - n // 2]])
    else:
        chosen = clean
    xs, ys = [], []
    rng = np.random.default_rng(family_seed)
    for i, base in enumerate(chosen):
        if i % 2 == 0:
            x, event = base, None
        else:
            family = "spike" if (i // 2) % 2 == 0 else "hump"
            x, event = inject(base, family, rng)
        y = np.zeros(LENGTH, dtype=np.float32)
        if event is not None:
            y[max(0, event[0] - 1):min(LENGTH, event[1] + 2)] = 1.0
        xs.append(x); ys.append(y)
    return np.asarray(xs, dtype=np.float32), np.asarray(ys, dtype=np.float32), chosen


def evaluate_model(model: YOLO, cnn: DenseCNN, vae: ConvVAE,
                   val_clean: np.ndarray, test_clean: np.ndarray,
                   events: dict[str, list[tuple[np.ndarray, tuple[int, int]]]],
                   image_root: Path, target_fpr: float = TARGET_FPR):
    val_cnn = torch.sigmoid(cnn(torch.from_numpy(val_clean).to(TORCH_DEVICE))).detach().cpu().numpy().max(axis=1)
    val_ae = []
    for batch in torch.from_numpy(val_clean).split(64):
        recon = vae_reconstruct(vae, batch)
        val_ae.extend((recon - batch).abs().numpy().max(axis=1))
    val_sigma = np.asarray([causal_score(x).max() for x in val_clean])
    val_paths = []
    for i, x in enumerate(val_clean):
        p = image_root / "validation" / f"{i:06d}.png"
        p.parent.mkdir(parents=True, exist_ok=True); render(x, p); val_paths.append(p)
    val_yolo = yolo_detect(model, val_paths)
    thresholds = {
        "cnn1d": threshold(val_cnn), "autoencoder_reconstruction": threshold(np.asarray(val_ae)),
        "3sigma_causal_window_max": threshold(val_sigma),
        "yolo": threshold(np.asarray([v[0] for v in val_yolo])),
    }
    clean_cnn = torch.sigmoid(cnn(torch.from_numpy(test_clean).to(TORCH_DEVICE))).detach().cpu().numpy()
    ae_clean = []
    for batch in torch.from_numpy(test_clean).split(64):
        recon = vae_reconstruct(vae, batch)
        ae_clean.extend((recon - batch).abs().numpy().max(axis=1))
    clean_sigma = np.asarray([causal_score(x).max() for x in test_clean])
    test_paths = []
    for i, x in enumerate(test_clean):
        p = image_root / "test_clean" / f"{i:06d}.png"
        p.parent.mkdir(parents=True, exist_ok=True); render(x, p); test_paths.append(p)
    clean_yolo = yolo_detect(model, test_paths)
    clean_fpr = {
        "cnn1d": float(np.mean(clean_cnn.max(axis=1) > thresholds["cnn1d"])),
        "autoencoder_reconstruction": float(np.mean(np.asarray(ae_clean) > thresholds["autoencoder_reconstruction"])),
        "3sigma_causal_window_max": float(np.mean(clean_sigma > thresholds["3sigma_causal_window_max"])),
        "yolo": float(np.mean([v[0] > thresholds["yolo"] for v in clean_yolo])),
    }
    recalls = {}
    for family, examples in events.items():
        scores, positions, paths = [], [], []
        for i, (x, interval) in enumerate(examples):
            scores.append(x); positions.append(interval)
            p = image_root / family / f"{i:06d}.png"
            p.parent.mkdir(parents=True, exist_ok=True); render(x, p); paths.append(p)
        batch_x = np.asarray(scores, dtype=np.float32)
        cnn_point = torch.sigmoid(cnn(torch.from_numpy(batch_x).to(TORCH_DEVICE))).detach().cpu().numpy()
        ae_point = []
        for batch in torch.from_numpy(batch_x).split(64):
            recon = vae_reconstruct(vae, batch)
            ae_point.extend((recon - batch).abs().numpy())
        sigma_point = np.asarray([causal_score(x) for x in batch_x])
        yolo_point = yolo_detect(model, paths)
        hit = {name: [] for name in thresholds}
        for i, (lo, hi) in enumerate(positions):
            left, right = max(0, lo - 3), min(LENGTH, hi + 4)
            pred_cnn = int(cnn_point[i].argmax())
            pred_ae = int(np.asarray(ae_point[i]).argmax())
            pred_sigma = int(sigma_point[i].argmax())
            yolo_conf, yolo_pos = yolo_point[i]
            hit["cnn1d"].append(cnn_point[i].max() > thresholds["cnn1d"] and left <= pred_cnn < right)
            hit["autoencoder_reconstruction"].append(
                np.max(ae_point[i]) > thresholds["autoencoder_reconstruction"] and left <= pred_ae < right)
            hit["3sigma_causal_window_max"].append(
                np.max(sigma_point[i]) > thresholds["3sigma_causal_window_max"] and left <= pred_sigma < right)
            hit["yolo"].append(yolo_conf > thresholds["yolo"] and yolo_pos is not None and left <= yolo_pos < right)
        recalls[family] = {k: float(np.mean(v)) for k, v in hit.items()}
    return thresholds, clean_fpr, recalls


def run(out: Path, work: Path, seed: int, train_n: int, val_n: int,
        test_n: int, vae_epochs: int, recognizer_epochs: int, yolo_epochs: int):
    torch.set_num_threads(4)
    print(f"Training device: {TORCH_DEVICE}; YOLO device: {YOLO_DEVICE}")
    rng = np.random.default_rng(seed)
    clean_train = np.asarray([sample_clean(seed + i, "train") for i in range(train_n)], dtype=np.float32)
    clean_ref = np.asarray([sample_clean(seed + 100_000 + i, "train") for i in range(1500)], dtype=np.float32)
    clean_ood = np.asarray([sample_clean(seed + 200_000 + i, "ood") for i in range(val_n + test_n)], dtype=np.float32)
    val_clean, test_clean = clean_ood[:val_n], clean_ood[val_n:]

    vae = fit_vae(clean_train, seed, vae_epochs)
    vae_synthetic = vae_generate(vae, train_n, seed + 1)
    recon = []
    for batch in torch.from_numpy(clean_ref).split(64):
        r = vae_reconstruct(vae, batch)
        recon.extend(r.numpy())
    gen_diagnostics = generation_diagnostics(clean_ref, vae_synthetic)
    gen_diagnostics["clean_reconstruction_rmse"] = float(np.sqrt(np.mean((np.asarray(recon) - clean_ref) ** 2)))

    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    model_dir = out / "models"; model_dir.mkdir(exist_ok=True)
    torch.save(vae.state_dict(), model_dir / "conv_vae_clean_volatility.pt")
    report = {"protocol": {"seed": seed, "window_length": LENGTH, "train": train_n,
                           "validation_clean": val_n, "test_clean": test_n,
                           "yolo_epochs_each": yolo_epochs, "recognizer_epochs": recognizer_epochs,
                           "vae_epochs": vae_epochs, "target_validation_fpr": TARGET_FPR,
                           "train_domain": "Gaussian mean-reverting AR with Markov volatility states",
                           "validation_test_domain": "independent AR parameter ranges with Student-t innovations and switching volatility",
                           "train_defects": ["isolated spike", "smooth hump"],
                           "test_defects": list(FAMILIES),
                           "limits": ["all clean series and labels are synthetic", "one seed; research gate only"]},
              "vae_generation_diagnostics": gen_diagnostics, "models": {}}

    # Generate independent test defect families; none are used for thresholding.
    events = {family: [] for family in FAMILIES}
    for family in FAMILIES:
        for i in range(test_n):
            base = sample_clean(seed + 300_000 + i + 10_000 * FAMILIES.index(family), "ood")
            amp = AMPLITUDES[i % len(AMPLITUDES)] if family != "stale_block" else None
            x, interval = inject(base, family, rng, amp)
            events[family].append((x, interval))

    for mode in ("base", "vae_augmented"):
        use_vae = mode == "vae_augmented"
        x_train, y_train, _ = prepare_train(
            clean_train, vae_synthetic, seed + 50, use_vae)
        cnn = fit_dense_cnn(x_train, y_train, seed, recognizer_epochs)
        # YOLO train/validation data are isolated under /tmp, not committed into the repo.
        data_root = work / mode
        for i, x in enumerate(x_train):
            event_idx = np.flatnonzero(y_train[i])
            event = None if not len(event_idx) else (int(event_idx[0]), int(event_idx[-1]))
            write_item(data_root, "train", i, x, event)
        val_rng = np.random.default_rng(seed + 8)
        for i, x in enumerate(val_clean):
            if i % 2:
                family = "spike" if (i // 2) % 2 == 0 else "hump"
                x, event = inject(x, family, val_rng)
            else:
                event = None
            write_item(data_root, "val", i, x, event)
        (data_root / "dataset.yaml").write_text(
            f"path: {data_root.resolve()}\ntrain: images/train\nval: images/val\nnames:\n  0: defect\n",
            encoding="utf-8")
        best = fit_detector(data_root, "yolo11n.pt", out / "yolo_runs",
                            f"{mode}_seed{seed}", yolo_epochs, seed)
        yolo = YOLO(str(best))
        saved = model_dir / f"yolo11n_{mode}_best.pt"
        shutil.copy2(best, saved)
        torch.save(cnn.state_dict(), model_dir / f"cnn1d_{mode}.pt")

        # A separate clean VAE is used as an anomaly detector, never trained on defects.
        thresholds, fpr, recall = evaluate_model(
            yolo, cnn, vae, val_clean, test_clean, events, work / f"eval_{mode}")
        report["models"][mode] = {"thresholds": thresholds, "clean_test_fpr": fpr,
                                  "event_recall_located": recall,
                                  "yolo_weights": str(saved)}

    report["interpretation"] = (
        "VAE augmentation adds value only if the OOD event-recall lift survives at similar clean-test FPR; "
        "a high synthetic validation score alone is not an operational DQ result.")
    (out / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "results/reports/dq_yolo_generative_pack")
    parser.add_argument("--work", type=Path, default=Path("/tmp/dq_yolo_generative_pack"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train", type=int, default=800)
    parser.add_argument("--val", type=int, default=300)
    parser.add_argument("--test", type=int, default=250)
    parser.add_argument("--vae-epochs", type=int, default=20)
    parser.add_argument("--recognizer-epochs", type=int, default=12)
    parser.add_argument("--yolo-epochs", type=int, default=5)
    args = parser.parse_args()
    print(json.dumps(run(args.out, args.work, args.seed, args.train, args.val, args.test,
                         args.vae_epochs, args.recognizer_epochs, args.yolo_epochs), indent=2))


if __name__ == "__main__":
    main()
