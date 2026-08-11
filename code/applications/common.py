"""Utilidades compartidas por los experimentos de aplicaciones.

Reutiliza la geometría del canal ya implementada y validada en la 2ª pata
(`../part2_channel_survival/channel_survival.py`) — misma recta OLS + banda de
residuos ±k·σ y ATR proxy — para NO reimplementar (ni desincronizar) la
definición del canal del proyecto.

Incluye además: carga de precios (con fallback sintético para poder ejecutar los
experimentos sin la serie propietaria), residuo de consistencia hacia delante
(DQ), volatilidad realizada / EWMA y un split temporal sin fuga.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# --- Acceso a la geometría del canal de la 2ª pata ---------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))


def _find_part2() -> str:
    """Localiza `part2_channel_survival/` subiendo directorios.

    Robusto a dónde se coloque este paquete dentro del repo: evita que un cambio
    de ubicación de la carpeta rompa el import de la geometría del canal.
    """
    d = _HERE
    for _ in range(5):
        cand = os.path.join(d, "part2_channel_survival")
        if os.path.isdir(cand):
            return cand
        d = os.path.dirname(d)
    return os.path.normpath(os.path.join(_HERE, "..", "part2_channel_survival"))


_PART2 = _find_part2()
if _PART2 not in sys.path:
    sys.path.insert(0, _PART2)

import channel_survival as cs  # noqa: E402  (geometría/episodios ya validados)

LOOKBACK: int = cs.LOOKBACK
BAND_MULT: float = cs.BAND_MULT
ATR_WIN: int = cs.ATR_WIN
TOL_ATR: float = cs.TOL_ATR
FEATURES: List[str] = cs.FEATURES


# --- Carga de precios ---------------------------------------------------------
def synthetic_brent(n: int = 1600, seed: int = 42) -> pd.Series:
    """Serie de precios sintética con tramos de canal, compresión y saltos.

    Solo para poder ejecutar/verificar los experimentos SIN la serie real del
    proyecto. No es dato de mercado: no usar para conclusiones.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2015-01-01", periods=n)
    price = np.zeros(n, dtype=float)
    price[0] = 60.0
    # regímenes alternos: tendencia / rango / compresión con expansión
    regime_len = 80
    drift, vol = 0.0004, 0.012
    for t in range(1, n):
        if t % regime_len == 0:
            phase = (t // regime_len) % 3
            drift = {0: 0.0009, 1: 0.0, 2: -0.0007}[phase]
            vol = {0: 0.010, 1: 0.006, 2: 0.018}[phase]  # rango = compresión
        shock = rng.normal(drift, vol)
        price[t] = max(price[t - 1] * (1.0 + shock), 1.0)
    s = pd.Series(price, index=dates, name="BRENT")
    return s


def load_prices(path: Optional[str] = None, synthetic: bool = False,
                seed: int = 42) -> Tuple[pd.Series, str]:
    """Devuelve (serie, fuente). Usa la serie real si existe; si no, sintética.

    `fuente` ∈ {"file:<path>", "synthetic"} y se registra en el manifest.
    """
    if synthetic:
        return synthetic_brent(seed=seed), "synthetic"
    candidate = path or cs._default_prices_path()
    if candidate and os.path.exists(candidate):
        return cs.load_brent(candidate), f"file:{candidate}"
    return synthetic_brent(seed=seed), "synthetic (fallback: serie real no encontrada)"


# --- Geometría rolling (para DQ y forecast) ----------------------------------
def atr_like(prices: np.ndarray, win: int = ATR_WIN) -> np.ndarray:
    return cs._atr_like(prices, win)


def forward_channel_residual(prices: np.ndarray, lookback: int = LOOKBACK
                             ) -> pd.DataFrame:
    """Consistencia hacia delante de cada observación con su canal reciente.

    Para cada t≥lookback ajusta la recta OLS sobre las `lookback` observaciones
    PREVIAS (t-lookback..t-1) — sin incluir el punto evaluado, evitando fuga — y
    proyecta el centro y la banda al instante t. Devuelve el z-score del residuo
    del nuevo precio: z = (p[t] − centro_proyectado) / σ_resid.
    """
    n = len(prices)
    rows: List[Dict[str, float]] = []
    for t in range(lookback, n):
        win = prices[t - lookback:t]
        if np.isnan(win).any():
            continue
        slope, intercept, resid_std, r2 = cs._fit_line(cs.smooth_series(win))
        center = intercept + slope * lookback  # proyección un paso adelante
        resid_std = resid_std if resid_std > 1e-9 else 1e-9
        z = (prices[t] - center) / resid_std
        rows.append({
            "pos": t,
            "price": float(prices[t]),
            "center": float(center),
            "resid_std": float(resid_std),
            "z": float(z),
            "band_width_rel": float(2.0 * BAND_MULT * resid_std / max(center, 1e-9)),
            "r2": float(r2),
            "slope_norm": float(slope / max(np.mean(win), 1e-9)),
        })
    return pd.DataFrame(rows)


# --- Volatilidad --------------------------------------------------------------
def log_returns(prices: np.ndarray) -> np.ndarray:
    prices = np.asarray(prices, dtype=float)
    return np.diff(np.log(np.clip(prices, 1e-9, None)))


def realized_vol(returns: np.ndarray, window: int = 20) -> np.ndarray:
    return pd.Series(returns).rolling(window, min_periods=window).std().to_numpy()


def ewma_vol(returns: np.ndarray, lam: float = 0.94) -> np.ndarray:
    """Volatilidad EWMA (RiskMetrics). Devuelve la desviación por posición."""
    r = np.asarray(returns, dtype=float)
    var = np.zeros_like(r)
    if len(r) == 0:
        return var
    var[0] = r[0] ** 2
    for t in range(1, len(r)):
        var[t] = lam * var[t - 1] + (1.0 - lam) * r[t - 1] ** 2
    return np.sqrt(var)


# --- Supervivencia del canal como feature (P(T>k)) ---------------------------
def _km_curve(durations: np.ndarray, events: np.ndarray) -> List[Tuple[float, float]]:
    """Estimador de Kaplan-Meier: devuelve [(t, S(t))] como función escalón."""
    d = np.asarray(durations, dtype=float)
    e = np.asarray(events, dtype=int)
    curve: List[Tuple[float, float]] = []
    s = 1.0
    for t in np.unique(d):
        n_risk = float(np.sum(d >= t))
        n_evt = float(np.sum((d == t) & (e == 1)))
        if n_risk > 0:
            s *= (1.0 - n_evt / n_risk)
        curve.append((float(t), float(s)))
    return curve


def _km_at(curve: List[Tuple[float, float]], k: float) -> float:
    """S(k) = supervivencia en el mayor tiempo de evento <= k (1.0 si k<primer t)."""
    s = 1.0
    for t, sv in curve:
        if t <= k:
            s = sv
        else:
            break
    return s


class SurvivalFeaturizer:
    """Convierte la supervivencia del canal en una feature por ventana: P(T>k).

    Se ajusta SOLO con episodios del periodo de train (sin fuga temporal). Usa
    Cox (lifelines) si está instalado; si no, cae a un Kaplan-Meier por buckets
    de una feature geométrica (`bucket_feature`), de modo que la integración de
    supervivencia funciona sin dependencias pesadas y mejora automáticamente al
    instalar lifelines/scikit-survival.
    """

    def __init__(self, n_buckets: int = 3, bucket_feature: str = "band_width",
                 penalizer: float = 0.1):
        self.n_buckets = n_buckets
        self.bucket_feature = bucket_feature if bucket_feature in FEATURES else FEATURES[4]
        self.penalizer = penalizer
        self.method = "none"
        self.detail = ""
        self._cox = None
        self._mu = None
        self._sd = None
        self._edges: Optional[np.ndarray] = None
        self._bucket_curves: List[List[Tuple[float, float]]] = []
        self._global_curve: List[Tuple[float, float]] = []

    def fit(self, episodes: pd.DataFrame, cutoff: Optional[str] = None) -> "SurvivalFeaturizer":
        if episodes is None or episodes.empty:
            self.method = "none"
            self.detail = "sin episodios"
            return self
        if cutoff:
            tr = episodes["start_date"] <= pd.Timestamp(cutoff)
        else:
            k = int(len(episodes) * 0.70)
            tr = pd.Series(np.arange(len(episodes)) < k, index=episodes.index)
        ep = episodes.loc[tr]
        if len(ep) < 15 or int(ep["event"].sum()) < 8:
            self.method = "none"
            self.detail = f"episodios de train insuficientes ({len(ep)})"
            return self

        dur = ep["duration"].to_numpy(dtype=float).clip(min=0.5)
        evt = ep["event"].to_numpy(dtype=int)
        self._global_curve = _km_curve(dur, evt)

        # 1) Cox (lifelines) si está disponible.
        try:
            from lifelines import CoxPHFitter

            X = ep[FEATURES].to_numpy(dtype=float)
            self._mu = X.mean(axis=0)
            self._sd = X.std(axis=0)
            self._sd[self._sd == 0] = 1.0
            Xs = (X - self._mu) / self._sd
            df = pd.DataFrame(Xs, columns=FEATURES)
            df["duration"], df["event"] = dur, evt
            self._cox = CoxPHFitter(penalizer=self.penalizer).fit(df, "duration", "event")
            self.method = "cox"
            self.detail = f"CoxPHFitter (n_train={len(ep)}, eventos={int(evt.sum())})"
            return self
        except Exception as exc:  # lifelines ausente o fallo de ajuste
            self.detail = f"cox no disponible ({type(exc).__name__}); KM por buckets"

        # 2) Fallback: Kaplan-Meier por buckets de una feature geométrica.
        f = ep[self.bucket_feature].to_numpy(dtype=float)
        qs = np.linspace(0.0, 1.0, self.n_buckets + 1)[1:-1]
        self._edges = np.quantile(f, qs) if qs.size else np.array([])
        buckets = np.digitize(f, self._edges) if self._edges.size else np.zeros(len(f), dtype=int)
        self._bucket_curves = []
        for b in range(self.n_buckets):
            sel = buckets == b
            if sel.sum() >= 5 and int(evt[sel].sum()) >= 2:
                self._bucket_curves.append(_km_curve(dur[sel], evt[sel]))
            else:
                self._bucket_curves.append(self._global_curve)
        self.method = "km_bucket"
        return self

    def predict_pk(self, feats: pd.DataFrame, k: float) -> np.ndarray:
        """Devuelve P(T>k) por fila de `feats` (columnas FEATURES)."""
        if self.method == "none":
            return np.full(len(feats), np.nan)
        if self.method == "cox":
            X = feats[FEATURES].to_numpy(dtype=float)
            Xs = (X - self._mu) / self._sd
            sf = self._cox.predict_survival_function(
                pd.DataFrame(Xs, columns=FEATURES), times=[float(k)]
            )
            return sf.loc[float(k)].to_numpy()
        # km_bucket
        f = feats[self.bucket_feature].to_numpy(dtype=float)
        buckets = np.digitize(f, self._edges) if self._edges is not None and self._edges.size else np.zeros(len(f), dtype=int)
        return np.array([_km_at(self._bucket_curves[min(b, len(self._bucket_curves) - 1)], k)
                         for b in buckets])


def window_features(prices: np.ndarray) -> Tuple[np.ndarray, np.ndarray, pd.DataFrame]:
    """Wrapper de is_channel_flags: (idxs e0, flags canal, DataFrame de FEATURES)."""
    idxs, flags, feats = cs.is_channel_flags(prices)
    return idxs, flags, pd.DataFrame(feats)[FEATURES] if feats else pd.DataFrame(columns=FEATURES)


# --- Split temporal sin fuga --------------------------------------------------
def temporal_mask(dates: pd.DatetimeIndex, cutoff: Optional[str]) -> np.ndarray:
    """Máscara booleana de train (True) según cutoff; 70% si no se da cutoff."""
    if cutoff:
        # `DatetimeIndex <= Timestamp` ya devuelve un ndarray (una Series no):
        # np.asarray cubre ambos casos sin depender de la versión de pandas.
        return np.asarray(pd.DatetimeIndex(dates) <= pd.Timestamp(cutoff), dtype=bool)
    k = int(len(dates) * 0.70)
    return np.arange(len(dates)) < k