#!/usr/bin/env python3
"""WP-RD1 · Gate 1 v2 — valor de alerta para una POSICIÓN LARGA en Brent.

Diseño CONGELADO en docs/PREREGISTRO_WPRD1_ENMIENDA.md (MASTER: posición larga;
B: evaluación por episodio no solapado, curva coste-cobertura, punto operativo en
validación, calendario como baseline, a igual tasa de falsas alarmas, cooldown,
bootstrap por bloques). v1 (`wprd1_gate1.py`) queda como exploratorio.

Estricto con sesgos:
- Perspectiva larga: evento = caída acumulada a 10 sesiones por debajo del peor
  decil estimado SOLO en FIT (fwd < theta).
- Señal as-of (<= t); featurizador de supervivencia y logística ajustados SOLO en FIT.
- Episodios NO solapados (fusión de excedencias separadas < 10 sesiones).
- Umbral de alerta calibrado SOLO en VALIDACIÓN a una tasa de falsas alarmas
  objetivo; se aplica a TEST. Nada se calibra con cuantiles de test.
- Cooldown de 10 sesiones (una alerta por racimo).
- Comparación a IGUAL tasa de falsas alarmas; recall por episodio; IC pareado por
  bloques; nulo aleatorio.
"""
from __future__ import annotations
import os, sys, json
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "code", "applications"))
sys.path.insert(0, os.path.join(ROOT, "code", "part2_channel_survival"))
import common  # noqa
import channel_survival as cs  # noqa
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

FIT_END = pd.Timestamp("2016-12-31")   # ajuste de theta/supervivencia/logística
VAL_END = pd.Timestamp("2020-08-20")   # validación: FIT_END..VAL_END
# test: > VAL_END
H = 10            # horizonte del evento
LEAD = 10         # ventana de aviso [inicio-LEAD, inicio-1]
COOLDOWN = 10     # des-duplicación
MERGE = 10        # fusión de excedencias en episodios
FA_GRID = [5, 10, 20, 40]     # tasas de falsas alarmas/año para la curva
FA_STAR = 20                  # punto operativo primario (a priori)
SEED = 42
rng = np.random.default_rng(SEED)


def asof(prices, dates):
    rets = np.diff(np.log(prices))
    vol = common.ewma_vol(rets, 0.94)
    idxs, flags, feats = cs.is_channel_flags(prices)
    band = pd.Series(np.nan, index=np.arange(len(prices)))
    for k, e0 in enumerate(idxs):
        band.loc[e0] = feats[k].get("band_width", np.nan)
    band = band.ffill().to_numpy()[:-1]
    # supervivencia: 1-P(T>H), featurizador ajustado SOLO en FIT
    frag = np.full(len(rets), np.nan)
    try:
        ep = cs.extract_episodes(prices, dates)
        ft = common.SurvivalFeaturizer().fit(ep, str(FIT_END.date()))
        fi, _f, fdf = common.window_features(prices)
        if ft.method != "none" and not fdf.empty:
            pk = ft.predict_pk(fdf, H)
            prop = {int(e0): 1.0 - float(pk[k]) for k, e0 in enumerate(fi) if pk[k] == pk[k]}
            s = pd.Series(np.nan, index=np.arange(len(prices)))
            for e0, v in prop.items():
                s.loc[e0] = v
            frag = s.ffill().to_numpy()[:-1]
    except Exception as ex:
        print("surv warn:", str(ex)[:100])
    return rets, vol, band, frag


def episodes(e, lo, hi):
    """Episodios no solapados dentro de [lo,hi): fusiona excedencias < MERGE aparte."""
    starts, last = [], -10**9
    for t in range(lo, hi):
        if e[t] == 1:
            if t - last >= MERGE:
                starts.append(t)
            last = t
    return starts


def gen_alerts(score, lo, hi, thr):
    """Alertas con cooldown dentro de [lo,hi)."""
    a = np.zeros(len(score)); last = -10**9
    for t in range(lo, hi):
        s = score[t]
        if s == s and s >= thr and (t - last) >= COOLDOWN:
            a[t] = 1.0; last = t
    return a


