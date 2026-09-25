"""Render README visuals from pipeline outputs (no hard-coded numbers).

images/dashboard_overview.png     Executive Payment Overview (Power BI page 1 preview)
images/performance_analysis.png   Merchant performance & lifecycle
images/trend_analysis.png         Transaction quality & trends
images/profitability.png          Profitability, pricing and billing leakage
images/data_model.png             Star schema
images/architecture.png           Pipeline architecture

Run:  python python/visuals.py
"""
from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from utils import get_logger, load_config, read_csv_checked  # noqa: E402

log = get_logger("visuals")

S = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
LIGHT = "#9ec5f4"
POS, NEG, TOTAL = "#2a78d6", "#e34948", "#52514e"
GOOD, CRIT = "#0ca30c", "#d03b3b"
PAGE, SURFACE = "#f9f9f7", "#fcfcfb"
INK, INK2, MUTED, GRID, BASE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
CNAME = {"EG": "Egypt", "SA": "Saudi Arabia", "AE": "UAE", "OM": "Oman"}
SEG_COLOR = {"Enterprise": S[0], "SME": S[1], "Online": S[2], "B2B": S[6]}
GW_COLOR = {"GW-ATLAS": S[0], "GW-NIMBUS": S[1], "GW-ORION": S[2], "GW-NILE": S[6]}

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9.5, "axes.edgecolor": BASE, "axes.labelcolor": INK2,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.titlesize": 11, "axes.titleweight": "bold",
    "axes.titlecolor": INK, "axes.titlelocation": "left", "axes.titlepad": 10, "figure.facecolor": PAGE,
    "axes.facecolor": SURFACE, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False, "legend.fontsize": 8.5,
    "savefig.facecolor": PAGE,
})


def usd(x, d=1):
    s = "-" if x < 0 else ""
    x = abs(x)
    if x >= 1e9:
        return f"{s}${x / 1e9:,.{d + 1}f}B"
    if x >= 1e6:
        return f"{s}${x / 1e6:,.{d}f}M"
    return f"{s}${x / 1e3:,.0f}K"


def card(fig, rect, title, value, sub="", sub_color=INK2):
    ax = fig.add_axes(rect)
    ax.set_axis_off()
    ax.add_patch(FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0,rounding_size=0.06", transform=ax.transAxes,
                                fc=SURFACE, ec=GRID, lw=1))
    ax.text(0.07, 0.74, title, fontsize=9, color=INK2, transform=ax.transAxes)
    ax.text(0.07, 0.36, value.replace("$", r"\$"), fontsize=19, color=INK, weight="bold", transform=ax.transAxes)
    ax.text(0.07, 0.12, sub.replace("$", r"\$"), fontsize=8.5, color=sub_color, transform=ax.transAxes)


def header(fig, title, subtitle):
    fig.text(0.02, 0.965, title, fontsize=17, weight="bold", color=INK)
    fig.text(0.02, 0.935, subtitle, fontsize=9.5, color=INK2)
    fig.text(0.98, 0.965, "Falak Payments (fictional) | synthetic data | FY = Jul-Jun", fontsize=8.5, color=MUTED, ha="right")


def footer(fig, text):
    fig.text(0.02, 0.012, text, fontsize=8, color=MUTED)


def mfmt(ax, axis="y", scale=1e6, suffix="M"):
    f = FuncFormatter(lambda v, _: f"{v / scale:,.0f}{suffix}")
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(f)


def waterfall(ax, labels, values, totals):
    run, bottoms, heights, colors = 0.0, [], [], []
    for i, v in enumerate(values):
        if i in totals:
            bottoms.append(0), heights.append(v), colors.append(TOTAL)
            run = v
        else:
            bottoms.append(run if v >= 0 else run + v), heights.append(abs(v)), colors.append(POS if v >= 0 else NEG)
            run += v
    x = np.arange(len(values))
    ax.bar(x, heights, bottom=bottoms, color=colors, width=0.62, edgecolor=SURFACE, linewidth=2)
    for i, v in enumerate(values):
        txt = usd(v) if i in totals else ("+" if v >= 0 else "") + usd(v)
        ax.text(i, bottoms[i] + heights[i] + max(heights) * 0.012, txt, ha="center", va="bottom", fontsize=8.5, color=INK)
    ax.set_xticks(x, labels, fontsize=8.5)
    ax.grid(axis="x", visible=False)


