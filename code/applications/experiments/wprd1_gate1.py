#!/usr/bin/env python3
"""WP-RD1 · Gate 1 — valor de la alerta (dato REAL, sin simulación).

Pregunta: con el mismo presupuesto de revisiones/año, ¿una política que añade
régimen y supervivencia del canal a un baseline de volatilidad captura antes los
episodios de riesgo material que calendario y solo-vol?

Diseño congelado en docs/PREREGISTRO_WPRD1.md. Estricto con sesgos:
- Señal as-of (<= t); el evento es forward (t+1..t+10), que es lo que se anticipa.
- Umbral del evento y umbrales de alerta estimados SOLO en train (no cuantiles de test).
- Featurizador de supervivencia ajustado SOLO en train.
- Comparadores: calendario, solo-vol, régimen, supervivencia, combinación, nulo.
- Métrica: captura de episodios a presupuesto de revisiones fijado en train;
  IC pareado por bloques; nulo aleatorio de igual frecuencia.
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

CUTOFF = pd.Timestamp("2020-08-20")
H = 10               # horizonte del evento (sesiones)
LEAD = 10            # tolerancia de aviso: alerta en [start-LEAD, start-1]
BUDGET_PER_YEAR = 20 # presupuesto de revisiones/año (fijado a priori)
EMBARGO = 10
SEED = 42
rng = np.random.default_rng(SEED)


def asof_signals(prices, dates):
    rets = np.diff(np.log(prices))
    n = len(rets)
    vol = common.ewma_vol(rets, 0.94)
    rv20 = pd.Series(rets).rolling(20).std().to_numpy()
    # geometría/régimen as-of
    idxs, flags, feats = cs.is_channel_flags(prices)
    reg = pd.Series(np.nan, index=np.arange(len(prices)))
    band = pd.Series(np.nan, index=np.arange(len(prices)))
    age = pd.Series(np.nan, index=np.arange(len(prices)))
    reg.loc[idxs] = flags
    for k, e0 in enumerate(idxs):
        band.loc[e0] = feats[k].get("band_width", np.nan)
        age.loc[e0] = feats[k].get("age", feats[k].get("channel_age", np.nan))
    reg = reg.ffill().to_numpy()[: -1]
    band = band.ffill().to_numpy()[: -1]
    return rets, vol, rv20, reg, band


def survival_fragility(prices, dates, fit_cutoff):
    """1 - P(T>H) por retorno, con featurizador ajustado SOLO en train."""
    n = len(prices) - 1
    frag = np.full(n, np.nan)
    try:
        episodes = cs.extract_episodes(prices, dates)
        feat = common.SurvivalFeaturizer().fit(episodes, str(fit_cutoff.date()))
        idxs, _f, fdf = common.window_features(prices)
        if feat.method != "none" and not fdf.empty:
            pk = feat.predict_pk(fdf, H)
            prop = {int(e0): (1.0 - float(pk[k])) for k, e0 in enumerate(idxs) if pk[k] == pk[k]}
            s = pd.Series(np.nan, index=np.arange(len(prices)))
            for e0, v in prop.items():
                s.loc[e0] = v
            frag = s.ffill().to_numpy()[:-1]
    except Exception as e:
        print("survival warn:", str(e)[:120])
    return frag


def forward_event(rets, theta):
    """e_t = 1 si el retorno acumulado forward de H sesiones < theta."""
    n = len(rets)
    fwd = np.full(n, np.nan)
    for t in range(n - H):
        fwd[t] = rets[t + 1: t + 1 + H].sum()
    return (fwd < theta).astype(float), fwd


def episodes_from_events(e):
    """Agrupa días de evento consecutivos en episodios; devuelve índices de inicio."""
    starts = []
    prev = 0
    for t in range(len(e)):
        if e[t] == 1 and prev == 0:
            starts.append(t)
        prev = e[t] if e[t] == e[t] else 0
    return starts


def alerts_from_score(score, thr):
    a = np.zeros(len(score))
    m = ~np.isnan(score)
    a[m] = (score[m] >= thr).astype(float)
    return a


def thr_for_budget(score_train, budget_frac):
    s = score_train[~np.isnan(score_train)]
    if len(s) == 0:
        return np.inf
    return float(np.quantile(s, 1.0 - budget_frac))


def capture(alerts, starts, lead=LEAD):
    """Fracción de episodios con alerta en [start-lead, start-1]."""
    if not starts:
        return np.nan, []
    hit = []
    for s0 in starts:
        lo = max(0, s0 - lead)
        hit.append(1.0 if alerts[lo:s0].sum() > 0 else 0.0)
    return float(np.mean(hit)), hit


def main():
    sp, src = common.load_prices(os.path.join(ROOT, "data", "brent_fred_daily.csv"))
    prices = sp.to_numpy(float); dates = pd.DatetimeIndex(sp.index)
    rets, vol, rv20, reg, band = asof_signals(prices, dates)
    frag = survival_fragility(prices, dates, CUTOFF)
    dr = dates[1:]                       # fecha del retorno t (cierre t+1)
    tr = np.asarray(dr <= CUTOFF)
    te = np.asarray(dr > CUTOFF)

    # evento: umbral del peor decil estimado SOLO en train
    theta = float(np.nanquantile(np.array([rets[t+1:t+1+H].sum()
                  for t in range(len(rets)-H) if tr[t]]), 0.10))
    e, fwd = forward_event(rets, theta)
    # embargo alrededor del corte
    cut_idx = int(np.argmax(dr > CUTOFF))
    emb = np.ones(len(rets), bool); emb[max(0, cut_idx-EMBARGO):cut_idx+EMBARGO] = False

    budget_frac = BUDGET_PER_YEAR / 252.0

    # ---- scores por política (as-of) ----
    scores = {"solo_vol": vol, "regimen": band, "supervivencia": frag}
    # combinación: logística en train
    X = np.column_stack([vol, band, frag])
    good = ~np.isnan(X).any(1)
    mtr = good & tr & emb & ~np.isnan(e)
    sc = StandardScaler().fit(X[mtr]);
    clf = LogisticRegression(max_iter=1000, class_weight="balanced").fit(sc.transform(X[mtr]), e[mtr])
    comb = np.full(len(rets), np.nan)
    comb[good] = clf.predict_proba(sc.transform(X[good]))[:, 1]
    scores["combinacion"] = comb
    # calendario fijo: alerta cada round(252/budget) sesiones
    step = max(1, round(252 / BUDGET_PER_YEAR))
    cal = np.zeros(len(rets)); cal[::step] = 1.0

    te_idx = te & emb
    starts_te = [s for s in episodes_from_events(np.where(te_idx, e, 0)) ]
    out = {"source": src, "cutoff": str(CUTOFF.date()), "H": H, "lead": LEAD,
           "theta_train_worst_decile": round(theta, 5),
           "budget_rev_year": BUDGET_PER_YEAR,
           "n_test_days": int(te_idx.sum()), "n_episodios_test": len(starts_te)}

    res = {}
    # calendario
    cap_cal, hit_cal = capture(np.where(te_idx, cal, 0), starts_te)
    rev_cal = 252 * cal[te_idx].sum() / max(1, te_idx.sum())
    res["calendario"] = {"captura": round(cap_cal, 3), "rev_year": round(rev_cal, 1)}
    hits = {"calendario": hit_cal}
    # resto por umbral de train
    for name, sco in scores.items():
        thr = thr_for_budget(np.where(tr & emb, sco, np.nan), budget_frac)
        a = alerts_from_score(np.where(te_idx, sco, np.nan), thr)
        cap, hit = capture(a, starts_te)
        rev = 252 * np.nansum(a) / max(1, te_idx.sum())
        prec = (np.nansum(a * e) / max(1, np.nansum(a)))
        res[name] = {"captura": round(cap, 3), "rev_year": round(rev, 1),
                     "precision": round(float(prec), 3)}
        hits[name] = hit

    # nulo aleatorio de igual frecuencia que la combinación
    kr = int(round(res["combinacion"]["rev_year"] / 252 * te_idx.sum()))
    te_positions = np.where(te_idx)[0]
    null_caps = []
    for _ in range(1000):
        a = np.zeros(len(rets));
        pick = rng.choice(te_positions, size=min(kr, len(te_positions)), replace=False)
        a[pick] = 1.0
        null_caps.append(capture(a, starts_te)[0])
    null_caps = np.array([x for x in null_caps if x == x])
    out["nulo_aleatorio"] = {"captura_media": round(float(np.mean(null_caps)), 3),
                             "captura_p95": round(float(np.percentile(null_caps, 95)), 3)}

    # IC pareado por bloques: combinación - mejor(calendario, solo_vol), sobre episodios
    base_best = "solo_vol" if res["solo_vol"]["captura"] >= res["calendario"]["captura"] else "calendario"
    hc = np.array(hits["combinacion"]); hb = np.array(hits[base_best])
    diffs = []
    nep = len(hc); bl = 10
    if nep >= bl:
        for _ in range(1000):
            idx = []
            while len(idx) < nep:
                s = rng.integers(0, nep - bl + 1); idx.extend(range(s, s + bl))
            idx = np.array(idx[:nep])
            diffs.append(hc[idx].mean() - hb[idx].mean())
    diffs = np.array(diffs)
    ic = [round(float(np.percentile(diffs, 2.5)), 3), round(float(np.percentile(diffs, 97.5)), 3)] if diffs.size else [None, None]
    out["resultados"] = res
    out["mejor_baseline"] = base_best
    out["delta_captura_combinacion_vs_baseline"] = round(float(hc.mean() - hb.mean()), 3)
    out["ic95_bloques_delta"] = ic
    bate_vol = res["combinacion"]["captura"] > res["solo_vol"]["captura"]
    out["veredicto"] = {
        "combinacion_bate_a_solo_vol": bool(bate_vol),
        "ic_excluye_cero": bool(ic[0] is not None and ic[0] > 0),
        "supera_nulo": bool(res["combinacion"]["captura"] > out["nulo_aleatorio"]["captura_p95"]),
        "lectura": ("Gate 1 PASA: la combinación mejora la captura sobre solo-vol con IC que excluye 0 y supera el nulo."
                    if (bate_vol and ic[0] is not None and ic[0] > 0) else
                    "Gate 1 NO pasa: la combinación no mejora de forma robusta sobre solo-vol."),
    }
    outdir = os.path.join(ROOT, "results", "reports"); os.makedirs(outdir, exist_ok=True)
    json.dump(out, open(os.path.join(outdir, "wprd1_gate1.json"), "w"), indent=2, ensure_ascii=False)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