def recall_fa(a, starts, lo, hi):
    """recall de episodios (alerta en [inicio-LEAD,inicio-1]) y falsas alarmas/año."""
    if not starts:
        return np.nan, np.nan, []
    hit = []
    covered_windows = np.zeros(len(a), bool)
    for s0 in starts:
        w0 = max(lo, s0 - LEAD)
        covered_windows[w0:s0] = True
        hit.append(1.0 if a[w0:s0].sum() > 0 else 0.0)
    n_alert = int(a[lo:hi].sum())
    fa = int(a[lo:hi].astype(bool).sum() - (a.astype(bool) & covered_windows)[lo:hi].sum())
    years = max((hi - lo) / 252.0, 1e-9)
    return float(np.mean(hit)), fa / years, hit


def calibrate_thr(score, lo, hi, starts, target_fa):
    """Umbral que da ~target_fa falsas alarmas/año en VALIDACIÓN."""
    s = score[lo:hi]; s = s[~np.isnan(s)]
    if len(s) == 0:
        return np.inf
    best_thr, best_gap = np.inf, 1e9
    for q in np.linspace(0.50, 0.999, 60):
        thr = float(np.quantile(s, q))
        a = gen_alerts(score, lo, hi, thr)
        _, fa, _ = recall_fa(a, starts, lo, hi)
        if fa == fa and abs(fa - target_fa) < best_gap:
            best_gap, best_thr = abs(fa - target_fa), thr
    return best_thr