# ---------------------------------------------------------------------------
def dashboard_overview(d, res, path):
    cm, q02, q03, q17 = d["cm"], d["q02"], d["q03"], d["q17"]
    fig = plt.figure(figsize=(16, 9))
    header(fig, "Executive Payment Overview", "Volume, revenue, profitability and payment quality | FY2026 vs FY2025")
    am_last, am_first = res["active_merchants_last_month"], int(cm.loc[cm["month_key"] == cm["month_key"].max() - 100, "active_merchants"].iloc[0])
    cards = [("GMV FY2026", usd(res["gmv_fy26"], 2), f"{res['gmv_growth_pct']:+.1f}% vs FY2025", GOOD),
             ("Revenue FY2026", usd(res["revenue_fy26"]), f"{res['revenue_growth_pct']:+.1f}% | take rate {res['take_rate_fy26_pct']:.2f}%", GOOD),
             ("Gross profit FY2026", usd(res["gp_fy26"]), f"{res['gp_growth_pct']:+.1f}% | margin {res['gp_margin_fy26_pct']:.1f}%", GOOD),
             ("Success rate", f"{res['success_rate_fy26_pct']:.1f}%",
              f"{res['success_rate_fy26_pct'] - res['success_rate_fy25_pct']:+.2f}pp vs FY2025", CRIT),
             ("Active merchants (Jun-26)", f"{am_last}", f"{100 * (am_last / am_first - 1):+.0f}% vs Jun-25", GOOD),
             ("GMV growth, latest month", f"{res['gmv_yoy_last_month_pct']:+.0f}%", f"YoY, down from {res['gmv_yoy_first_month_pct']:+.0f}% in Jul-25", CRIT)]
    for i, c in enumerate(cards):
        card(fig, [0.02 + i * 0.1633, 0.78, 0.153, 0.12], *c)

    ax = fig.add_axes([0.045, 0.40, 0.55, 0.31])
    x = np.arange(len(cm))
    cols = [LIGHT if fy == 2025 else S[0] for fy in cm["fiscal_year"]]
    ax.bar(x, cm["gmv"], color=cols, width=0.72, edgecolor=SURFACE, linewidth=1.5)
    ax.set_xticks(x[::2], [f"{str(m)[:4]}-{str(m)[4:]}" for m in cm["month_key"]][::2], fontsize=8)
    mfmt(ax)
    ax.set_title("Monthly GMV (USD) - light = FY2025, dark = FY2026")
    ax.grid(axis="x", visible=False)
    for i in (11, 23):
        ax.text(i, cm["gmv"].iloc[i] * 1.01, usd(cm["gmv"].iloc[i]), ha="center", va="bottom", fontsize=8, color=INK)

    ax = fig.add_axes([0.66, 0.40, 0.32, 0.31])
    q = q02.sort_values("gmv_fy26_musd")
    y = np.arange(len(q))
    ax.barh(y - 0.18, q["gmv_fy25_musd"], height=0.34, color=LIGHT, label="FY2025", edgecolor=SURFACE)
    ax.barh(y + 0.18, q["gmv_fy26_musd"], height=0.34, color=S[0], label="FY2026", edgecolor=SURFACE)
    for yi, (v, g) in enumerate(zip(q["gmv_fy26_musd"], q["gmv_growth_usd_pct"])):
        ax.text(v + 5, yi + 0.18, f"${v:,.0f}M  ({g:+.0f}%)", va="center", fontsize=8.5, color=INK)
    ax.set_yticks(y, q["country_name"])
    ax.set_xlim(0, q["gmv_fy26_musd"].max() * 1.45)
    ax.set_title("GMV by country ($M, growth vs FY2025)")
    ax.legend(loc="lower right")
    ax.grid(axis="y", visible=False)

    ax = fig.add_axes([0.07, 0.07, 0.38, 0.25])
    q = q03.set_index("segment").loc[["Enterprise", "B2B", "Online", "SME"]]
    gmv_share = 100 * q["gmv_fy26_musd"] / q["gmv_fy26_musd"].sum()
    y = np.arange(len(q))
    ax.barh(y + 0.18, gmv_share, height=0.34, color=S[0], label="Share of GMV", edgecolor=SURFACE)
    ax.barh(y - 0.18, q["gp_share_fy26_pct"], height=0.34, color=S[1], label="Share of gross profit", edgecolor=SURFACE)
    for yi, (a, b, mg) in enumerate(zip(gmv_share, q["gp_share_fy26_pct"], q["gp_margin_fy26_pct"])):
        ax.text(a + 1, yi + 0.18, f"{a:.0f}%", va="center", fontsize=8, color=INK)
        ax.text(b + 1, yi - 0.18, f"{b:.0f}%  (margin {mg:.0f}%)", va="center", fontsize=8, color=INK)
    ax.set_yticks(y, q.index)
    ax.invert_yaxis()
    ax.set_xlim(0, 85)
    ax.set_title("FY2026 segment mix: GMV share vs gross-profit share")
    ax.legend(loc="lower right")
    ax.grid(axis="y", visible=False)

    ax = fig.add_axes([0.53, 0.07, 0.45, 0.25])
    vals = q17.set_index("bridge_step")["gmv_musd"] * 1e6
    labels = ["FY2025\nGMV", "New\nmerchants", "Expansion", "Contraction", "Churned", "FY2026\nGMV"]
    waterfall(ax, labels, list(vals.values), totals={0, 5})
    ax.set_ylim(vals.iloc[0] * 0.6, vals.iloc[-1] * 1.12)
    mfmt(ax)
    ax.set_title("GMV growth bridge FY2025 -> FY2026 (USD)")
    footer(fig, "Preview rendered in Python from kpi_company_month and reports/sql_results (q02, q03, q17). Power BI spec: dashboard/README.md")
    fig.savefig(path, dpi=110)
    plt.close(fig)


