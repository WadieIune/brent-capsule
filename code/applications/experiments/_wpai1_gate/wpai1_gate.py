#!/usr/bin/env python3
"""WP-AI1 · gate barato: ¿la estructura de término del riesgo depende del régimen?

Si el riesgo a h días escala distinto en tendencia (canal) que fuera de él,
condicionar el HORIZONTE del motor de cálculo al régimen tiene valor. Se mide el
variance ratio VR(h) = Var(r^(h)) / (h * Var(r^(1))) condicionado al régimen
conocido en t (as-of), con las ventanas forward de h días. VR>1 => el riesgo
compone más rápido que sqrt(h) (autocorrelación positiva, típico de tendencia);
VR<1 => reversión. Nulo por permutación de etiquetas de régimen.
"""
from __future__ import annotations
import os, sys, json
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "code", "applications"))
sys.path.insert(0, os.path.join(ROOT, "code", "part2_channel_survival"))
import common  # noqa
import channel_survival as cs  # noqa

SEED = 42
rng = np.random.default_rng(SEED)
HS = [5, 10, 20]


def daily_regime(prices):
    """Indicador diario as-of: 1 si el día t cierra una ventana clasificada canal."""
    idxs, flags, feats = cs.is_channel_flags(prices)
    reg = pd.Series(np.nan, index=np.arange(len(prices)))
    reg.loc[idxs] = flags
    dir_asc = pd.Series(np.nan, index=np.arange(len(prices)))
    for k, e0 in enumerate(idxs):
        dir_asc.loc[e0] = feats[k].get("dir_asc", np.nan)
    return reg.ffill(), dir_asc.ffill()


def var_ratio(rets, mask, h):
    """VR(h) usando retornos forward de h días que ARRANCAN en días con mask=True."""
    n = len(rets)
    r1 = rets[mask[:n]]
    if len(r1) < 50:
        return np.nan, 0
    v1 = np.var(r1, ddof=1)
    # retorno acumulado forward de h días desde cada t con mask
    idx = np.where(mask[:n - h])[0]
    rh = np.array([rets[t:t + h].sum() for t in idx])
    if len(rh) < 50 or v1 <= 0:
        return np.nan, len(rh)
    vh = np.var(rh, ddof=1)
    return vh / (h * v1), len(rh)


def main():
    s, src = common.load_prices(os.path.join(ROOT, "data", "brent_fred_daily.csv"))
    prices = s.to_numpy(float)
    rets = np.diff(np.log(prices))
    reg, dir_asc = daily_regime(prices)
    reg_r = reg.to_numpy()[1:]          # alinear con retornos (ret t ~ precio t+1)
    trend = (reg_r == 1)
    flat = (reg_r == 0)
    out = {"source": src, "n_rets": int(len(rets)),
           "pct_en_canal": round(float(np.nanmean(trend)), 3)}
    res = {}
    for h in HS:
        vr_tr, n_tr = var_ratio(rets, trend, h)
        vr_fl, n_fl = var_ratio(rets, flat, h)
        vr_all, _ = var_ratio(rets, np.ones(len(rets), bool), h)
        # nulo: permutar etiquetas trend/flat y medir el gap |VR_tr - VR_fl|
        lab = np.where(trend, 1, np.where(flat, 0, -1))
        valid = lab >= 0
        gaps = []
        base_gap = (vr_tr - vr_fl) if (vr_tr == vr_tr and vr_fl == vr_fl) else np.nan
        for _ in range(500):
            perm = lab.copy()
            v = perm[valid]; rng.shuffle(v); perm[valid] = v
            a, _ = var_ratio(rets, perm == 1, h)
            b, _ = var_ratio(rets, perm == 0, h)
            if a == a and b == b:
                gaps.append(a - b)
        gaps = np.array(gaps)
        p = float(np.mean(np.abs(gaps) >= abs(base_gap))) if gaps.size and base_gap == base_gap else np.nan
        res[f"h={h}"] = {
            "VR_global": round(vr_all, 3),
            "VR_tendencia": round(vr_tr, 3), "n_tend": n_tr,
            "VR_fuera": round(vr_fl, 3), "n_fuera": n_fl,
            "gap_tend_menos_fuera": round(base_gap, 3) if base_gap == base_gap else None,
            "escala_correcta_tend_vs_sqrt_h": round(float(np.sqrt(vr_tr)), 3) if vr_tr == vr_tr else None,
            "p_valor_nulo_permutacion": round(p, 3),
        }
    out["resultados"] = res
    # veredicto
    sig = [v for v in res.values() if v["p_valor_nulo_permutacion"] is not None
           and v["p_valor_nulo_permutacion"] < 0.05 and abs(v["gap_tend_menos_fuera"] or 0) > 0.05]
    out["veredicto"] = {
        "gate_pasa": bool(len(sig) >= 1),
        "lectura": ("La estructura de término DIFIERE por régimen en al menos un horizonte "
                    "(gap significativo sobre el nulo): WP-AI1 tiene premisa. "
                    if len(sig) >= 1 else
                    "La estructura de término NO difiere por régimen sobre el nulo: "
                    "WP-AI1 no supera el gate; el horizonte adaptativo por régimen no aporta."),
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
