#!/usr/bin/env python3
"""WP-AI2 · gate barato: selección del periodo de estrés por régimen vs por vol.

Para el ES estresado (FRTB) hay que elegir un periodo de estrés. Se comparan
selectores de los N=250 días "más estresados" y el ES de cola que producen:
  - calendario: ventana contigua de 250 d que maximiza el ES (incumbente);
  - vol: los 250 días de mayor volatilidad EWMA;
  - geometría: los 250 días de mayor anchura de canal (band_width);
  - fragilidad: los 250 días de mayor fragilidad (1 - P(T>k), señal de supervivencia).
Si el selector por régimen no bate al de vol y además coincide con él (solape
alto), la geometría es redundante: WP-AI2 no aporta.
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

N = 250          # tamaño del periodo de estrés (~12 meses)
ALPHA = 0.975    # ES 97.5% (FRTB)


def tail_es(rets):
    """ES de cola: media de las peores (1-ALPHA) pérdidas del conjunto."""
    if len(rets) < 20:
        return np.nan
    q = np.quantile(rets, 1 - ALPHA)
    tail = rets[rets <= q]
    return float(-np.mean(tail)) if len(tail) else np.nan


def daily_signal(prices, key):
    idxs, flags, feats = cs.is_channel_flags(prices)
    s = pd.Series(np.nan, index=np.arange(len(prices)))
    for k, e0 in enumerate(idxs):
        s.loc[e0] = feats[k].get(key, np.nan)
    return s.ffill().to_numpy()


def main():
    sp, src = common.load_prices(os.path.join(ROOT, "data", "brent_fred_daily.csv"))
    prices = sp.to_numpy(float)
    dates = pd.DatetimeIndex(sp.index)
    rets = np.diff(np.log(prices))
    n = len(rets)
    vol = common.ewma_vol(rets, 0.94)
    band = daily_signal(prices, "band_width")[1:]
    # fragilidad: usar supervivencia para 1 - P(T>k) por día (horizonte 10)
    try:
        episodes = cs.extract_episodes(prices, dates)
        feat = common.SurvivalFeaturizer().fit(episodes, str(dates[int(len(dates)*0.7)].date()))
        idxs, _f, fdf = common.window_features(prices)
        frag = np.zeros(n)
        if feat.method != "none" and not fdf.empty:
            pk = feat.predict_pk(fdf, 10)
            prop = {int(e0): (1.0 - float(pk[k])) for k, e0 in enumerate(idxs) if pk[k] == pk[k]}
            for t in range(n):
                frag[t] = prop.get(t + 1, 0.0)
    except Exception as e:
        frag = np.full(n, np.nan)

    def top_days(sig):
        s = np.where(np.isnan(sig), -np.inf, sig)
        return set(np.argsort(s)[-N:])

    def es_of(days):
        d = np.array(sorted(days)); d = d[d < n]
        return tail_es(rets[d])

    sel = {"vol": top_days(vol), "geometria_band": top_days(band)}
    if np.isfinite(frag).any():
        sel["fragilidad_superv"] = top_days(frag)

    # calendario: ventana contigua de 250 que maximiza el ES de cola
    best_es, best_t = -1, None
    for t in range(0, n - N, 10):
        e = tail_es(rets[t:t + N])
        if e == e and e > best_es:
            best_es, best_t = e, t
    out = {"source": src, "N": N, "alpha": ALPHA,
           "ES_calendario_max": round(best_es, 5),
           "periodo_calendario": [str(dates[best_t + 1].date()), str(dates[best_t + N].date())]}
    for k, days in sel.items():
        out[f"ES_{k}"] = round(es_of(days), 5)
    # solape (Jaccard) de los selectores de régimen con el de vol
    volset = sel["vol"]
    for k in [x for x in sel if x != "vol"]:
        inter = len(sel[k] & volset); union = len(sel[k] | volset)
        out[f"jaccard_{k}_vs_vol"] = round(inter / union, 3)

    es_vol = out["ES_vol"]
    es_geo = out.get("ES_geometria_band", np.nan)
    es_fr = out.get("ES_fragilidad_superv", np.nan)
    mejor_regimen = max([x for x in (es_geo, es_fr) if x == x], default=np.nan)
    out["veredicto"] = {
        "regimen_bate_a_vol": bool(mejor_regimen > es_vol * 1.02),
        "redundante_con_vol": bool(max(
            [out.get("jaccard_geometria_band_vs_vol", 0),
             out.get("jaccard_fragilidad_superv_vs_vol", 0)]) > 0.5),
        "lectura": ("La selección por régimen produce un ES estresado comparable o menor "
                    "que la de volatilidad; el estrés lo encuentra la vol. WP-AI2 no aporta."
                    if not (mejor_regimen > es_vol * 1.02) else
                    "La selección por régimen produce un ES estresado materialmente mayor: "
                    "WP-AI2 tendría premisa."),
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