def performance_analysis(d, res, path):
    mm, health, act = d["mm"], d["health"], d["act"]
    fig = plt.figure(figsize=(16, 9))
    header(fig, "Merchant Performance & Lifecycle", "Concentration, profitability per merchant, health status and onboarding")

    ax = fig.add_axes([0.05, 0.53, 0.40, 0.34])
    fy = mm[mm["fiscal_year"] == 2026].groupby("merchant_key")["gmv"].sum().sort_values(ascending=False)
    cum = 100 * fy.cumsum() / fy.sum()
    pct = 100 * np.arange(1, len(fy) + 1) / len(fy)
    ax.plot(pct, cum, color=S[0], lw=2)
    c = res["concentration"]["gmv"]
    ax.axvline(10, color=BASE, lw=1, ls="--")
    ax.scatter([10], [c["top10pct_share_pct"]], color=S[0], s=40, zorder=3, edgecolor=SURFACE, linewidth=1.5)
    ax.text(12, c["top10pct_share_pct"] - 6, f"Top 10% of merchants = {c['top10pct_share_pct']:.0f}% of GMV\n"
            f"Top 10 merchants = {c['top10_share_pct']:.0f}% (HHI {c['hhi']:.0f})", fontsize=8.5, color=INK)
    ax.set_xlabel("% of active merchants (ranked by GMV)")
    ax.set_ylabel("Cumulative % of FY2026 GMV")
    ax.set_title("GMV concentration (Pareto)")

    ax = fig.add_axes([0.55, 0.53, 0.43, 0.34])
    g = mm[mm["fiscal_year"] == 2026].groupby(["merchant_key", "segment"], as_index=False)[["gmv", "revenue", "gp"]].sum()
    g = g[(g["gmv"] > 1e4) & (g["revenue"] > 0)]
    g["margin"] = 100 * g["gp"] / g["revenue"]
    for seg in ["Enterprise", "B2B", "Online", "SME"]:
        s = g[g["segment"] == seg]
        ax.scatter(s["gmv"], s["margin"].clip(-40, 70), s=16, color=SEG_COLOR[seg], alpha=0.75, label=seg, lw=0)
    ax.set_xscale("log")
    ax.axhline(0, color=INK, lw=1)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: usd(v, 0)))
    ax.set_xlabel("FY2026 GMV per merchant (log scale)")
    ax.set_ylabel("GP margin % (clipped -40..70)")
    ax.set_title(f"Merchant GMV vs GP margin ({res['profitability']['negative_gp_merchants']} merchants below zero)")
    ax.legend(loc="lower left", ncol=4)

    ax = fig.add_axes([0.13, 0.07, 0.32, 0.34])
    order = ["Growing", "Stable", "Declining", "Dormant", "Churned", "Live - never transacted", "Onboarding (not live)"]
    vc = health["health_status"].value_counts().reindex(order).fillna(0)
    colors = [GOOD, S[0], S[1], S[3], NEG, MUTED, BASE]
    ax.barh(range(len(vc)), vc.values, color=colors, height=0.6, edgecolor=SURFACE)
    for yi, v in enumerate(vc.values):
        ax.text(v + 5, yi, f"{int(v)}", va="center", fontsize=8.5, color=INK)
    ax.set_yticks(range(len(vc)), vc.index)
    ax.invert_yaxis()
    ax.set_title(f"Merchant health as of Jun-2026 ({len(health):,} merchants signed)")
    ax.grid(axis="y", visible=False)

    ax = fig.add_axes([0.55, 0.07, 0.43, 0.34])
    a = act.sort_values("activated_pct")
    y = np.arange(len(a))
    ax.barh(y + 0.18, a["live_pct"], height=0.34, color=LIGHT, label="Went live %", edgecolor=SURFACE)
    ax.barh(y - 0.18, a["activated_pct"], height=0.34, color=S[0], label="Activated within 30 days %", edgecolor=SURFACE)
    for yi, (v, dl) in enumerate(zip(a["activated_pct"], a["median_days_signup_to_live"])):
        ax.text(v + 1, yi - 0.18, f"{v:.0f}%  | {dl:.0f} days to live", va="center", fontsize=8, color=INK)
    ax.set_yticks(y, a["integration_type"])
    ax.set_xlim(0, 135)
    ax.set_title("Onboarding funnel by integration type (signed Jul-24..Mar-26)")
    ax.legend(loc="lower right", fontsize=8)
    ax.grid(axis="y", visible=False)
    footer(fig, "Preview rendered in Python from kpi_merchant_month and reports/analysis (merchant_health, activation_by_integration)")
    fig.savefig(path, dpi=110)
    plt.close(fig)


