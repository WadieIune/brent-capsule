#!/usr/bin/env python3
"""WP-RD1 multiactivo — run EXPLORATORIO (no confirmatorio).

Cesta larga 1/N de 6 commodities (panel extendido). Misma metodología limpia que
Gate 1 v3 (purga en fronteras, baseline en validación, nulo con política propia,
FA emparejada). Pendiente del freeze de B (representación WTI negativo, agregación
por contribución al riesgo train-only). Etiquetado EXPLORATORIO.
"""
from __future__ import annotations
import os, sys, json
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "code", "applications"))
sys.path.insert(0, os.path.join(ROOT, "code", "part2_channel_survival"))
import common, channel_survival as cs  # noqa
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

ASSETS = ["BRENT", "WTI", "GOLD", "SILVER", "COPPER", "NATGAS"]
FIT_END, VAL_END = pd.Timestamp("2016-12-31"), pd.Timestamp("2020-08-20")
H = LEAD = COOLDOWN = MERGE = 10; FA_TARGET = 15.0; FLOOR = -0.95
rng = np.random.default_rng(42)


def gen_alerts(sc, lo, hi, thr):
    a = np.zeros(len(sc)); last = -10**9
    for t in range(lo, hi):
        s = sc[t]
        if s == s and s >= thr and t - last >= COOLDOWN: a[t] = 1; last = t
    return a
def gen_cal(lo, hi, K):
    a = np.zeros(hi); a[lo:hi:K] = 1; return a
def recall_fa(a, st, lo, hi):
    if not st: return np.nan, np.nan, []
    cov = np.zeros(len(a), bool); hit = []
    for s0 in st:
        w0 = max(lo, s0 - LEAD); cov[w0:s0] = True; hit.append(1.0 if a[w0:s0].sum() > 0 else 0.0)
    fa = int(a[lo:hi].sum()) - int((a.astype(bool) & cov)[lo:hi].sum())
    return float(np.mean(hit)), fa / max((hi - lo) / 252, 1e-9), hit
def episodes(e, lo, hi):
    st, last = [], -10**9
    for t in range(lo, min(hi, len(e))):
        if e[t] == 1 and t - last >= MERGE: st.append(t); last = t
        elif e[t] == 1: last = t
    return st
def thr_val(sc, lo, hi, ep, fa_t):
    s = sc[lo:hi]; s = s[~np.isnan(s)]; best, gap = np.inf, 1e9
    for q in np.linspace(.5, .999, 80):
        thr = float(np.quantile(s, q)); _, fa, _ = recall_fa(gen_alerts(sc, lo, hi, thr), ep, lo, hi)
        if fa == fa and abs(fa - fa_t) < gap: gap, best = abs(fa - fa_t), thr
    return best


