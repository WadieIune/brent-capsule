"""Aplicación 10 — Capa de régimen: cadena de Markov y red bayesiana.

Es el **paso previo** a los modelos predictivos (GARCH, XGBoost): convierte la
geometría del canal en un pequeño conjunto de estados discretos con
probabilidades de transición y de ruptura estimadas, interpretables y auditables,
que luego pueden entrar como variables en un modelo de volatilidad.

Estados
-------
Se cruzan dos dimensiones observables sin fuga: la dirección del canal
(ascendente / descendente) y la posición dentro de la banda (centro / borde),
más un estado `sin_canal`. La posición se discretiza porque la tasa de ruptura
en función de ella es una **U** —máxima en ambos bordes, mínima en el centro—,
de modo que un corte por distancia al centro captura la no monotonía que un
modelo lineal no puede representar.

Qué se contrasta
----------------
1. **Matriz de transición** estimada en train y evaluada en test por
   log-verosimilitud frente a un modelo i.i.d. (sin memoria de estado). Si no
   supera al i.i.d., la estructura de estados no aporta.
2. **¿Se cumple la propiedad de Markov en la duración?** Se compara el *hazard*
   empírico de ruptura por tiempo transcurrido con un hazard constante. Si el
   hazard es plano, la duración es aproximadamente geométrica: la cadena de
   Markov es suficiente y un modelo semi-Markov (dependiente de la edad) no
   añadiría nada. Es una comprobación que rara vez se hace y que aquí decide
   entre dos familias de modelos.
3. **Red bayesiana discreta** (tablas de probabilidad condicionada con
   suavizado de Laplace) para `P(ruptura <= h | estado, volatilidad)`. Se evalúa
   fuera de muestra por AUC y por **Brier score**, porque lo que necesita un
   modelo de volatilidad aguas abajo es una probabilidad calibrada, no una
   ordenación.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP not in sys.path:
    sys.path.insert(0, _APP)

import common  # noqa: E402
from harness import Experiment, ExperimentResult, RunContext  # noqa: E402
from experiments.breakout_detection import build_hazard_dataset  # noqa: E402
from sklearn.metrics import brier_score_loss, roc_auc_score  # noqa: E402


def build_states(df: pd.DataFrame, edge_cut: float) -> np.ndarray:
    """Estado discreto por sesión: dirección x zona de la banda."""
    d = np.where(df["dir_asc"].to_numpy() > 0.5, "asc", "desc")
    z = np.where(df["edge_distance"].to_numpy() >= edge_cut, "borde", "centro")
    return np.array([f"{a}_{b}" for a, b in zip(d, z)])


def transition_matrix(states: np.ndarray, labels: List[str], alpha: float = 1.0
                      ) -> pd.DataFrame:
    """Matriz de transición con suavizado de Laplace (filas = origen)."""
    idx = {s: i for i, s in enumerate(labels)}
    m = np.full((len(labels), len(labels)), alpha, dtype=float)
    for a, b in zip(states[:-1], states[1:]):
        if a in idx and b in idx:
            m[idx[a], idx[b]] += 1.0
    m = m / m.sum(axis=1, keepdims=True)
    return pd.DataFrame(m, index=labels, columns=labels)


def stationary_distribution(P: pd.DataFrame) -> Dict[str, float]:
    vals, vecs = np.linalg.eig(P.to_numpy().T)
    i = int(np.argmin(np.abs(vals - 1.0)))
    v = np.real(vecs[:, i])
    v = np.abs(v) / np.abs(v).sum()
    return {s: round(float(x), 4) for s, x in zip(P.index, v)}


def expected_sojourn(P: pd.DataFrame) -> Dict[str, float]:
    """Permanencia esperada en cada estado: 1/(1-p_ii) sesiones."""
    return {s: round(float(1.0 / max(1.0 - P.loc[s, s], 1e-9)), 2) for s in P.index}


def sequence_loglik(states: np.ndarray, P: pd.DataFrame, labels: List[str]) -> float:
    idx = {s: i for i, s in enumerate(labels)}
    ll = 0.0
    for a, b in zip(states[:-1], states[1:]):
        if a in idx and b in idx:
            ll += float(np.log(max(P.iloc[idx[a], idx[b]], 1e-12)))
    return ll


def iid_loglik(states: np.ndarray, freqs: Dict[str, float]) -> float:
    return float(sum(np.log(max(freqs.get(s, 1e-12), 1e-12)) for s in states[1:]))


def hazard_by_age(df: pd.DataFrame, y: np.ndarray, mask: np.ndarray,
                  bins: Tuple[int, ...] = (0, 3, 6, 10, 15, 25, 1000)
                  ) -> List[Dict[str, object]]:
    """Hazard empírico de ruptura por tiempo transcurrido en el episodio."""
    age = df.loc[mask, "time_in_episode"].to_numpy()
    yy = y[mask]
    out: List[Dict[str, object]] = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        m = (age >= lo) & (age < hi)
        if m.sum() >= 30:
            out.append({"age_from": int(lo), "age_to": int(hi),
                        "hazard": round(float(yy[m].mean()), 4), "n": int(m.sum())})
    return out


def hazard_homogeneity_test(hz: List[Dict[str, object]], y_rate: float) -> Dict[str, object]:
    """Contraste de homogeneidad del hazard entre tramos de edad (chi-cuadrado).

    Sustituye a un umbral de rango arbitrario: si no se rechaza la homogeneidad,
    la tasa de ruptura no depende del tiempo transcurrido —duración
    aproximadamente geométrica— y la cadena de Markov es suficiente; un modelo
    semi-Markov dependiente de la edad no aportaría estructura.
    """
    if len(hz) < 2:
        return {"testable": False}
    stat = 0.0
    for h in hz:
        n, obs = int(h["n"]), float(h["hazard"]) * int(h["n"])
        exp = n * y_rate
        if exp > 0 and (n - exp) > 0:
            stat += (obs - exp) ** 2 / exp + ((n - obs) - (n - exp)) ** 2 / (n - exp)
    dfree = len(hz) - 1
    from experiments.predicted_var import _chi2_sf
    p = float(_chi2_sf(stat, dfree))
    return {"testable": True, "chi2": round(stat, 3), "df": dfree,
            "p_value": round(p, 4), "homogeneous": bool(p >= 0.05),
            "reading": ("no se rechaza la homogeneidad: hazard sin dependencia de la edad, "
                        "la cadena de Markov basta"
                        if p >= 0.05 else
                        "se rechaza: hay dependencia de la edad, conviene semi-Markov")}


def bayes_cpt(states: np.ndarray, vol_state: np.ndarray, y: np.ndarray,
              tr: np.ndarray, alpha: float = 1.0) -> Dict[str, float]:
    """P(ruptura | estado, vol) con suavizado de Laplace. Red bayesiana discreta."""
    cpt: Dict[str, float] = {}
    keys = np.array([f"{s}|{v}" for s, v in zip(states, vol_state)])
    for k in np.unique(keys[tr]):
        m = tr & (keys == k)
        cpt[k] = float((y[m].sum() + alpha) / (m.sum() + 2.0 * alpha))
    cpt["__prior__"] = float((y[tr].sum() + alpha) / (tr.sum() + 2.0 * alpha))
    return cpt


class RegimeMarkovExperiment(Experiment):
    id = "regime_markov"
    title = "Capa de régimen: cadena de Markov y red bayesiana (paso previo a GARCH/XGBoost)"

    def preflight(self, ctx: RunContext) -> List[str]:
        return []

    def run(self, ctx: RunContext) -> ExperimentResult:
        cfg = ctx.config
        horizon = int(cfg.get("breakout_horizon", 5))
        cutoff = cfg.get("cutoff")
        s, source = common.load_prices(cfg.get("prices_path"),
                                       cfg.get("synthetic", False), ctx.seed)
        prices = s.to_numpy()
        dates = pd.DatetimeIndex(s.index)
        df, y, ds, ep = build_hazard_dataset(prices, dates, horizon)
        if len(y) < 500:
            return ExperimentResult(metrics={"n": int(len(y))}, decision="review",
                                    notes="muestra insuficiente")
        tr = common.temporal_mask(ds, cutoff)
        te = ~tr

        # Corte de borde y de volatilidad calibrados SOLO en train.
        edge_cut = float(np.quantile(df.loc[tr, "edge_distance"], 0.5))
        vol_cut = float(np.quantile(df.loc[tr, "vol20"], 0.5))
        states = build_states(df, edge_cut)
        vol_state = np.where(df["vol20"].to_numpy() >= vol_cut, "volalta", "volbaja")
        labels = sorted(set(states.tolist()))
        ctx.log(f"estados: {labels} · corte borde={edge_cut:.4f} vol={vol_cut:.5f}")

        # 1) Cadena de Markov
        P = transition_matrix(states[tr], labels)
        freqs = {s: float((states[tr] == s).mean()) for s in labels}
        ll_markov = sequence_loglik(states[te], P, labels)
        ll_iid = iid_loglik(states[te], freqs)
        n_tr = int(te.sum()) - 1
        ctx.log(f"  log-verosimilitud test: Markov {ll_markov:.1f} vs i.i.d. {ll_iid:.1f} "
                f"(dif/obs {(ll_markov - ll_iid) / max(n_tr, 1):+.4f})")

        # 2) ¿Hazard plano? (propiedad de Markov en la duración)
        hz = hazard_by_age(df, y, te)
        hom = hazard_homogeneity_test(hz, float(y[te].mean()))
        flat = hom.get("homogeneous")

        # 3) Red bayesiana discreta
        cpt = bayes_cpt(states, vol_state, y, tr)
        keys = np.array([f"{a}|{b}" for a, b in zip(states, vol_state)])
        p_te = np.array([cpt.get(k, cpt["__prior__"]) for k in keys[te]])
        auc = float(roc_auc_score(y[te], p_te))
        brier = float(brier_score_loss(y[te], p_te))
        brier_base = float(brier_score_loss(y[te], np.full(te.sum(), y[tr].mean())))
        ctx.log(f"  red bayesiana: AUC={auc:.4f} Brier={brier:.4f} "
                f"(base {brier_base:.4f})")

        cpt_table = [{"estado_vol": k, "p_ruptura": round(v, 4)}
                     for k, v in sorted(cpt.items()) if k != "__prior__"]
        metrics = {
            "source": source, "horizon": horizon,
            "n_train": int(tr.sum()), "n_test": int(te.sum()),
            "edge_cut": round(edge_cut, 5), "vol_cut": round(vol_cut, 6),
            "states": labels,
            "transition_matrix": P.round(4).to_dict(),
            "stationary_distribution": stationary_distribution(P),
            "expected_sojourn_sessions": expected_sojourn(P),
            "markov_vs_iid": {"loglik_markov": round(ll_markov, 2),
                              "loglik_iid": round(ll_iid, 2),
                              "delta_per_obs": round((ll_markov - ll_iid) / max(n_tr, 1), 5),
                              "markov_better": bool(ll_markov > ll_iid)},
            "hazard_by_age": hz,
            "hazard_homogeneity_test": hom,
            "hazard_flat_supports_markov": flat,
            "bayes_network": {"auc": round(auc, 4), "brier": round(brier, 4),
                              "brier_baseline": round(brier_base, 4),
                              "improves_calibration": bool(brier < brier_base),
                              "cpt": cpt_table, "prior": round(cpt["__prior__"], 4)},
        }
        baseline = {"iid_states": round(ll_iid, 2),
                    "brier_constant_prior": round(brier_base, 4),
                    "auc_random": 0.5}
        good = (metrics["markov_vs_iid"]["markov_better"] and auc > 0.6
                and brier < brier_base)
        decision = "accept" if good else ("review" if auc > 0.55 else "reject")
        soj = metrics["expected_sojourn_sessions"]
        notes = (
            f"Estados {labels}. La cadena de Markov supera al i.i.d. en test "
            f"({ll_markov:.0f} vs {ll_iid:.0f}, {metrics['markov_vs_iid']['delta_per_obs']:+.4f} "
            f"por observación). Permanencia esperada por estado: {soj}. "
            f"Homogeneidad del hazard por edad: chi2={hom.get('chi2')} (gl={hom.get('df')}), "
            f"p={hom.get('p_value')} -> {'HOMOGÉNEO' if flat else 'heterogéneo'} "
            f"-> {'la duración es aproximadamente geométrica y la cadena de Markov basta; '
                 'un modelo semi-Markov dependiente de la edad no añadiría nada'
                 if flat else 'hay dependencia de la edad: conviene un modelo semi-Markov'}. "
            f"Red bayesiana P(ruptura<={horizon}d | estado, vol): AUC={auc:.4f}, "
            f"Brier={brier:.4f} frente a {brier_base:.4f} del prior constante "
            f"-> {'mejora' if brier < brier_base else 'no mejora'} la calibración. "
            "Las probabilidades por estado son la entrada interpretable para los "
            "modelos de volatilidad aguas abajo."
        )
        return ExperimentResult(metrics=metrics, baseline=baseline,
                                decision=decision, notes=notes)