def main():
    sp, src = common.load_prices(os.path.join(ROOT, "data", "brent_fred_daily.csv"))
    prices = sp.to_numpy(float); dates = pd.DatetimeIndex(sp.index)
    rets, vol, band, frag = asof(prices, dates)
    dr = dates[1:]
    n = len(rets)
    fit = np.asarray(dr <= FIT_END)
    val = np.asarray((dr > FIT_END) & (dr <= VAL_END))
    tes = np.asarray(dr > VAL_END)
    lo_v, hi_v = int(np.argmax(val)), n - int(np.argmax(val[::-1]))
    lo_t, hi_t = int(np.argmax(tes)), n - int(np.argmax(tes[::-1]))

    # evento (perspectiva larga): fwd-10 < peor decil estimado en FIT
    fwd = np.array([rets[t+1:t+1+H].sum() if t < n-H else np.nan for t in range(n)])
    theta = float(np.nanquantile(fwd[fit], 0.10))
    e = (fwd < theta).astype(float); e[np.isnan(fwd)] = 0
    ep_val = episodes(e, lo_v, hi_v)
    ep_tes = episodes(e, lo_t, hi_t)

    # logística (combinación) ajustada SOLO en FIT
    X = np.column_stack([vol, band, frag]); good = ~np.isnan(X).any(1)
    mfit = good & fit
    scaler = StandardScaler().fit(X[mfit])
    clf = LogisticRegression(max_iter=1000, class_weight="balanced").fit(scaler.transform(X[mfit]), e[mfit])
    comb = np.full(n, np.nan); comb[good] = clf.predict_proba(scaler.transform(X[good]))[:, 1]

    scores = {"solo_vol": vol, "regimen": band, "supervivencia": frag, "combinacion": comb}
    # calendario: alerta cada 13 sesiones (baseline operativo válido)
    cal = np.zeros(n); cal[lo_t:hi_t:13] = 1.0

    out = {"source": src, "perspectiva": "posicion larga Brent",
           "fit_end": str(FIT_END.date()), "val_end": str(VAL_END.date()),
           "theta_fit_worst_decile": round(theta, 5), "H": H, "lead": LEAD,
           "cooldown": COOLDOWN, "fa_star_year": FA_STAR,
           "n_episodios_val": len(ep_val), "n_episodios_test": len(ep_tes),
           "n_dias_test": int(tes.sum())}

    # ---- curva coste-cobertura (recall vs FA/año) en TEST, umbral calibrado en VAL ----
    curva = {}
    hits_at_star = {}
    for name, sc in scores.items():
        pts = []
        for fa_t in FA_GRID:
            thr = calibrate_thr(sc, lo_v, hi_v, ep_val, fa_t)
            a = gen_alerts(sc, lo_t, hi_t, thr)
            rec, fa, hit = recall_fa(a, ep_tes, lo_t, hi_t)
            rev = 252 * a[lo_t:hi_t].sum() / max(1, tes.sum())
            pts.append({"fa_objetivo": fa_t, "recall": round(rec, 3),
                        "fa_real": round(fa, 1), "rev_year": round(rev, 1)})
            if fa_t == FA_STAR:
                hits_at_star[name] = hit
        curva[name] = pts
    # calendario como punto de referencia
    rec_c, fa_c, hit_c = recall_fa(cal, ep_tes, lo_t, hi_t)
    rev_c = 252 * cal[lo_t:hi_t].sum() / max(1, tes.sum())
    out["calendario"] = {"recall": round(rec_c, 3), "fa_year": round(fa_c, 1), "rev_year": round(rev_c, 1)}
    hits_at_star["calendario"] = hit_c
    out["curva_coste_cobertura"] = curva

    # ---- nulo aleatorio a la carga de la combinación en FA_STAR ----
    thr = calibrate_thr(comb, lo_v, hi_v, ep_val, FA_STAR)
    a = gen_alerts(comb, lo_t, hi_t, thr); kr = int(a[lo_t:hi_t].sum())
    pos = np.arange(lo_t, hi_t); null_rec = []
    for _ in range(1000):
        aa = np.zeros(n); pick = rng.choice(pos, size=min(kr, len(pos)), replace=False); aa[pick] = 1.0
        null_rec.append(recall_fa(aa, ep_tes, lo_t, hi_t)[0])
    null_rec = np.array([x for x in null_rec if x == x])
    out["nulo_aleatorio_recall"] = {"media": round(float(np.mean(null_rec)), 3),
                                    "p95": round(float(np.percentile(null_rec, 95)), 3)}

    # ---- IC pareado por bloques: combinación - mejor(calendario, solo_vol) en FA_STAR ----
    base = "solo_vol" if np.mean(hits_at_star.get("solo_vol", [0])) >= rec_c else "calendario"
    hc = np.array(hits_at_star["combinacion"]); hb = np.array(hits_at_star[base])
    m = min(len(hc), len(hb)); hc, hb = hc[:m], hb[:m]
    diffs = []; bl = 10
    if m >= bl:
        for _ in range(1000):
            idx = []
            while len(idx) < m:
                s0 = rng.integers(0, m - bl + 1); idx.extend(range(s0, s0 + bl))
            idx = np.array(idx[:m]); diffs.append(hc[idx].mean() - hb[idx].mean())
    diffs = np.array(diffs)
    ic = [round(float(np.percentile(diffs, 2.5)), 3), round(float(np.percentile(diffs, 97.5)), 3)] if diffs.size else [None, None]
    rec_comb = float(hc.mean()); rec_base = float(hb.mean())
    out["en_FA_star"] = {"recall_combinacion": round(rec_comb, 3),
                         "mejor_baseline": base, "recall_baseline": round(rec_base, 3),
                         "delta": round(rec_comb - rec_base, 3), "ic95_bloques": ic}
    out["veredicto"] = {
        "combinacion_bate_baseline": bool(ic[0] is not None and ic[0] > 0),
        "supera_nulo": bool(rec_comb > out["nulo_aleatorio_recall"]["p95"]),
        "lectura": ("Gate 1 PASA: la combinación bate al mejor baseline a igual FA con IC que excluye 0 y supera el nulo."
                    if (ic[0] is not None and ic[0] > 0 and rec_comb > out["nulo_aleatorio_recall"]["p95"])
                    else "Gate 1 NO pasa: la combinación no mejora de forma robusta sobre el mejor baseline a igual tasa de falsas alarmas."),
    }
    od = os.path.join(ROOT, "results", "reports"); os.makedirs(od, exist_ok=True)
    json.dump(out, open(os.path.join(od, "wprd1_gate1_v2.json"), "w"), indent=2, ensure_ascii=False)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