def trend_analysis(d, res, path):
    gs, q14, cm = d["gsr"], d["q14"], d["cm"]
    fig = plt.figure(figsize=(16, 9))
    header(fig, "Transaction Quality & Trends", "Success rate by gateway, detected incidents, slow degradation and decline reasons")

    ax = fig.add_axes([0.05, 0.53, 0.55, 0.34])
    card_sr = gs[gs["payment_method"] == "CARD"].copy()
    card_sr["date"] = pd.to_datetime(card_sr["date_key"].astype(str))
    for gw, col in GW_COLOR.items():
        s = card_sr[card_sr["gateway"] == gw].set_index("date")["sr"].rolling(3, min_periods=1).mean()
        ax.plot(s.index, 100 * s, color=col, lw=1.4, label=gw)
    inc = [i for i in res["incidents"] if i["payment_method"] == "CARD"]
    for i in inc:
        a, b = pd.to_datetime(i["start"]), pd.to_datetime(i["end"])
        ax.axvspan(a, b, color=NEG, alpha=0.12, lw=0)
        ax.annotate(f"{i['gateway']} incident\n{i['anomalous_days']} days, SR {100 * i['avg_success_rate']:.1f}%\n"
                    f"~{usd(i['est_lost_gmv_usd'])} GMV lost", xy=(b, 100 * i["avg_success_rate"] + 3),
                    xytext=(b + pd.Timedelta(days=40), 80), fontsize=8, color=INK,
                    arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
    ax.set_ylim(70, 96)
    ax.set_ylabel("Card success rate % (3-day avg)")
    ax.set_title("Daily card success rate by gateway (shaded = detected incident)")
    ax.legend(loc="lower left", ncol=4)

    ax = fig.add_axes([0.66, 0.53, 0.32, 0.34])
    w = gs[(gs["gateway"] == "GW-NILE") & (gs["payment_method"] == "WALLET")].copy()
    w["m"] = w["date_key"] // 100
    mw = w.groupby("m")[["success_count", "attempts"]].sum()
    mw["sr"] = 100 * mw["success_count"] / mw["attempts"]
    ax.plot(range(len(mw)), mw["sr"], color=S[6], lw=2, marker="o", ms=3.5)
    ax.set_xticks(range(0, len(mw), 3), [f"{str(m)[:4]}-{str(m)[4:]}" for m in mw.index][::3], fontsize=8)
    deg = res["degradation"][0] if res["degradation"] else None
    if deg:
        ax.text(0.02, 0.08, f"{deg['gateway']} {deg['payment_method']}: {deg['slope_pp_per_month']:+.2f}pp / month\n"
                f"{deg['sr_6m_ago_pct']:.1f}% -> {deg['sr_latest_pct']:.1f}% in 6 months", transform=ax.transAxes,
                fontsize=8.5, color=INK)
    ax.set_ylabel("Success rate %")
    ax.set_title("Slow degradation: Nile Local Switch - Mobile Wallet")

    ax = fig.add_axes([0.05, 0.07, 0.43, 0.34])
    t = q14[q14["decline_reason"] == "Gateway Timeout"].set_index("gateway")
    gws = list(GW_COLOR)
    x = np.arange(len(gws))
    ax.bar(x - 0.18, t.loc[gws, "failed_fy25"] / 1e3, width=0.34, color=LIGHT, label="FY2025", edgecolor=SURFACE)
    ax.bar(x + 0.18, t.loc[gws, "failed_fy26"] / 1e3, width=0.34, color=S[0], label="FY2026", edgecolor=SURFACE)
    for xi, (v, ch) in enumerate(zip(t.loc[gws, "failed_fy26"] / 1e3, t.loc[gws, "yoy_change_pct"])):
        ax.text(xi + 0.18, v + 3, f"{ch:+.0f}%", ha="center", fontsize=8.5, color=INK)
    ax.set_xticks(x, gws)
    ax.set_ylabel("Failed payments (thousands)")
    ax.set_title("Gateway-timeout failures by gateway (YoY change)")
    ax.legend(loc="upper left")
    ax.grid(axis="x", visible=False)

    ax = fig.add_axes([0.55, 0.07, 0.43, 0.34])
    x = np.arange(len(cm))
    ax.plot(x, cm["active_merchants"], color=S[0], lw=2, label="Active merchants")
    ax.bar(x, cm["new_live_merchants"], color=S[2], width=0.6, label="New live merchants", edgecolor=SURFACE)
    ax.set_xticks(x[::3], [f"{str(m)[:4]}-{str(m)[4:]}" for m in cm["month_key"]][::3], fontsize=8)
    ax.set_title("Active merchants and new go-lives per month")
    ax.legend(loc="upper left")
    ax.grid(axis="x", visible=False)
    footer(fig, "Preview rendered in Python from fact_gateway_daily, analysis/gateway_incidents and q14 decline reasons")
    fig.savefig(path, dpi=110)
    plt.close(fig)


def profitability(d, res, path):
    q11, q12, neg, q16 = d["q11"], d["q12"], d["neg"], d["q16"]
    fig = plt.figure(figsize=(16, 9))
    header(fig, "Profitability", "Take rate vs margin, pricing below cost, cost of failures and billing leakage | FY2026")
    p = res["profitability"]
    cards = [("Gross profit FY2026", usd(res["gp_fy26"]), f"margin {res['gp_margin_fy26_pct']:.1f}% of revenue", INK2),
             ("Negative-GP merchants", f"{p['negative_gp_merchants']}", f"{usd(p['negative_gp_total_usd'])} GP on ${p['negative_gp_gmv_musd']:.0f}M GMV", CRIT),
             ("Repricing opportunity", usd(p["repricing_uplift_usd"]), f"{p['below_cost_contracts']} below-cost contracts to 15% margin", GOOD),
             ("Billing leakage", usd(res["billing_leakage_total_usd"]), f"{res['billing_leakage_merchants']} merchants billed ~40% below contract", CRIT),
             ("Cost of failed attempts", usd(res["failed_attempt_cost_fy26"]), "auth fees on failed / voided payments", INK2)]
    for i, c in enumerate(cards):
        card(fig, [0.02 + i * 0.196, 0.78, 0.186, 0.12], *c)

    ax = fig.add_axes([0.05, 0.40, 0.43, 0.30])
    seg = q11.groupby("segment")[["gmv_fy26_musd", "revenue_fy26_kusd"]].sum()
    seg_gp = q11.assign(gp=q11["revenue_fy26_kusd"] * q11["gp_margin_pct"] / 100).groupby("segment")["gp"].sum()
    seg["take"] = 100 * seg["revenue_fy26_kusd"] / 1e3 / seg["gmv_fy26_musd"]
    seg["gp_bps"] = 10 * seg_gp / seg["gmv_fy26_musd"]          # GP ($K) / GMV ($M) x 10 = basis points of GMV
    seg = seg.loc[["Enterprise", "B2B", "Online", "SME"]]
    x = np.arange(len(seg))
    ax.bar(x, seg["gp_bps"], color=[SEG_COLOR[s] for s in seg.index], width=0.55, edgecolor=SURFACE)
    for xi, (v, t) in enumerate(zip(seg["gp_bps"], seg["take"])):
        ax.text(xi, v * 1.02 + 1, f"{v:.0f} bps GP\n(take rate {t:.2f}%)", ha="center", va="bottom", fontsize=8.5, color=INK)
    ax.set_xticks(x, seg.index)
    ax.set_ylim(0, seg["gp_bps"].max() * 1.35)
    ax.set_ylabel("Gross profit per $ of GMV (bps)")
    ax.set_title("Gross profit per $1 of GMV by segment")
    ax.grid(axis="x", visible=False)

    ax = fig.add_axes([0.58, 0.40, 0.40, 0.30])
    q = q12.copy()
    q["label"] = q["payment_method"] + " / " + q["gateway"]
    q = q.sort_values("gp_margin_pct")
    ax.barh(q["label"], q["gp_margin_pct"], color=[NEG if v < 15 else S[0] for v in q["gp_margin_pct"]], height=0.6,
            edgecolor=SURFACE)
    for yi, (v, g) in enumerate(zip(q["gp_margin_pct"], q["gmv_fy26_musd"])):
        ax.text(v + 0.8, yi, f"{v:.1f}%  (${g:.0f}M GMV)", va="center", fontsize=8, color=INK)
    ax.set_xlim(0, q["gp_margin_pct"].max() * 1.45)
    ax.tick_params(axis="y", labelsize=8)
    ax.set_title("GP margin by payment method / gateway (red = below 15%)")
    ax.grid(axis="y", visible=False)

    ax = fig.add_axes([0.14, 0.07, 0.34, 0.24])
    n = neg.sort_values("gp").head(8).iloc[::-1]
    cols = [S[1] if r.startswith("Billing") else NEG for r in n["root_cause"]]
    ax.barh([f"{a} ({b})" for a, b in zip(n["merchant_name"], n["segment"])], n["gp"] / 1e3, color=cols, height=0.6,
            edgecolor=SURFACE)
    ax.axvline(0, color=INK, lw=1)
    ax.set_xlabel("FY2026 gross profit (\\$K)")
    ax.set_title("Largest negative-GP merchants (red = priced below cost, orange = leakage)")
    ax.grid(axis="y", visible=False)

    ax = fig.add_axes([0.62, 0.07, 0.36, 0.24])
    l = q16.head(8).iloc[::-1]
    ax.barh(l["merchant_name"], l["leakage_usd"] / 1e3, color=S[1], height=0.6, edgecolor=SURFACE)
    for yi, (v, s) in enumerate(zip(l["leakage_usd"] / 1e3, l["leakage_since_month"])):
        ax.text(v + 0.3, yi, f"${v:.1f}K since {str(s)[:4]}-{str(s)[4:]}", va="center", fontsize=8, color=INK)
    ax.set_xlim(0, l["leakage_usd"].max() / 1e3 * 1.6)
    ax.set_title("Billing leakage: billed below contracted pricing")
    ax.grid(axis="y", visible=False)
    footer(fig, "Preview rendered in Python from q11, q12, q16 and analysis/negative_gp_merchants")
    fig.savefig(path, dpi=110)
    plt.close(fig)


# ---------------------------------------------------------------------------
def _table(ax, x, y, name, cols, color, w=0.17):
    h = 0.032 * (len(cols) + 1) + 0.01
    ax.add_patch(FancyBboxPatch((x, y - h), w, h, boxstyle="round,pad=0.004,rounding_size=0.008", fc=SURFACE, ec=color, lw=1.6, zorder=2))
    ax.add_patch(FancyBboxPatch((x, y - 0.036), w, 0.036, boxstyle="round,pad=0.004,rounding_size=0.008", fc=color, ec=color, lw=1.6, zorder=2))
    ax.text(x + 0.008, y - 0.019, name, fontsize=9.5, weight="bold", color="white", va="center", zorder=3)
    for i, c in enumerate(cols):
        ax.text(x + 0.008, y - 0.058 - i * 0.032, c, fontsize=8, color=INK if c[:2] in ("PK", "FK") else INK2,
                va="center", weight="bold" if c.startswith("PK") else "normal", zorder=3)
    return (x, y - h, w, h)


def data_model(path):
    fig = plt.figure(figsize=(16, 10))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    fig.text(0.02, 0.965, "Data Model - star schema", fontsize=17, weight="bold", color=INK)
    fig.text(0.02, 0.938, "Daily and monthly payment facts at merchant x method x gateway x status grain, decline reasons, "
             "gateway monitoring table, merchant-month KPI layer", fontsize=9.5, color=INK2)
    D, F, K = S[0], S[1], S[2]
    t = {}
    t["fd"] = _table(ax, 0.40, 0.84, "fact_payments_daily", ["PK date + merchant + method", "     + gateway + status",
                     "FK date_key, merchant_key", "FK payment_method, gateway", "FK status", "txn_count", "gmv_usd, refund_usd",
                     "revenue_usd (billed)", "expected_revenue_usd", "cost_usd (COGS), gp_usd"], F, 0.19)
    t["fm"] = _table(ax, 0.40, 0.43, "fact_payments_monthly", ["PK month + merchant + method", "     + gateway + status",
                     "same measures as daily"], F, 0.19)
    t["fdec"] = _table(ax, 0.63, 0.43, "fact_declines_monthly", ["PK month + merchant + method", "     + gateway + reason",
                       "failed_count"], F, 0.18)
    t["fg"] = _table(ax, 0.17, 0.43, "fact_gateway_daily", ["PK date + gateway + method", "     + country",
                     "success_count, failed_count", "gmv_usd"], F, 0.18)
    t["dd"] = _table(ax, 0.17, 0.86, "dim_date", ["PK date_key", "month_key", "fiscal_year (Jul-Jun)", "fiscal_quarter"], D)
    t["dm"] = _table(ax, 0.63, 0.86, "dim_merchant", ["PK merchant_key", "mid (unique)", "segment, vertical, service",
                     "integration, settlement", "account_manager", "signup / live / first txn", "lifecycle_status, cohort"], D, 0.18)
    t["dpm"] = _table(ax, 0.84, 0.86, "dim_payment_method", ["PK payment_method", "name, default MDR / cost"], D, 0.15)
    t["dgw"] = _table(ax, 0.84, 0.70, "dim_gateway", ["PK gateway", "name, countries", "auth_fee_usd"], D, 0.15)
    t["dst"] = _table(ax, 0.17, 0.66, "dim_status", ["PK status", "counts_in_gmv", "counts_in_success_rate"], D)
    t["dco"] = _table(ax, 0.84, 0.53, "dim_country", ["PK country_code", "name, currency, region"], D, 0.15)
    t["dpr"] = _table(ax, 0.84, 0.36, "dim_merchant_pricing", ["PK merchant + method", "mdr_pct, fixed_fee_usd"], D, 0.15)
    t["kpi"] = _table(ax, 0.40, 0.25, "KPI layer", ["kpi_merchant_month", "kpi_dimension_month", "kpi_company_month",
                      "vw_merchant_month, vw_company_month"], K, 0.19)

    def link(a, b):
        xa, ya, wa, ha = t[a]
        xb, yb, wb, hb = t[b]
        ax.plot([xa + wa / 2, xb + wb / 2], [ya + ha / 2, yb + hb / 2], color=BASE, lw=1.3, zorder=0)

    for dim in ["dd", "dm", "dpm", "dgw", "dst"]:
        link("fd", dim)
    for dim in ["dm", "dd"]:
        link("fm", dim)
        link("fdec", dim)
    link("fg", "dd")
    link("fg", "dgw")
    link("dm", "dco")
    link("dpr", "dm")
    link("kpi", "fm")
    for i, (c, lab) in enumerate([(D, "Dimension"), (F, "Fact"), (K, "KPI / analytical layer")]):
        ax.add_patch(FancyBboxPatch((0.02 + i * 0.14, 0.035), 0.018, 0.018, boxstyle="round,pad=0.002", fc=c, ec=c))
        ax.text(0.045 + i * 0.14, 0.044, lab, fontsize=9, va="center", color=INK2)
    ax.text(0.98, 0.044, "Power BI: dimension -> fact, single direction; country filters via dim_merchant", fontsize=8.5,
            color=MUTED, ha="right", va="center")
    fig.savefig(path, dpi=110)
    plt.close(fig)


def architecture(path):
    fig = plt.figure(figsize=(16, 4.4))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    fig.text(0.02, 0.92, "Pipeline architecture", fontsize=17, weight="bold", color=INK)
    fig.text(0.02, 0.85, "One command (python run_pipeline.py) regenerates every table, KPI, chart and report", fontsize=9.5, color=INK2)
    steps = [("Raw extracts", "switch + billing export\nCRM merchant master\npricing, gateway costs\n~2M daily rows", S[7]),
             ("ETL + validation", "status & date standardisation\n17 DQ rules, MID de-dup\nFX to USD, contract pricing\nrow reconciliation", S[1]),
             ("Star schema", "daily + monthly facts\ndeclines, gateway table\n7 dimensions\nSQLite + CSV", S[0]),
             ("SQL layer", "10 DQ assertions\nKPI views\n17 business queries", S[6]),
             ("KPI engine", "merchant / dimension /\ncompany month KPIs\nreconciled to SQL\n(11 checks)", S[2]),
             ("Analysis", "health scoring, cohorts\ngrowth bridge, incidents\nprofitability, leakage", S[4]),
             ("Outputs", "Power BI (7 pages)\nExcel management pack\nAM action list\ninsights + charts", S[5])]
    w, gap = 0.125, 0.0133
    for i, (title, body, col) in enumerate(steps):
        x = 0.02 + i * (w + gap)
        ax.add_patch(FancyBboxPatch((x, 0.14), w, 0.58, boxstyle="round,pad=0.005,rounding_size=0.015", fc=SURFACE, ec=col, lw=2))
        ax.add_patch(FancyBboxPatch((x, 0.62), w, 0.10, boxstyle="round,pad=0.005,rounding_size=0.015", fc=col, ec=col, lw=2))
        ax.text(x + w / 2, 0.67, title, ha="center", va="center", fontsize=10.5, weight="bold", color="white")
        ax.text(x + w / 2, 0.38, body, ha="center", va="center", fontsize=8.6, color=INK2, linespacing=1.6)
        if i < len(steps) - 1:
            ax.annotate("", xy=(x + w + gap + 0.002, 0.43), xytext=(x + w - 0.002, 0.43), arrowprops=dict(arrowstyle="-|>", color=INK2, lw=1.4))
    ax.text(0.02, 0.05, "Quality gates stop the pipeline: row reconciliation, 8 integrity checks, 10 SQL assertions, "
            "11 Python-vs-SQL reconciliation checks", fontsize=8.5, color=MUTED)
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main():
    cfg = load_config()
    p, rs, an = cfg["paths"]["processed"], cfg["paths"]["reports"] / "sql_results", cfg["paths"]["reports"] / "analysis"
    res = json.loads((cfg["paths"]["reports"] / "analysis_results.json").read_text())
    d = {"cm": read_csv_checked(p / "kpi_company_month.csv"), "mm": read_csv_checked(p / "kpi_merchant_month.csv"),
         "health": read_csv_checked(an / "merchant_health.csv"), "act": read_csv_checked(an / "activation_by_integration.csv"),
         "gsr": read_csv_checked(an / "gateway_daily_sr.csv"), "neg": read_csv_checked(an / "negative_gp_merchants.csv")}
    for q in ["q02_country_contribution", "q03_segment_growth", "q11_gmv_vs_revenue", "q12_profitability_by_method_gateway",
              "q14_decline_reasons", "q16_billing_leakage", "q17_gmv_growth_bridge"]:
        d[q.split("_")[0]] = read_csv_checked(rs / f"{q}.csv")
    img = cfg["paths"]["images"]
    dashboard_overview(d, res, img / "dashboard_overview.png")
    performance_analysis(d, res, img / "performance_analysis.png")
    trend_analysis(d, res, img / "trend_analysis.png")
    profitability(d, res, img / "profitability.png")
    data_model(img / "data_model.png")
    architecture(img / "architecture.png")
    log.info("rendered 6 images to %s", img)


if __name__ == "__main__":
    main()