def main():
    df = pd.read_csv(os.path.join(ROOT, "data", "panel_extendido_2026-09-09.csv"), parse_dates=["date"])
    df = df[["date"] + ASSETS].dropna().reset_index(drop=True)
    dates = pd.DatetimeIndex(df["date"]); px = df[ASSETS].to_numpy(float)
    # retornos simples por activo con suelo (preserva WTI negativo sin -284%)
    r_assets = np.clip(px[1:] / px[:-1] - 1.0, FLOOR, None)
    # WTI con precio <=0: el cociente no es fiable -> usar suelo ese día
    for j, a in enumerate(ASSETS):
        bad = (px[:-1, j] <= 0) | (px[1:, j] <= 0)
        r_assets[bad, j] = FLOOR
    rp = r_assets.mean(axis=1)                      # retorno de cartera 1/N
    dr = dates[1:]; n = len(rp)
    volp = common.ewma_vol(rp, 0.94)
    # señales de geometría del Brent (band_width, supervivencia) as-of
    bp = df["BRENT"].to_numpy(float)
    idxs, flags, feats = cs.is_channel_flags(bp)
    band = pd.Series(np.nan, index=np.arange(len(bp)))
    for k, e0 in enumerate(idxs): band.loc[e0] = feats[k].get("band_width", np.nan)
    band = band.ffill().to_numpy()[:len(rp)]
    frag = np.full(n, np.nan)
    try:
        ep = cs.extract_episodes(bp, dates); ft = common.SurvivalFeaturizer().fit(ep, str(FIT_END.date()))
        fi, _f, fdf = common.window_features(bp)
        if ft.method != "none" and not fdf.empty:
            pk = ft.predict_pk(fdf, H); prop = {int(e0): 1 - float(pk[k]) for k, e0 in enumerate(fi) if pk[k] == pk[k]}
            s = pd.Series(np.nan, index=np.arange(len(bp)))
            for e0, v in prop.items(): s.loc[e0] = v
            frag = s.ffill().to_numpy()[:len(rp)]
    except Exception as ex: print("surv warn", str(ex)[:80])

    fit = np.asarray(dr <= FIT_END); val = np.asarray((dr > FIT_END) & (dr <= VAL_END)); tes = np.asarray(dr > VAL_END)
    rb = lambda m: (int(np.where(m)[0][0]), int(np.where(m)[0][-1]) + 1)
    lo_f, hi_f = rb(fit); lo_v, hi_v = rb(val); lo_t, hi_t = rb(tes)
    fwd = np.array([rp[t+1:t+1+H].sum() if t < n-H else np.nan for t in range(n)])
    fit_ok = np.arange(lo_f, hi_f - H)
    theta = float(np.nanquantile(fwd[fit_ok], 0.10))
    e = np.zeros(n)
    for t in range(n - H):
        if (lo_f <= t < hi_f - H) or (lo_v <= t < hi_v - H) or (lo_t <= t < hi_t - H):
            if fwd[t] < theta: e[t] = 1
    ep_v, ep_t = episodes(e, lo_v, hi_v - H), episodes(e, lo_t, hi_t - H)

    X = np.column_stack([volp, band, frag]); good = ~np.isnan(X).any(1); mfit = good & (np.arange(n) < hi_f - H) & (np.arange(n) >= lo_f)
    clf = LogisticRegression(max_iter=1000, class_weight="balanced")
    scaler = StandardScaler().fit(X[mfit]); clf.fit(scaler.transform(X[mfit]), e[mfit])
    comb = np.full(n, np.nan); comb[good] = clf.predict_proba(scaler.transform(X[good]))[:, 1]
    scores = {"vol_cartera": volp, "regimen_brent": band, "superv_brent": frag, "combinacion": comb}

    out = {"EXPLORATORIO": True, "cesta": "1/N " + "+".join(ASSETS),
           "fuente": "panel_extendido_2026-09-09.csv", "wti_neg": "suelo -95%/día (provisional)",
           "theta_fit_purgado": round(theta, 5), "n_ep_test": len(ep_t), "fa_target": FA_TARGET}
    res = {}; hits = {}
    for name, sc in scores.items():
        thr = thr_val(sc, lo_v, hi_v, ep_v, FA_TARGET); _, fa, hit = recall_fa(gen_alerts(sc, lo_t, hi_t, thr), ep_t, lo_t, hi_t)
        res[name] = {"recall": round(np.mean(hit), 3), "fa_year": round(fa, 1)}; hits[name] = hit
    bestK, gap = 14, 1e9
    for K in range(5, 41):
        _, fa, _ = recall_fa(gen_cal(lo_v, hi_v, K), ep_v, lo_v, hi_v)
        if abs(fa - FA_TARGET) < gap: gap, bestK = abs(fa - FA_TARGET), K
    rc, fac, hitc = recall_fa(gen_cal(lo_t, hi_t, bestK), ep_t, lo_t, hi_t)
    res["calendario"] = {"recall": round(rc, 3), "fa_year": round(fac, 1)}; hits["calendario"] = hitc
    # baseline preselec en val
    vr = {}
    thr = thr_val(scores["vol_cartera"], lo_v, hi_v, ep_v, FA_TARGET); vr["vol_cartera"] = recall_fa(gen_alerts(scores["vol_cartera"], lo_v, hi_v, thr), ep_v, lo_v, hi_v)[0]
    vr["calendario"] = recall_fa(gen_cal(lo_v, hi_v, bestK), ep_v, lo_v, hi_v)[0]
    base = max(vr, key=vr.get)
    hc, hb = np.array(hits["combinacion"]), np.array(hits[base]); m = min(len(hc), len(hb)); hc, hb = hc[:m], hb[:m]
    diffs = []
    for _ in range(2000):
        idx = []
        while len(idx) < m:
            s0 = rng.integers(0, m - 9); idx.extend(range(s0, s0 + 10))
        idx = np.array(idx[:m]); diffs.append(hc[idx].mean() - hb[idx].mean())
    ic = [round(float(np.percentile(diffs, 2.5)), 3), round(float(np.percentile(diffs, 97.5)), 3)]
    out["resultados"] = res; out["baseline_val"] = base
    out["contraste"] = {"combinacion": round(float(hc.mean()), 3), "baseline": base,
                        "baseline_recall": round(float(hb.mean()), 3), "delta": round(float(hc.mean() - hb.mean()), 3), "ic95": ic}
    out["veredicto_exploratorio"] = ("Señal no bate al baseline" if not (ic[0] and ic[0] > 0) else "Señal mejora (revisar confirmatorio)")
    od = os.path.join(ROOT, "results", "reports"); os.makedirs(od, exist_ok=True)
    json.dump(out, open(os.path.join(od, "wprd1_multi_explor.json"), "w"), indent=2, ensure_ascii=False)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
