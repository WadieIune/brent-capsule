from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from torch import nn
from torch.utils.data import DataLoader, Dataset

from .config import PATTERN_CLASSES
from .datasets import build_image_for_record, synthetic_example_from_index
from .metrics import class_weights_from_counts, classification_metrics

IMAGENET_MEAN = torch.tensor([0.485, 0.456, 0.406], dtype=torch.float32).view(3, 1, 1)
IMAGENET_STD = torch.tensor([0.229, 0.224, 0.225], dtype=torch.float32).view(3, 1, 1)


def set_global_seed(seed: int) -> None:
    """Fija semillas para reproducibilidad (numpy, random, torch, CUDA)."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def configure_backend(config: Dict[str, object]) -> None:
    """Configura cuDNN para rendimiento en GPU."""
    if bool(config["training"].get("cudnn_benchmark", True)) and torch.cuda.is_available():
        torch.backends.cudnn.benchmark = True


class FocalLoss(nn.Module):
    """Focal loss multiclase para mitigar el desbalance de clases.

    Lin et al. (2017), "Focal Loss for Dense Object Detection". Reduce el peso de
    los ejemplos bien clasificados (clases mayoritarias) para enfocar el
    aprendizaje en las minoritarias (double_top, double_bottom, etc.).
    """

    def __init__(self, gamma: float = 2.0, weight: Optional[torch.Tensor] = None) -> None:
        super().__init__()
        self.gamma = float(gamma)
        self.register_buffer("weight", weight if weight is not None else None)

    def forward(self, logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        ce = F.cross_entropy(logits, target, weight=self.weight, reduction="none")
        pt = torch.exp(-ce)
        loss = ((1.0 - pt) ** self.gamma) * ce
        return loss.mean()


class FallbackConvBackbone(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(3, 32, kernel_size=3, stride=2, padding=1),
            nn.BatchNorm2d(32),
            nn.SiLU(),
            nn.Conv2d(32, 64, kernel_size=3, stride=2, padding=1),
            nn.BatchNorm2d(64),
            nn.SiLU(),
            nn.Conv2d(64, 128, kernel_size=3, stride=2, padding=1),
            nn.BatchNorm2d(128),
            nn.SiLU(),
            nn.Conv2d(128, 192, kernel_size=3, stride=2, padding=1),
            nn.BatchNorm2d(192),
            nn.SiLU(),
            nn.AdaptiveAvgPool2d((1, 1)),
            nn.Flatten(),
        )
        self.out_features = 192

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)



def _load_backbone(force_backend: str | None = None, pretrained: bool = True) -> tuple[nn.Module, int, str]:
    backend_order = [force_backend] if force_backend else ["torchvision", "timm", "fallback"]
    for backend in backend_order:
        if backend == "torchvision":
            try:
                from torchvision.models import EfficientNet_B1_Weights, efficientnet_b1

                weights = EfficientNet_B1_Weights.DEFAULT if pretrained else None
                model = efficientnet_b1(weights=weights)
                feature_dim = int(model.classifier[1].in_features)
                model.classifier = nn.Identity()
                return model, feature_dim, "torchvision"
            except Exception:
                try:
                    from torchvision.models import efficientnet_b1

                    model = efficientnet_b1(weights=None)
                    feature_dim = int(model.classifier[1].in_features)
                    model.classifier = nn.Identity()
                    return model, feature_dim, "torchvision"
                except Exception:
                    continue
        if backend == "timm":
            try:
                import timm

                try:
                    model = timm.create_model("efficientnet_b1", pretrained=bool(pretrained), num_classes=0, global_pool="avg")
                except Exception:
                    model = timm.create_model("efficientnet_b1", pretrained=False, num_classes=0, global_pool="avg")
                feature_dim = int(model.num_features)
                return model, feature_dim, "timm"
            except Exception:
                continue
        if backend == "fallback":
            model = FallbackConvBackbone()
            return model, model.out_features, "fallback"
    model = FallbackConvBackbone()
    return model, model.out_features, "fallback"



def _normalize_image(image: np.ndarray) -> torch.Tensor:
    tensor = torch.from_numpy(image.transpose(2, 0, 1)).float() / 255.0
    return (tensor - IMAGENET_MEAN) / IMAGENET_STD


class CachedImageDataset(Dataset):
    """Dataset sobre imágenes precomputadas (uint8) en memoria.

    Elimina el cuello de botella de reconstruir GASF/GADF + resize en cada
    acceso. La normalización ImageNet se aplica on-the-fly (operación barata).
    """

    def __init__(
        self,
        images: np.ndarray,
        y_class: np.ndarray,
        y_reg: np.ndarray,
        indices: Optional[np.ndarray] = None,
    ) -> None:
        self.images = images
        self.y_class = np.asarray(y_class, dtype=np.int64)
        self.y_reg = np.asarray(y_reg, dtype=np.float32)
        self.indices = (
            np.arange(len(images)) if indices is None else np.asarray(indices, dtype=np.int64)
        )

    def __len__(self) -> int:
        return len(self.indices)

    def __getitem__(self, idx: int):
        real = int(self.indices[idx])
        x = _normalize_image(self.images[real])
        y_class = torch.tensor(int(self.y_class[real]), dtype=torch.long)
        y_reg = torch.tensor(self.y_reg[real], dtype=torch.float32)
        return x, y_class, y_reg


class TorchBrentDataset(Dataset):
    def __init__(
        self,
        frame: pd.DataFrame,
        table: pd.DataFrame,
        feature_cols: Sequence[str],
        config: Dict[str, object],
        split: str,
    ) -> None:
        self.frame = frame.reset_index(drop=True)
        self.table = table[table["split"] == split].reset_index(drop=True)
        self.feature_cols = list(feature_cols)
        self.config = config
        self.image_size = int(config["dataset"]["image_size"])
        self.target_col = str(config["data"].get("target_col", "BRENT"))

    def __len__(self) -> int:
        return len(self.table)

    def __getitem__(self, idx: int):
        row = self.table.iloc[idx]
        image = build_image_for_record(
            self.frame,
            row,
            feature_cols=self.feature_cols,
            image_size=self.image_size,
            target_col=self.target_col,
        )
        x = _normalize_image(image)
        y_class = torch.tensor(int(row["pattern_idx"]), dtype=torch.long)
        y_reg = torch.tensor(row[["future_return", "future_low", "future_high"]].to_numpy(dtype=np.float32), dtype=torch.float32)
        return x, y_class, y_reg


class SyntheticTorchDataset(Dataset):
    def __init__(self, config: Dict[str, object], n_samples: int) -> None:
        self.config = config
        self.n_samples = int(n_samples)

    def __len__(self) -> int:
        return self.n_samples

    def __getitem__(self, idx: int):
        image, label, target = synthetic_example_from_index(idx, self.config)
        x = _normalize_image(image)
        y_class = torch.tensor(int(label), dtype=torch.long)
        y_reg = torch.tensor(target, dtype=torch.float32)
        return x, y_class, y_reg


class BrentTorchModel(nn.Module):
    def __init__(self, dropout: float = 0.30, force_backend: str | None = None, pretrained: bool = True) -> None:
        super().__init__()
        backbone, feature_dim, backend = _load_backbone(force_backend=force_backend, pretrained=pretrained)
        self.backbone = backbone
        self.backend = backend
        self.head = nn.Sequential(
            nn.Dropout(dropout),
            nn.Linear(feature_dim, 256),
            nn.SiLU(),
            nn.Dropout(dropout),
        )
        self.classifier = nn.Linear(256, len(PATTERN_CLASSES))
        self.regressor = nn.Linear(256, 3)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        feats = self.backbone(x)
        shared = self.head(feats)
        return self.classifier(shared), self.regressor(shared)

    def freeze_backbone(self) -> None:
        for param in self.backbone.parameters():
            param.requires_grad = False

    def _backbone_blocks(self) -> Optional[nn.Module]:
        """Localiza el contenedor secuencial de bloques del backbone.

        EfficientNet de torchvision expone ``features`` (Sequential de 9 bloques);
        timm expone ``blocks``. Se devuelve dicho contenedor para hacer
        fine-tuning progresivo de los últimos N bloques (no de toda la red).
        """
        if hasattr(self.backbone, "features") and isinstance(self.backbone.features, nn.Sequential):
            return self.backbone.features
        if hasattr(self.backbone, "blocks") and isinstance(self.backbone.blocks, nn.Sequential):
            return self.backbone.blocks
        return None

    def unfreeze_last_blocks(self, n_last_blocks: int = 2, freeze_bn: bool = True) -> None:
        """Descongela solo los últimos `n_last_blocks` bloques del backbone.

        Corrige el comportamiento previo, que descongelaba la red entera. Si
        `freeze_bn` es True, las BatchNorm descongeladas se mantienen en modo
        eval con stats fijas (recomendado con batches pequeños y datasets cortos).
        """
        for param in self.backbone.parameters():
            param.requires_grad = False

        blocks = self._backbone_blocks()
        if blocks is None:
            # Fallback / arquitectura desconocida: descongela todo el backbone.
            for param in self.backbone.parameters():
                param.requires_grad = True
            target_modules = [self.backbone]
        else:
            n = max(1, min(int(n_last_blocks), len(blocks)))
            target_modules = list(blocks)[-n:]
            for module in target_modules:
                for param in module.parameters():
                    param.requires_grad = True

        if freeze_bn:
            for module in target_modules:
                for sub in module.modules():
                    if isinstance(sub, nn.BatchNorm2d):
                        sub.eval()
                        for p in sub.parameters():
                            p.requires_grad = False


@dataclass
class EpochStats:
    loss: float
    cls_loss: float
    reg_loss: float
    accuracy: float
    mae: float
    balanced_accuracy: float = 0.0
    macro_f1: float = 0.0



def _run_epoch(
    model: BrentTorchModel,
    loader: DataLoader,
    optimizer,
    device: torch.device,
    regression_weight: float,
    train: bool,
    cls_criterion: nn.Module,
    reg_criterion: nn.Module,
    scaler: Optional["torch.cuda.amp.GradScaler"] = None,
    use_amp: bool = False,
    grad_clip_norm: float = 0.0,
) -> EpochStats:
    model.train(mode=train)
    total_loss = 0.0
    total_cls = 0.0
    total_reg = 0.0
    total_correct = 0
    total_obs = 0
    total_mae = 0.0
    all_true: List[int] = []
    all_pred: List[int] = []

    amp_enabled = bool(use_amp) and device.type == "cuda"
    autocast_device = "cuda" if device.type == "cuda" else "cpu"

    for x, y_class, y_reg in loader:
        x = x.to(device, non_blocking=True)
        y_class = y_class.to(device, non_blocking=True)
        y_reg = y_reg.to(device, non_blocking=True)

        if train:
            optimizer.zero_grad(set_to_none=True)

        with torch.autocast(device_type=autocast_device, enabled=amp_enabled):
            logits, reg_out = model(x)
            cls_loss = cls_criterion(logits, y_class)
            reg_loss = reg_criterion(reg_out, y_reg)
            loss = cls_loss + regression_weight * reg_loss

        if train:
            if scaler is not None and amp_enabled:
                scaler.scale(loss).backward()
                if grad_clip_norm and grad_clip_norm > 0:
                    scaler.unscale_(optimizer)
                    nn.utils.clip_grad_norm_(model.parameters(), grad_clip_norm)
                scaler.step(optimizer)
                scaler.update()
            else:
                loss.backward()
                if grad_clip_norm and grad_clip_norm > 0:
                    nn.utils.clip_grad_norm_(model.parameters(), grad_clip_norm)
                optimizer.step()

        with torch.no_grad():
            preds = torch.argmax(logits, dim=1)
            total_correct += int((preds == y_class).sum().item())
            total_obs += int(x.size(0))
            total_mae += float(torch.mean(torch.abs(reg_out.float() - y_reg)).item()) * int(x.size(0))
            total_loss += float(loss.item()) * int(x.size(0))
            total_cls += float(cls_loss.item()) * int(x.size(0))
            total_reg += float(reg_loss.item()) * int(x.size(0))
            all_true.extend(y_class.cpu().numpy().tolist())
            all_pred.extend(preds.cpu().numpy().tolist())

    denom = max(1, total_obs)
    true_labels = [PATTERN_CLASSES[i] for i in all_true]
    pred_labels = [PATTERN_CLASSES[i] for i in all_pred]
    cls_report = classification_metrics(true_labels, pred_labels, PATTERN_CLASSES)
    return EpochStats(
        loss=total_loss / denom,
        cls_loss=total_cls / denom,
        reg_loss=total_reg / denom,
        accuracy=total_correct / denom,
        mae=total_mae / denom,
        balanced_accuracy=float(cls_report["balanced_accuracy"]),
        macro_f1=float(cls_report["macro_f1"]),
    )



def _make_loader(dataset: Dataset, config: Dict[str, object], shuffle: bool) -> DataLoader:
    num_workers = int(config["training"].get("num_workers", 0))
    use_cuda = torch.cuda.is_available()
    kwargs = dict(
        batch_size=int(config["training"].get("batch_size", 16)),
        shuffle=shuffle,
        num_workers=num_workers,
        pin_memory=bool(config["training"].get("pin_memory", True)) and use_cuda,
        drop_last=False,
    )
    if num_workers > 0:
        kwargs["persistent_workers"] = bool(config["training"].get("persistent_workers", True))
        kwargs["prefetch_factor"] = 4
    return DataLoader(dataset, **kwargs)


def _build_criteria(
    config: Dict[str, object],
    y_class_train: np.ndarray,
    device: torch.device,
) -> tuple[nn.Module, nn.Module]:
    """Construye criterios de clasificación (con pesos/focal) y regresión."""
    counts = np.array(
        [int(np.sum(y_class_train == i)) for i in range(len(PATTERN_CLASSES))], dtype=float
    )
    scheme = str(config["training"].get("class_weight_scheme", "balanced"))
    if scheme and scheme != "none":
        weights_np = class_weights_from_counts(counts, scheme=scheme)
        weight = torch.tensor(weights_np, dtype=torch.float32, device=device)
    else:
        weight = None

    if bool(config["training"].get("use_focal_loss", False)):
        cls_criterion: nn.Module = FocalLoss(
            gamma=float(config["training"].get("focal_gamma", 2.0)), weight=weight
        ).to(device)
    else:
        cls_criterion = nn.CrossEntropyLoss(weight=weight)
    reg_criterion = nn.SmoothL1Loss()
    return cls_criterion, reg_criterion


def _monitor_value(stats: EpochStats, metric: str) -> float:
    if metric == "macro_f1":
        return stats.macro_f1
    if metric == "balanced_accuracy":
        return stats.balanced_accuracy
    return stats.accuracy



def _select_device(config: Dict[str, object]) -> torch.device:
    requested = str(config["training"].get("device", "cuda"))
    if requested == "cuda" and torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")



def _train_phase(
    model: BrentTorchModel,
    train_loader: DataLoader,
    valid_loader: DataLoader,
    optimizer,
    device: torch.device,
    config: Dict[str, object],
    cls_criterion: nn.Module,
    reg_criterion: nn.Module,
    scaler,
    regression_weight: float,
    n_epochs: int,
    monitor_metric: str,
) -> tuple[dict, Dict[str, List[float]], float]:
    """Bucle de entrenamiento con scheduler coseno, AMP y early-stopping por métrica."""
    use_amp = bool(config["training"].get("amp", True))
    grad_clip = float(config["training"].get("grad_clip_norm", 0.0))
    patience = int(config["training"].get("patience", 5))
    patience_left = patience

    scheduler = None
    if str(config["training"].get("lr_scheduler", "cosine")) == "cosine" and n_epochs > 1:
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=n_epochs)

    history: Dict[str, List[float]] = {
        "train_loss": [], "train_macro_f1": [], "train_mae": [],
        "valid_loss": [], "valid_macro_f1": [], "valid_balanced_accuracy": [],
        "valid_accuracy": [], "valid_mae": [],
    }
    best_state = None
    best_metric = -np.inf

    for _ in range(int(n_epochs)):
        train_stats = _run_epoch(
            model, train_loader, optimizer, device, regression_weight, train=True,
            cls_criterion=cls_criterion, reg_criterion=reg_criterion,
            scaler=scaler, use_amp=use_amp, grad_clip_norm=grad_clip,
        )
        with torch.no_grad():
            valid_stats = _run_epoch(
                model, valid_loader, optimizer, device, regression_weight, train=False,
                cls_criterion=cls_criterion, reg_criterion=reg_criterion,
                scaler=scaler, use_amp=use_amp, grad_clip_norm=grad_clip,
            )
        if scheduler is not None:
            scheduler.step()

        history["train_loss"].append(train_stats.loss)
        history["train_macro_f1"].append(train_stats.macro_f1)
        history["train_mae"].append(train_stats.mae)
        history["valid_loss"].append(valid_stats.loss)
        history["valid_macro_f1"].append(valid_stats.macro_f1)
        history["valid_balanced_accuracy"].append(valid_stats.balanced_accuracy)
        history["valid_accuracy"].append(valid_stats.accuracy)
        history["valid_mae"].append(valid_stats.mae)

        monitor = _monitor_value(valid_stats, monitor_metric)
        if monitor > best_metric:
            best_metric = monitor
            best_state = {k: v.cpu() for k, v in model.state_dict().items()}
            patience_left = patience
        else:
            patience_left -= 1
            if patience_left <= 0:
                break

    return best_state, history, float(best_metric)


def train_torch_pipeline(
    frame: pd.DataFrame,
    table: pd.DataFrame,
    feature_cols: Sequence[str],
    config: Dict[str, object],
    output_dir: str,
    fold_id: Optional[int] = None,
) -> Dict[str, object]:
    from .image_cache import precompute_synthetic_images, precompute_window_images

    os.makedirs(output_dir, exist_ok=True)
    set_global_seed(int(config["training"].get("seed", 42)))
    configure_backend(config)

    device = _select_device(config)
    model = BrentTorchModel(
        dropout=float(config["training"].get("dropout", 0.30)),
        pretrained=bool(config["training"].get("pretrained_backbone", True)),
    ).to(device)
    regression_weight = float(config["training"].get("regression_loss_weight", 0.50))
    monitor_metric = str(config["training"].get("monitor_metric", "macro_f1"))
    use_amp = bool(config["training"].get("amp", True)) and device.type == "cuda"
    cache_dir = config["output"].get("cache_dir") if bool(config["training"].get("cache_images", True)) else None
    image_size = int(config["dataset"]["image_size"])
    target_col = str(config["data"].get("target_col", "BRENT"))

    # Precompute (and cache) imágenes de TODAS las ventanas una sola vez.
    images = precompute_window_images(
        frame, table, feature_cols, image_size=image_size, target_col=target_col, cache_dir=cache_dir,
    )
    y_class = table["pattern_idx"].to_numpy(dtype=np.int64)
    y_reg = table[["future_return", "future_low", "future_high"]].to_numpy(dtype=np.float32)

    train_idx = np.where(table["split"].to_numpy() == "train")[0]
    valid_idx = np.where(table["split"].to_numpy() == "valid")[0]
    if len(train_idx) == 0 or len(valid_idx) == 0:
        raise ValueError("Splits 'train'/'valid' vacíos en la window_table.")

    train_ds = CachedImageDataset(images, y_class, y_reg, indices=train_idx)
    valid_ds = CachedImageDataset(images, y_class, y_reg, indices=valid_idx)
    train_loader = _make_loader(train_ds, config, shuffle=True)
    valid_loader = _make_loader(valid_ds, config, shuffle=False)

    cls_criterion, reg_criterion = _build_criteria(config, y_class[train_idx], device)
    scaler = torch.cuda.amp.GradScaler(enabled=use_amp)

    # Pre-entrenamiento sintético (opcional), también cacheado.
    if bool(config["dataset"].get("use_synthetic_pretrain", True)):
        synth_x, synth_yc, synth_yr = precompute_synthetic_images(
            config, n_samples=int(config["dataset"].get("synthetic_samples", 8000)), cache_dir=cache_dir,
        )
        synth_ds = CachedImageDataset(synth_x, synth_yc, synth_yr)
        synth_loader = _make_loader(synth_ds, config, shuffle=True)
        synth_epochs = max(1, min(5, int(config["training"].get("epochs", 12)) // 2))
        model.freeze_backbone()
        synth_opt = torch.optim.AdamW(
            filter(lambda p: p.requires_grad, model.parameters()),
            lr=float(config["training"].get("learning_rate", 3e-4)),
        )
        for _ in range(synth_epochs):
            _run_epoch(
                model, synth_loader, synth_opt, device, regression_weight, train=True,
                cls_criterion=nn.CrossEntropyLoss(), reg_criterion=reg_criterion,
                scaler=scaler, use_amp=use_amp,
                grad_clip_norm=float(config["training"].get("grad_clip_norm", 0.0)),
            )

    # Fase 1: warm-up con backbone congelado.
    model.freeze_backbone()
    optimizer = torch.optim.AdamW(
        filter(lambda p: p.requires_grad, model.parameters()),
        lr=float(config["training"].get("learning_rate", 3e-4)),
    )
    best_state, history, best_warm = _train_phase(
        model, train_loader, valid_loader, optimizer, device, config,
        cls_criterion, reg_criterion, scaler, regression_weight,
        n_epochs=int(config["training"].get("epochs", 12)), monitor_metric=monitor_metric,
    )
    if best_state is not None:
        model.load_state_dict(best_state)

    # Fase 2: fine-tuning de los últimos bloques.
    model.unfreeze_last_blocks(
        n_last_blocks=int(config["training"].get("unfreeze_last_blocks", 2)),
        freeze_bn=bool(config["training"].get("freeze_backbone_bn", True)),
    )
    optimizer = torch.optim.AdamW(
        filter(lambda p: p.requires_grad, model.parameters()),
        lr=float(config["training"].get("fine_tune_learning_rate", 1e-4)),
    )
    best_state_ft, fine_history, best_fine = _train_phase(
        model, train_loader, valid_loader, optimizer, device, config,
        cls_criterion, reg_criterion, scaler, regression_weight,
        n_epochs=int(config["training"].get("fine_tune_epochs", 8)), monitor_metric=monitor_metric,
    )
    if best_state_ft is not None:
        model.load_state_dict(best_state_ft)

    suffix = "" if fold_id is None else f"_fold{fold_id}"
    base_name = str(config["output"].get("torch_model_name", "brent_efficientnet_b1_torch.pt"))
    if suffix:
        root, ext = os.path.splitext(base_name)
        base_name = f"{root}{suffix}{ext}"
    model_path = os.path.join(output_dir, base_name)
    torch.save({
        "state_dict": model.state_dict(),
        "pattern_classes": PATTERN_CLASSES,
        "backend": model.backend,
    }, model_path)

    report = {
        "model_path": model_path,
        "fold_id": fold_id,
        "device": str(device),
        "amp": bool(use_amp),
        "backbone_backend": model.backend,
        "monitor_metric": monitor_metric,
        "train_windows": int(len(train_ds)),
        "valid_windows": int(len(valid_ds)),
        "best_valid_warm": best_warm,
        "best_valid_fine": best_fine,
        "warm_history": history,
        "fine_tune_history": fine_history,
    }
    report_name = f"torch_training_report{suffix}.json"
    with open(os.path.join(output_dir, report_name), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    return report



def load_torch_model(model_path: str, config: Dict[str, object]) -> tuple[BrentTorchModel, torch.device]:
    device = _select_device(config)
    checkpoint = torch.load(model_path, map_location=device)
    model = BrentTorchModel(
        dropout=float(config["training"].get("dropout", 0.30)),
        force_backend=str(checkpoint.get("backend", "fallback")),
        pretrained=False,
    )
    model.load_state_dict(checkpoint["state_dict"])
    model.to(device)
    model.eval()
    return model, device



def predict_torch_model(
    model_path: str,
    frame: pd.DataFrame,
    infer_table: pd.DataFrame,
    feature_cols: Sequence[str],
    config: Dict[str, object],
) -> pd.DataFrame:
    model, device = load_torch_model(model_path, config)
    target_col = str(config["data"].get("target_col", "BRENT"))
    image_size = int(config["dataset"]["image_size"])
    batch_size = int(config["training"].get("batch_size", 16))

    results: List[Dict[str, float]] = []
    batch_images: List[torch.Tensor] = []
    batch_rows: List[pd.Series] = []

    def _flush() -> None:
        nonlocal batch_images, batch_rows, results
        if not batch_images:
            return
        x = torch.stack(batch_images, dim=0).to(device)
        with torch.no_grad():
            logits, reg = model(x)
            probs = torch.softmax(logits, dim=1).cpu().numpy()
            reg_np = reg.cpu().numpy()

        for row, prob_row, level_row in zip(batch_rows, probs, reg_np):
            current_price = float(frame.iloc[int(row["end"]) - 1][target_col])
            pred_pattern = PATTERN_CLASSES[int(np.argmax(prob_row))]
            payload = {
                "start": int(row["start"]),
                "end": int(row["end"]),
                "end_date": row["end_date"],
                "predicted_pattern": pred_pattern,
                "pred_return": float(level_row[0]),
                "pred_low": float(level_row[1]),
                "pred_high": float(level_row[2]),
                "target_level": float(current_price * (1.0 + float(level_row[0]))),
                "support_level": float(current_price * (1.0 + float(level_row[1]))),
                "resistance_level": float(current_price * (1.0 + float(level_row[2]))),
            }
            for i, label in enumerate(PATTERN_CLASSES):
                payload[f"prob_{label}"] = float(prob_row[i])
            results.append(payload)
        batch_images = []
        batch_rows = []

    for _, row in infer_table.iterrows():
        image = build_image_for_record(frame, row, feature_cols=feature_cols, image_size=image_size, target_col=target_col)
        batch_images.append(_normalize_image(image))
        batch_rows.append(row)
        if len(batch_images) >= batch_size:
            _flush()
    _flush()

    return pd.DataFrame(results)
