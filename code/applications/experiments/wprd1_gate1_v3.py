#!/usr/bin/env python3
"""WP-RD1 · Gate 1 v3 — Brent-only, corrige los 4 fallos del challenge de B.

Fallos de v2 corregidos (docs/auditorias/2026-10-06-A-challenge-WPRD1-gate1-v2.md):
  1. PURGA en fronteras: theta/eventos/episodios solo usan ventanas forward
     [t, t+H] contenidas enteras en su región (fit/val/test). No cruzan cortes.
  2. Baseline del contraste PRESELECCIONADO en VALIDACIÓN (no en test); se
     reportan ambos baselines en test.
  3. Comparación a FA EMPAREJADA: curva recall-vs-FA por política e interpolación
     a una FA objetivo fijada a priori; se reporta la carga realizada.
  4. NULO con la MISMA política: cooldown y nº de alertas igual que la señal,
     solo aleatoriza el tiempo; semilla congelada.
v1/v2 se conservan como exploratorios.
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

FIT_END = pd.Timestamp("2016-12-31")
VAL_END = pd.Timestamp("2020-08-20")
H = 10; LEAD = 10; COOLDOWN = 10; MERGE = 10
FA_TARGET = 15.0          # FA/año objetivo, a priori (emparejamiento)
FA_GRID = [5, 8, 12, 15, 20, 30]
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


def region_bounds(mask):
    idx = np.where(mask)[0]
    return int(idx[0]), int(idx[-1]) + 1


def episodes(e, lo, hi):
    """Episodios no solapados en [lo,hi) cuyo evento tiene ventana forward completa."""
    starts, last = [], -10**9
    for t in range(lo, min(hi, len(e))):
        if e[t] == 1 and (t - last) >= MERGE:
            starts.append(t); last = t
        elif e[t] == 1:
            last = t
    return starts


def gen_alerts(score, lo, hi, thr):
    a = np.zeros(len(score)); last = -10**9
    for t in range(lo, hi):
        s = score[t]
        if s == s and s >= thr and (t - last) >= COOLDOWN:
            a[t] = 1.0; last = t
    return a


def gen_calendar(lo, hi, K):
    a = np.zeros(hi); a[lo:hi:K] = 1.0
    return a


def recall_fa(a, starts, lo, hi):
    if not starts:
        return np.nan, np.nan, [], 0
    covered = np.zeros(len(a), bool); hit = []
    for s0 in starts:
        w0 = max(lo, s0 - LEAD); covered[w0:s0] = True
        hit.append(1.0 if a[w0:s0].sum() > 0 else 0.0)
    n_al = int(a[lo:hi].sum())
    fa = n_al - int((a.astype(bool) & covered)[lo:hi].sum())
    years = max((hi - lo) / 252.0, 1e-9)
    return float(np.mean(hit)), fa / years, hit, n_al


def curve_for(score, loR, hiR, epsR, loC, hiC, epsC):
    """Barre umbrales (cuantiles de VAL) y devuelve (fa_test, recall_test, thr, hits)."""
    s = score[loC:hiC]; s = s[~np.isnan(s)]
    pts = []
    if len(s) == 0:
        return pts
    for q in np.linspace(0.50, 0.999, 80):
        thr = float(np.quantile(s, q))
        aT = gen_alerts(score, loR, hiR, thr)
        rec, fa, hit, n = recall_fa(aT, epsR, loR, hiR)
        pts.append((fa, rec, thr, hit))
    return pts


def interp_recall(pts, fa_target):
    """Recall interpolado a fa_target sobre la curva (fa, recall)."""
    xs = np.array([p[0] for p in pts]); ys = np.array([p[1] for p in pts])
    o = np.argsort(xs); xs, ys = xs[o], ys[o]
    if fa_target <= xs.min():
        return float(ys[0])
    if fa_target >= xs.max():
        return float(ys[-1])
    return float(np.interp(fa_target, xs, ys))


def thr_at_fa_val(score, loC, hiC, epsC, fa_target):
    """Umbral (cuantil de val) cuya FA en VALIDACIÓN ~ fa_target."""
    s = score[loC:hiC]; s = s[~np.isnan(s)]
    best, gap = np.inf, 1e9
    for q in np.linspace(0.50, 0.999, 80):
        thr = float(np.quantile(s, q))
        aC = gen_alerts(score, loC, hiC, thr)
        _, fa, _, _ = recall_fa(aC, epsC, loC, hiC)
        if fa == fa and abs(fa - fa_target) < gap:
            gap, best = abs(fa - fa_target), thr
    return best


def main():
    sp, src = common.load_prices(os.path.join(ROOT, "data", "brent_fred_daily.csv"))
    prices = sp.to_numpy(float); dates = pd.DatetimeIndex(sp.index)
    rets, vol, band, frag = asof(prices, dates)
    dr = dates[1:]; n = len(rets)
    fit = np.asarray(dr <= FIT_END); val = np.asarray((dr > FIT_END) & (dr <= VAL_END)); tes = np.asarray(dr > VAL_END)
    lo_f, hi_f = region_bounds(fit); lo_v, hi_v = region_bounds(val); lo_t, hi_t = region_bounds(tes)

    # evento con PURGA: fwd[t] solo si [t, t+H] cae entero en la región de t
    fwd = np.full(n, np.nan)
    for t in range(n - H):
        fwd[t] = rets[t + 1:t + 1 + H].sum()
    def purge(lo, hi):  # índices válidos cuya ventana forward no cruza el corte
        return np.array([t for t in range(lo, hi - H)], dtype=int)
    fit_ok = purge(lo_f, hi_f); val_ok = purge(lo_v, hi_v); tes_ok = purge(lo_t, hi_t)
    theta = float(np.nanquantile(fwd[fit_ok], 0.10))
    e = np.zeros(n)
    for t in np.concatenate([fit_ok, val_ok, tes_ok]):
        if fwd[t] < theta: e[t] = 1.0
    ep_val = episodes(e, lo_v, hi_v - H); ep_tes = episodes(e, lo_t, hi_t - H)

    # logística: fit SOLO en fit purgado
    X = np.column_stack([vol, band, frag]); good = ~np.isnan(X).any(1)
    mfit = good & np.isin(np.arange(n), fit_ok)
    scaler = StandardScaler().fit(X[mfit])
    clf = LogisticRegression(max_iter=1000, class_weight="balanced").fit(scaler.transform(X[mfit]), e[mfit])
    comb = np.full(n, np.nan); comb[good] = clf.predict_proba(scaler.transform(X[good]))[:, 1]
    scores = {"solo_vol": vol, "regimen": band, "supervivencia": frag, "combinacion": comb}

    out = {"source": src, "perspectiva": "posicion larga Brent", "H": H, "lead": LEAD,
           "fit_end": str(FIT_END.date()), "val_end": str(VAL_END.date()),
           "theta_fit_purgado": round(theta, 5), "fa_target": FA_TARGET,
           "n_episodios_val": len(ep_val), "n_episodios_test": len(ep_tes),
           "purga": f">= {H} sesiones en cada frontera"}

    # curva coste-cobertura (test) + recall interpolado a FA_TARGET
    curva = {}; rec_interp = {}; hits_fa = {}
    for name, sc in scores.items():
        pts = curve_for(sc, lo_t, hi_t, ep_tes, lo_v, hi_v, ep_val)
        curva[name] = [{"fa_test": round(p[0], 1), "recall_test": round(p[1], 3)} for p in pts[::16]]
        rec_interp[name] = round(interp_recall(pts, FA_TARGET), 3)
        # operating point: umbral calibrado a FA_TARGET en VAL, aplicado a test
        thr = thr_at_fa_val(sc, lo_v, hi_v, ep_val, FA_TARGET)
        aT = gen_alerts(sc, lo_t, hi_t, thr)
        _, fa_t, hit, n_al = recall_fa(aT, ep_tes, lo_t, hi_t)
        hits_fa[name] = (hit, fa_t, n_al)

    # calendario: cadencia calibrada en VAL a FA_TARGET
    bestK, gap = 13, 1e9
    for K in range(5, 41):
        aC = gen_calendar(lo_v, hi_v, K)
        _, fa, _, _ = recall_fa(aC, ep_val, lo_v, hi_v)
        if abs(fa - FA_TARGET) < gap: gap, bestK = abs(fa - FA_TARGET), K
    aT = gen_calendar(lo_t, hi_t, bestK)
    rec_c, fa_c, hit_c, n_c = recall_fa(aT, ep_tes, lo_t, hi_t)
    rec_interp["calendario"] = round(rec_c, 3); hits_fa["calendario"] = (hit_c, fa_c, n_c)
    out["cadencia_calendario_val"] = bestK

    out["recall_a_FA_target_interp"] = rec_interp
    out["carga_realizada_test_FA_year"] = {k: round(v[1], 1) for k, v in hits_fa.items()}

    # baseline PRESELECCIONADO EN VALIDACIÓN (no en test)
    val_rec = {}
    for name in ("solo_vol", "calendario"):
        if name == "calendario":
            aV = gen_calendar(lo_v, hi_v, bestK); val_rec[name] = recall_fa(aV, ep_val, lo_v, hi_v)[0]
        else:
            thr = thr_at_fa_val(scores[name], lo_v, hi_v, ep_val, FA_TARGET)
            aV = gen_alerts(scores[name], lo_v, hi_v, thr); val_rec[name] = recall_fa(aV, ep_val, lo_v, hi_v)[0]
    base = max(val_rec, key=val_rec.get)
    out["baseline_preseleccionado_en_val"] = {"elegido": base, "recall_val": {k: round(v, 3) for k, v in val_rec.items()}}

    # IC pareado por bloques: combinación - baseline (en el operating point val-calibrado)
    hc = np.array(hits_fa["combinacion"][0]); hb = np.array(hits_fa[base][0])
    m = min(len(hc), len(hb)); hc, hb = hc[:m], hb[:m]; diffs = []; bl = 10
    if m >= bl:
        for _ in range(2000):
            idx = []
            while len(idx) < m:
                s0 = rng.integers(0, m - bl + 1); idx.extend(range(s0, s0 + bl))
            idx = np.array(idx[:m]); diffs.append(hc[idx].mean() - hb[idx].mean())
    diffs = np.array(diffs)
    ic = [round(float(np.percentile(diffs, 2.5)), 3), round(float(np.percentile(diffs, 97.5)), 3)] if diffs.size else [None, None]

    # NULO con misma política: nº de alertas y cooldown de la combinación, tiempo aleatorio
    n_al = hits_fa["combinacion"][2]
    null_rec = []
    for _ in range(1000):
        a = np.zeros(n); placed = 0; last = -10**9; order = rng.permutation(np.arange(lo_t, hi_t))
        for t in order:
            if (abs(t - last) >= COOLDOWN):
                pass  # colocación con cooldown respecto a las ya puestas
        # colocación secuencial respetando cooldown
        a = np.zeros(n); chosen = []; cand = list(rng.permutation(np.arange(lo_t, hi_t)))
        for t in cand:
            if placed >= n_al: break
            if all(abs(t - c) >= COOLDOWN for c in chosen):
                chosen.append(t); placed += 1
        for t in chosen: a[t] = 1.0
        null_rec.append(recall_fa(a, ep_tes, lo_t, hi_t)[0])
    null_rec = np.array([x for x in null_rec if x == x])
    out["nulo_mismo_cooldown_n_alertas"] = {"media": round(float(np.mean(null_rec)), 3),
                                            "p95": round(float(np.percentile(null_rec, 95)), 3),
                                            "n_alertas": int(n_al)}

    rec_comb = float(hc.mean()); rec_base = float(hb.mean())
    out["contraste_primario"] = {
        "combinacion_recall_test": round(rec_comb, 3),
        "baseline": base, "baseline_recall_test": round(rec_base, 3),
        "delta": round(rec_comb - rec_base, 3), "ic95_bloques": ic,
        "fa_combinacion": round(hits_fa["combinacion"][1], 1),
        "fa_baseline": round(hits_fa[base][1], 1),
    }
    out["veredicto"] = {
        "combinacion_bate_baseline": bool(ic[0] is not None and ic[0] > 0),
        "supera_nulo": bool(rec_comb > out["nulo_mismo_cooldown_n_alertas"]["p95"]),
        "lectura": ("Gate 1 PASA." if (ic[0] is not None and ic[0] > 0 and rec_comb > out["nulo_mismo_cooldown_n_alertas"]["p95"])
                    else "Gate 1 NO pasa: la combinación no bate al baseline preseleccionado con IC que excluya 0 ni supera el nulo con su misma política."),
    }
    od = os.path.join(ROOT, "results", "reports"); os.makedirs(od, exist_ok=True)
    json.dump(out, open(os.path.join(od, "wprd1_gate1_v3.json"), "w"), indent=2, ensure_ascii=False)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
