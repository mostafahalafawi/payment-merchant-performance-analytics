"""Synthetic data generator for Falak Payments (fictional payment service provider).

Produces the extracts a payments analyst actually receives:
    raw_merchants.csv            onboarding / CRM master (signup, go-live, segment, vertical ...)
    raw_merchant_pricing.csv     contracted pricing per merchant x payment method
    raw_gateway_costs.csv        processing cost per gateway x payment method
    raw_transactions_daily.csv   switch + billing export: date x MID x method x gateway x status
    raw_decline_reasons.csv      monthly failed-transaction reasons
    raw_fx_rates.csv, raw_account_managers.csv

The generator encodes BEHAVIOURS (merchant lifecycle, growth / decline / churn,
seasonality, gateway reliability, pricing, a billing misconfiguration). It does
not encode conclusions: every KPI and insight is computed downstream.

Run:  python python/generate_data.py
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from utils import ensure_dirs, get_logger, load_config

log = get_logger("generate")

# ---------------------------------------------------------------------------
# Static reference data (fictional)
# ---------------------------------------------------------------------------
COUNTRY_W = {"EG": .38, "SA": .30, "AE": .22, "OM": .10}
SEGMENT_W = {"Enterprise": .07, "SME": .48, "Online": .32, "B2B": .13}
VERTICALS = {
    "Enterprise": {"Retail": .25, "Food & Beverage": .15, "Travel & Hospitality": .15, "Telecom & Utilities": .15,
                   "Healthcare": .10, "Education": .10, "E-commerce": .10},
    "SME": {"Retail": .30, "Food & Beverage": .30, "Healthcare": .12, "Education": .10, "Professional Services": .18},
    "Online": {"E-commerce": .45, "Travel & Hospitality": .15, "Education": .12, "Digital Services": .18,
               "Food & Beverage": .10},
    "B2B": {"Distribution & Wholesale": .40, "Logistics": .25, "Professional Services": .20, "Telecom & Utilities": .15},
}
SERVICES = {
    "Enterprise": {"Online Checkout": .40, "POS Acceptance": .40, "Payment Links": .20},
    "SME": {"POS Acceptance": .50, "Payment Links": .35, "Online Checkout": .15},
    "Online": {"Online Checkout": .80, "Subscriptions": .20},
    "B2B": {"B2B Collections": .80, "Payment Links": .20},
}
INTEGRATION = {
    "Online Checkout": {"Direct API": .45, "Hosted Checkout": .35, "E-commerce Plugin": .20},
    "POS Acceptance": {"POS Terminal": 1.0},
    "Payment Links": {"Payment Links": 1.0},
    "Subscriptions": {"Direct API": 1.0},
    "B2B Collections": {"Direct API": .50, "Payment Links": .50},
}
# days from signup to go-live (uniform range) and probability of never going live
TIME_TO_LIVE = {"Payment Links": (2, 10, .05), "E-commerce Plugin": (5, 25, .06), "Hosted Checkout": (10, 40, .07),
                "POS Terminal": (10, 35, .05), "Direct API": (30, 120, .18)}
# mean days from go-live to first successful transaction, probability of never transacting
TIME_TO_FIRST_TXN = {"Payment Links": (12, .26), "E-commerce Plugin": (8, .10), "Hosted Checkout": (7, .07),
                     "POS Terminal": (4, .05), "Direct API": (6, .06)}
SETTLEMENT = {"Enterprise": {"T+1": .6, "T+2": .3, "Weekly": .1}, "SME": {"T+2": .5, "T+1": .3, "Instant": .2},
              "Online": {"T+2": .6, "T+1": .3, "Instant": .1}, "B2B": {"T+1": .5, "Weekly": .5}}
MONTHLY_GMV = {"Enterprise": (650_000, 0.9), "SME": (11_000, 0.9), "Online": (32_000, 1.1), "B2B": (170_000, 0.9)}
COUNTRY_SCALE = {"EG": .55, "SA": 1.30, "AE": 1.20, "OM": .70}
AOV = {"Retail": 35, "Food & Beverage": 14, "Travel & Hospitality": 320, "Telecom & Utilities": 28, "Healthcare": 55,
       "Education": 180, "E-commerce": 48, "Professional Services": 90, "Digital Services": 12,
       "Distribution & Wholesale": 2200, "Logistics": 850}
AOV_COUNTRY = {"EG": .60, "SA": 1.10, "AE": 1.20, "OM": 1.0}
REFUND_RATE = {"Retail": .030, "Food & Beverage": .005, "Travel & Hospitality": .060, "Telecom & Utilities": .008,
               "Healthcare": .010, "Education": .012, "E-commerce": .045, "Professional Services": .008,
               "Digital Services": .020, "Distribution & Wholesale": .004, "Logistics": .006}
BASE_SR = {"CARD": .905, "LDEBIT": .945, "WALLET": .885, "TOKEN": .955, "BNPL": .800, "BANKTR": .975}
SEGMENT_SR = {"Enterprise": .010, "SME": 0.0, "Online": -.020, "B2B": .005}
GATEWAY_SR = {"GW-ATLAS": -.012, "GW-NIMBUS": 0.0, "GW-ORION": .006, "GW-NILE": 0.0}
DECLINE_REASONS = ["Issuer Decline", "Insufficient Funds", "3DS Authentication Failed", "Gateway Timeout",
                   "Risk / Fraud Rule", "Invalid Card / Account Data"]
DECLINE_MIX = {  # probability of each reason by payment method (normal operation)
    "CARD": [.34, .22, .20, .06, .10, .08], "TOKEN": [.40, .25, .05, .08, .12, .10],
    "LDEBIT": [.30, .38, .10, .07, .05, .10], "WALLET": [.20, .35, .15, .15, .05, .10],
    "BNPL": [.05, .10, .05, .05, .70, .05], "BANKTR": [.10, .30, .00, .20, .05, .35],
}
INCIDENT = {"gateway": "GW-ORION", "methods": ["CARD", "TOKEN"], "start": "2025-10-12", "end": "2025-10-26", "sr_drop": .18}
DEGRADATION = {"gateway": "GW-NILE", "method": "WALLET", "start": "2026-01-01", "max_drop": .07}
RAMADAN_MONTHS = {"2025-03": 1.0, "2026-02": 0.4, "2026-03": 0.6}       # share of the month in Ramadan
AM_NAMES = {"EG": ["Hany Soliman", "Nadia Fouad", "Karim Ezzat", "Mai Ragab"],
            "SA": ["Turki Al-Shammari", "Reem Al-Ghamdi", "Omar Al-Anazi"],
            "AE": ["Layla Haddad", "Yousef Al-Marri"], "OM": ["Salim Al-Harthy"]}
NAME_A = ["Nova", "Blue", "Golden", "Crescent", "Palm", "Oasis", "Pearl", "Cedar", "Falcon", "Sand", "Silver",
          "Urban", "Prime", "Bright", "Green", "Royal", "Swift", "Metro", "Coral", "Amber", "Zenith", "Horizon"]
NAME_B = {"Retail": ["Mart", "Stores", "Boutique", "Outlet", "Market"], "Food & Beverage": ["Cafe", "Kitchen", "Bakery", "Grill", "Roastery"],
          "Travel & Hospitality": ["Travel", "Hotels", "Tours", "Stays", "Journeys"], "Telecom & Utilities": ["Connect", "Power", "Telecom", "Utilities", "Net"],
          "Healthcare": ["Clinics", "Pharmacy", "Care", "Medical", "Labs"], "Education": ["Academy", "Learning", "Schools", "Institute", "EdTech"],
          "E-commerce": ["Shop", "Online", "Deals", "Basket", "Cart"], "Professional Services": ["Consulting", "Advisory", "Legal", "Partners", "Services"],
          "Digital Services": ["Apps", "Games", "Streaming", "Cloud", "Digital"], "Distribution & Wholesale": ["Distribution", "Wholesale", "Trading", "Supply", "Traders"],
          "Logistics": ["Logistics", "Freight", "Express", "Cargo", "Movers"]}


def pick(rng, d: dict):
    keys = list(d)
    return keys[int(rng.choice(len(keys), p=np.array(list(d.values())) / sum(d.values())))]


def season(vertical: str, country: str, m: pd.Period) -> float:
    f = 1.0
    mo = m.month
    if vertical in ("Retail", "E-commerce"):
        f *= {11: 1.35 if vertical == "E-commerce" else 1.15, 12: 1.10, 1: .90}.get(mo, 1.0)
    if vertical == "Travel & Hospitality":
        f *= {6: 1.30, 7: 1.40, 8: 1.35, 1: .80, 2: .85}.get(mo, 1.0)
    if vertical == "Education":
        f *= {8: 1.45, 9: 1.55, 1: 1.25, 6: .70, 7: .70}.get(mo, 1.0)
    ram = RAMADAN_MONTHS.get(str(m), 0.0)
    if ram and country in ("SA", "AE", "OM", "EG") and vertical in ("Retail", "Food & Beverage", "E-commerce"):
        f *= 1 + 0.20 * ram
    return f


# ---------------------------------------------------------------------------
def build_fx(cfg, months, rng):
    rows = []
    for i, m in enumerate(months):
        for ccy, r in cfg["fx"]["pegged"].items():
            rows.append((str(m), ccy, r))
        k = i / (len(months) - 1)
        egp = cfg["fx"]["egp_start"] + k * (cfg["fx"]["egp_end"] - cfg["fx"]["egp_start"])
        rows.append((str(m), "EGP", round(egp * (1 + rng.normal(0, cfg["fx"]["egp_noise_pct"])), 4)))
    return pd.DataFrame(rows, columns=["fx_month", "currency", "rate_per_usd"])


def build_merchants(cfg, rng) -> pd.DataFrame:
    start, end = pd.Timestamp(cfg["project"]["start_date"]), pd.Timestamp(cfg["project"]["end_date"])
    rows, used_names = [], set()
    months = pd.period_range(start, end, freq="M")
    # existing base (signed before the window) + monthly new signups with a growing trend
    signups = [(start - pd.Timedelta(days=int(rng.integers(90, 1400)))) for _ in range(560)]
    for i, m in enumerate(months):
        n = rng.poisson(17 + 0.55 * i)
        signups += [m.start_time + pd.Timedelta(days=int(rng.integers(0, m.days_in_month))) for _ in range(n)]
    for idx, sd in enumerate(sorted(signups), start=1):
        c, seg = pick(rng, COUNTRY_W), pick(rng, SEGMENT_W)
        vert, svc = pick(rng, VERTICALS[seg]), pick(rng, SERVICES[seg])
        integ = pick(rng, INTEGRATION[svc])
        lo, hi, p_never = TIME_TO_LIVE[integ]
        live = None if rng.random() < p_never else sd + pd.Timedelta(days=int(rng.integers(lo, hi + 1)))
        if live is not None and live > end:
            live = None
        mean_ft, p_never_txn = TIME_TO_FIRST_TXN[integ]
        first = None
        if live is not None and rng.random() >= p_never_txn:
            first = live + pd.Timedelta(days=int(rng.exponential(mean_ft)))
            if first > end:
                first = None
        for _ in range(50):
            name = f"{rng.choice(NAME_A)} {rng.choice(NAME_B[vert])}"
            if name not in used_names:
                break
            name = f"{name} {idx}"
        used_names.add(name)
        rows.append({"merchant_id": f"M{idx:05d}", "mid": f"{c}{rng.integers(10**8, 10**9)}",
                     "merchant_name": name, "country_code": c, "segment": seg, "vertical": vert, "service": svc,
                     "integration_type": integ, "settlement_type": pick(rng, SETTLEMENT[seg]),
                     "account_manager": str(rng.choice(AM_NAMES[c])), "signup_date": sd.normalize(),
                     "live_date": live.normalize() if live is not None else pd.NaT,
                     "_first_txn": first.normalize() if first is not None else pd.NaT})
    return pd.DataFrame(rows)


def assign_methods(m, rng) -> dict[str, float]:
    """Payment-method mix (share of GMV) for a merchant."""
    c, svc = m["country_code"], m["service"]
    w: dict[str, float] = {}
    if svc == "B2B Collections":
        w = {"BANKTR": .75, "CARD": .25}
    elif svc == "Subscriptions":
        w = {"CARD": .75, "TOKEN": .25}
    elif svc == "POS Acceptance":
        w = {"CARD": .50, "LDEBIT": .30 if c != "AE" else .15, "TOKEN": .15}
        if c == "EG":
            w["WALLET"] = .15
    elif svc == "Payment Links":
        w = {"CARD": .60, "LDEBIT": .20}
        if c == "EG":
            w["WALLET"] = .35
    else:  # Online Checkout
        w = {"CARD": .55, "TOKEN": .15}
        if c in ("SA", "EG", "OM"):
            w["LDEBIT"] = .25 if c == "SA" else .12
        if c == "EG":
            w["WALLET"] = .20
        if c in ("SA", "AE", "EG") and rng.random() < .45:
            w["BNPL"] = .12
    tot = sum(w.values())
    return {k: v / tot for k, v in w.items()}


def route_gateway(country, method, rng) -> str:
    if country == "EG":
        return "GW-NILE" if method in ("LDEBIT", "WALLET", "BANKTR") or rng.random() < .5 else "GW-ATLAS"
    if method == "BNPL":
        return "GW-ATLAS"
    if method in ("LDEBIT", "BANKTR"):
        return "GW-NIMBUS"
    if country == "OM":
        return "GW-NIMBUS" if rng.random() < .6 else "GW-ATLAS"
    u = rng.random()
    return "GW-ORION" if u < .45 else ("GW-NIMBUS" if u < .80 else "GW-ATLAS")


def build_pricing(cfg, merchants, rng):
    pm, seg_mult = cfg["payment_methods"], cfg["segment_price_multiplier"]
    rows, routes = [], []
    for _, m in merchants.iterrows():
        nego = float(np.clip(rng.normal(1.0, .10 if m["segment"] == "Enterprise" else .04), .70, 1.25))
        mix = assign_methods(m, rng)
        for meth, share in mix.items():
            p = pm[meth]
            rows.append({"merchant_id": m["merchant_id"], "payment_method": meth,
                         "mdr_pct": round(p["mdr_pct"] * seg_mult[m["segment"]] * nego, 5),
                         "fixed_fee_usd": round(p["fixed_fee_usd"] * seg_mult[m["segment"]], 3),
                         "effective_from": m["signup_date"].date()})
            routes.append((m["merchant_id"], meth, share, route_gateway(m["country_code"], meth, rng)))
    return pd.DataFrame(rows), pd.DataFrame(routes, columns=["merchant_id", "payment_method", "share", "gateway"])


def build_gateway_costs(cfg):
    rows = []
    for gw, g in cfg["gateways"].items():
        for meth, p in cfg["payment_methods"].items():
            rows.append({"gateway": gw, "gateway_name": g["name"], "payment_method": meth,
                         "cost_pct": round(p["cost_pct"] * g["cost_multiplier"], 5),
                         "cost_fixed_usd": round(p["cost_fixed_usd"] * g["cost_multiplier"], 4),
                         "auth_fee_usd": g["auth_fee_usd"]})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
def simulate_payments(cfg, merchants, pricing, routes, gw_costs, rng):
    start, end = pd.Timestamp(cfg["project"]["start_date"]), pd.Timestamp(cfg["project"]["end_date"])
    days = pd.date_range(start, end, freq="D")
    nd = len(days)
    month_idx = days.to_period("M")
    months = month_idx.unique()
    m_of_day = np.searchsorted(months.to_timestamp(), month_idx.to_timestamp())
    dim = days.days_in_month.to_numpy()
    dow = days.dayofweek.to_numpy()                  # Fri=4, Sat=5 weekend in the region
    weekend = np.isin(dow, [4, 5])
    inc_mask = (days >= INCIDENT["start"]) & (days <= INCIDENT["end"])
    deg_start = pd.Timestamp(DEGRADATION["start"])
    deg = np.clip((days - deg_start).days.to_numpy() / max((end - deg_start).days, 1), 0, 1) * DEGRADATION["max_drop"]

    pr = pricing.set_index(["merchant_id", "payment_method"])
    gc = gw_costs.set_index(["gateway", "payment_method"])
    refund_fee = cfg["refund_fee_usd"]
    frames, decline_rows = [], []
    big_ent = merchants[(merchants["segment"] == "Enterprise") & merchants["_first_txn"].notna()
                        & (merchants["_first_txn"] < start)].sample(3, random_state=int(rng.integers(1e9)))["merchant_id"]
    big_ent = set(big_ent)

    for _, m in merchants[merchants["_first_txn"].notna()].iterrows():
        seg, vert, c = m["segment"], m["vertical"], m["country_code"]
        med, sig = MONTHLY_GMV[seg]
        base_gmv = rng.lognormal(np.log(med * COUNTRY_SCALE[c]), sig)
        if m["merchant_id"] in big_ent:
            base_gmv = max(base_gmv, med * COUNTRY_SCALE[c] * 4.5)
        aov = AOV[vert] * AOV_COUNTRY[c] * (0.8 if seg == "SME" else 1.0) * rng.lognormal(0, .2)
        first = m["_first_txn"]
        # trajectory -----------------------------------------------------------
        u = rng.random()
        age_m = (month_idx - first.to_period("M")).map(lambda x: x.n).to_numpy()   # months since first txn
        traj = np.ones(nd)
        if m["merchant_id"] in big_ent:            # large merchants migrating volume away in FY2026
            s = int(rng.integers(12, 16))
            traj = np.where(m_of_day >= s, np.clip(1 - .07 * (m_of_day - s + 1), .15, 1), 1.0)
        elif u < .25:
            traj = (1 + rng.uniform(.015, .030)) ** np.clip(age_m, 0, None)
        elif u < .40:
            s = int(rng.integers(0, len(months)))
            traj = np.where(m_of_day >= s, (1 - rng.uniform(.03, .06)) ** (m_of_day - s + 1), 1.0)
        elif u < .50:
            s = int(rng.integers(3, len(months)))
            traj = np.where(m_of_day >= s, 0.0, 1.0)      # churn: stops trading
        ramp = np.select([age_m <= 0, age_m == 1, age_m == 2], [.35, .65, .85], 1.0)
        seas = np.array([season(vert, c, p) for p in months])[m_of_day]
        active = (days >= first).astype(float)
        if seg == "SME":
            trade = rng.random(nd) < .75
        elif seg == "B2B":
            trade = (rng.random(nd) < .55) & ~weekend
        else:
            trade = np.ones(nd, bool)
        dow_f = np.where(weekend & (seg != "Online"), .85, 1.0)
        daily_gmv = base_gmv / dim * traj * ramp * seas * active * dow_f * trade
        daily_gmv *= 1 / max(trade.mean(), .3)      # keep monthly GMV comparable when trading intermittently
        merchant_sr_noise = rng.normal(0, .012)

        for _, r in routes[routes["merchant_id"] == m["merchant_id"]].iterrows():
            meth, gw = r["payment_method"], r["gateway"]
            exp_success = daily_gmv * r["share"] / aov
            sr = np.full(nd, BASE_SR[meth] + SEGMENT_SR[seg] + GATEWAY_SR[gw] + merchant_sr_noise)
            if gw == INCIDENT["gateway"] and meth in INCIDENT["methods"]:
                sr = sr - inc_mask * INCIDENT["sr_drop"]
            if gw == DEGRADATION["gateway"] and meth == DEGRADATION["method"]:
                sr = sr - deg
            sr = np.clip(sr + rng.normal(0, .01, nd), .30, .995)
            attempts = rng.poisson(exp_success / sr)
            success = rng.binomial(attempts, sr)
            failed = attempts - success
            voided = rng.binomial(success, .012)
            success = success - voided
            amt = success * aov * np.exp(rng.normal(0, .35 / np.sqrt(np.maximum(success, 1))))
            # refunds: dated 0-20 days after the sale
            rr = REFUND_RATE[vert] * (1.8 if (vert == "Travel & Hospitality" and str(first.year) and False) else 1.0)
            ref_cnt = rng.binomial(success, rr)
            lag = rng.integers(0, 21, nd)
            ref_day = np.minimum(np.arange(nd) + lag, nd - 1)
            ref_amt = ref_cnt * aov * np.exp(rng.normal(0, .3, nd))
            ref_cnt_d = np.bincount(ref_day, weights=ref_cnt, minlength=nd)
            ref_amt_d = np.bincount(ref_day, weights=ref_amt, minlength=nd)

            p = pr.loc[(m["merchant_id"], meth)]
            g = gc.loc[(gw, meth)]
            base = {"merchant_id": m["merchant_id"], "mid": m["mid"], "payment_method": meth, "gateway": gw}
            for status, cnt, amount in [("Success", success, amt), ("Failed", failed, failed * aov),
                                        ("Voided", voided, voided * aov), ("Refunded", ref_cnt_d, ref_amt_d)]:
                nz = cnt > 0
                if not nz.any():
                    continue
                cnt_nz, amt_nz = cnt[nz].astype(int), amount[nz]
                if status == "Success":
                    rev = amt_nz * p["mdr_pct"] + cnt_nz * p["fixed_fee_usd"]
                    cost = amt_nz * g["cost_pct"] + cnt_nz * (g["cost_fixed_usd"] + g["auth_fee_usd"])
                elif status == "Refunded":
                    rev, cost = np.zeros(nz.sum()), cnt_nz * refund_fee
                else:
                    rev, cost = np.zeros(nz.sum()), cnt_nz * g["auth_fee_usd"]
                frames.append(pd.DataFrame({**base, "txn_date": days[nz], "status": status, "txn_count": cnt_nz,
                                            "amount_usd": amt_nz, "revenue_usd": rev, "cost_usd": cost}))
            # monthly decline reasons ---------------------------------------------------
            fm = np.bincount(m_of_day, weights=failed, minlength=len(months))
            fm_inc = np.bincount(m_of_day, weights=failed * inc_mask, minlength=len(months)) \
                if (gw == INCIDENT["gateway"] and meth in INCIDENT["methods"]) else np.zeros(len(months))
            for mi in np.nonzero(fm)[0]:
                normal = int(fm[mi] - fm_inc[mi])
                split = rng.multinomial(normal, DECLINE_MIX[meth]) if normal > 0 else np.zeros(6, int)
                split[3] += int(fm_inc[mi])                     # incident failures are gateway timeouts
                if gw == DEGRADATION["gateway"] and meth == DEGRADATION["method"] and months[mi] >= deg_start.to_period("M"):
                    shift = int(split[1] * .25)                  # degradation shows up as timeouts
                    split[1] -= shift
                    split[3] += shift
                for reason, n in zip(DECLINE_REASONS, split):
                    if n:
                        decline_rows.append((str(months[mi]), m["mid"], meth, gw, reason, int(n)))
    tx = pd.concat(frames, ignore_index=True)
    dec = pd.DataFrame(decline_rows, columns=["txn_month", "mid", "payment_method", "gateway", "decline_reason", "failed_count"])
    return tx, dec, big_ent


# ---------------------------------------------------------------------------
def to_raw(cfg, tx, merchants, fx, rng):
    """Convert to local currency and a switch/billing export layout; apply billing misconfiguration."""
    ccy = merchants.set_index("merchant_id")["country_code"].map(lambda c: cfg["countries"][c]["currency"])
    tx = tx.copy()
    tx["currency"] = tx["merchant_id"].map(ccy)
    fxm = fx.set_index(["fx_month", "currency"])["rate_per_usd"]
    rate = fxm.reindex(pd.MultiIndex.from_arrays([tx["txn_date"].dt.strftime("%Y-%m"), tx["currency"]])).to_numpy()
    # billing misconfiguration: from a given month the billing engine applies ~60% of the contracted MDR
    live = merchants[merchants["_first_txn"].notna() & (merchants["segment"].isin(["SME", "Online"]))]
    under = live.sample(cfg["defects"]["underbilled_merchants"], random_state=int(rng.integers(1e9)))
    under_from = {mid: pd.Timestamp(cfg["project"]["start_date"]) + pd.Timedelta(days=int(rng.integers(120, 600)))
                  for mid in under["merchant_id"]}
    factor = np.ones(len(tx))
    for mid, d0 in under_from.items():
        factor[((tx["merchant_id"] == mid) & (tx["txn_date"] >= d0)).to_numpy()] = 0.6
    billed_rev = tx["revenue_usd"].to_numpy() * factor
    out = pd.DataFrame({
        "txn_date": tx["txn_date"].dt.strftime("%Y-%m-%d"), "mid": tx["mid"], "payment_method": tx["payment_method"],
        "gateway": tx["gateway"], "status": tx["status"], "txn_count": tx["txn_count"],
        "amount_local": (tx["amount_usd"] * rate).round(2), "currency": tx["currency"],
        "revenue_local": (billed_rev * rate).round(2), "cost_local": (tx["cost_usd"] * rate).round(2),
    })
    out["gp_local"] = (out["revenue_local"] - out["cost_local"]).round(2)
    return out, {k: str(v.date()) for k, v in under_from.items()}


def inject_defects(cfg, raw, merchants, rng):
    d, man = cfg["defects"], {}
    raw = raw.copy()

    def idx(rate, mask=None):
        pool = raw.index if mask is None else raw.index[mask]
        return rng.choice(pool, size=max(1, int(len(pool) * rate)), replace=False)

    succ = (raw["status"] == "Success").to_numpy()
    i = idx(d["status_label_variant_rate"])
    variants = {s: v for s, v in cfg["status_map"].items()}
    raw.loc[i, "status"] = [str(rng.choice([x for x in variants[s] if x != s])) for s in raw.loc[i, "status"]]
    man["status_label_variants"] = len(i)
    i = idx(d["unknown_status_rate"])
    raw.loc[i, "status"] = rng.choice(["PENDING_REVIEW", "CHARGEBACK?", "UNKNOWN"], size=len(i))
    man["unknown_status"] = len(i)
    i = idx(d["negative_amount_rate"], succ)
    raw.loc[i, ["amount_local", "revenue_local", "cost_local", "gp_local"]] *= -1
    man["negative_amount"] = len(i)
    i = idx(d["zero_count_rate"], succ)
    raw.loc[i, "txn_count"] = 0
    man["zero_count_with_amount"] = len(i)
    i = idx(d["revenue_gt_gmv_rate"], succ)
    raw.loc[i, "revenue_local"] = (raw.loc[i, "amount_local"] * 1.4).round(2)
    raw.loc[i, "gp_local"] = (raw.loc[i, "revenue_local"] - raw.loc[i, "cost_local"]).round(2)
    man["revenue_gt_gmv"] = len(i)
    i = idx(d["gp_inconsistent_rate"])
    raw.loc[i, "gp_local"] = (raw.loc[i, "gp_local"] + rng.uniform(5, 500, len(i))).round(2)
    man["gp_inconsistent"] = len(i)
    i = idx(d["bad_date_rate"])
    raw.loc[i, "txn_date"] = rng.choice(["2025-13-01", "31/02/2025", "", "N/A", "2025-02-30"], size=len(i))
    man["bad_dates"] = len(i)
    i = idx(0.0005)
    raw.loc[i, "mid"] = [f"XX{rng.integers(10**8, 10**9)}" for _ in i]
    man["unknown_mid"] = len(i)
    i = idx(d["duplicate_row_rate"])
    raw = pd.concat([raw, raw.loc[i]], ignore_index=True)
    man["duplicate_rows"] = len(i)
    raw = raw.sample(frac=1, random_state=int(rng.integers(1e9))).reset_index(drop=True)

    # ---- merchant master defects ------------------------------------------------
    mm = merchants.drop(columns=["_first_txn"]).copy()
    txn_merch = merchants[merchants["_first_txn"].notna()]
    dup_src = txn_merch.sample(d["duplicate_mid_merchants"], random_state=int(rng.integers(1e9)))
    dups = dup_src.drop(columns=["_first_txn"]).copy()
    dups["merchant_id"] = [f"M9{int(x[1:]):04d}" for x in dups["merchant_id"]]
    dups["signup_date"] = dups["signup_date"] + pd.Timedelta(days=200)
    dups["live_date"] = dups["live_date"] + pd.Timedelta(days=200)
    dups["merchant_name"] = dups["merchant_name"] + " (re-onboarded)"
    mm = pd.concat([mm, dups], ignore_index=True)
    man["duplicate_mid_merchants"] = len(dups)
    i = rng.choice(mm.index, int(len(mm) * d["missing_vertical_rate"]), replace=False)
    mm.loc[i, "vertical"] = None
    man["missing_vertical"] = len(i)
    i = rng.choice(mm.index, int(len(mm) * d["missing_country_rate"]), replace=False)
    mm.loc[i, "country_code"] = None
    man["missing_country"] = len(i)
    live_idx = mm.index[mm["live_date"].notna()]
    i = rng.choice(live_idx, d["live_before_signup"], replace=False)
    mm.loc[i, "signup_date"] = mm.loc[i, "live_date"] + pd.Timedelta(days=15)
    man["live_before_signup"] = len(i)
    early = merchants[merchants["_first_txn"] > pd.Timestamp(cfg["project"]["start_date"]) + pd.Timedelta(days=60)]
    late = early.sample(d["txn_before_live_merchants"], random_state=int(rng.integers(1e9)))["merchant_id"]
    mm.loc[mm["merchant_id"].isin(late), "live_date"] = mm.loc[mm["merchant_id"].isin(late), "live_date"] + pd.Timedelta(days=45)
    man["live_date_after_first_txn"] = len(late)
    for col in ("signup_date", "live_date"):
        mm[col] = pd.to_datetime(mm[col]).dt.strftime("%Y-%m-%d")
    return raw, mm, man


def main() -> None:
    cfg = load_config()
    ensure_dirs(cfg)
    rng = np.random.default_rng(cfg["project"]["seed"])
    months = pd.period_range(cfg["project"]["start_date"], cfg["project"]["end_date"], freq="M")
    fx = build_fx(cfg, months, rng)
    merchants = build_merchants(cfg, rng)
    pricing, routes = build_pricing(cfg, merchants, rng)
    gw_costs = build_gateway_costs(cfg)
    log.info("merchants %d (with transactions: %d)", len(merchants), merchants["_first_txn"].notna().sum())
    tx, dec, big_ent = simulate_payments(cfg, merchants, pricing, routes, gw_costs, rng)
    raw_tx, underbilled = to_raw(cfg, tx, merchants, fx, rng)
    raw_tx, raw_merchants, manifest = inject_defects(cfg, raw_tx, merchants, rng)
    manifest["underbilled_merchants"] = underbilled
    manifest["clean_rows"] = int(len(tx))

    ams = pd.DataFrame([{"account_manager": n, "country_code": c} for c, ns in AM_NAMES.items() for n in ns])
    raw_dir = cfg["paths"]["raw"]
    outputs = {"raw_merchants.csv": raw_merchants, "raw_merchant_pricing.csv": pricing, "raw_gateway_costs.csv": gw_costs,
               "raw_transactions_daily.csv": raw_tx, "raw_decline_reasons.csv": dec, "raw_fx_rates.csv": fx,
               "raw_account_managers.csv": ams}
    for name, df in outputs.items():
        df.to_csv(raw_dir / name, index=False)
        log.info("wrote %-28s %9d rows", name, len(df))
    (raw_dir / "_defect_manifest.json").write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
