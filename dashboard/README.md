# Power BI Dashboard - Build Specification

A 7-page report on `data/processed/` (committed tables only, no need to run Python first). The images in `images/` are
**previews rendered in Python from the same tables**. Replace them with real Power BI screenshots once the `.pbix` exists
(section 5).

* Report file: `dashboard/payment_merchant_performance.pbix` (build from this spec)
* Theme: `dashboard/theme.json` · Measures: `dashboard/dax_measures.md`
* Canvas 16:9 (1280 × 720), page background `#F9F9F7`

## 1. Data model

| Table | Source | Role |
|---|---|---|
| dim_date | `dim_date.csv` | Date table (mark as date table; fiscal year ends 30 June) |
| dim_merchant, dim_payment_method, dim_gateway, dim_status, dim_country | CSV | Dimensions |
| fact_payments_monthly | CSV (~16 MB) | Main fact: month × merchant × method × gateway × status |
| fact_gateway_daily | CSV | Daily success / failed counts per gateway × method × country |
| agg_declines_gateway_month | CSV | Decline reasons per gateway × method × month |
| kpi_merchant_month | CSV | Merchant-month KPI layer (cohort and lifecycle visuals) |
| reports/analysis/merchant_health.csv | CSV | Health status + alert flags (one row per merchant) |
| reports/analysis/cohort_retention.csv, gateway_incidents.csv, negative_gp_merchants.csv | CSV | Helper tables |

**Relationships** (single direction, dimension → fact):

| From (1) | To (*) | Key |
|---|---|---|
| dim_date | fact_payments_monthly, fact_gateway_daily, agg_declines_gateway_month, kpi_merchant_month | date_key |
| dim_merchant | fact_payments_monthly, kpi_merchant_month, merchant_health | merchant_key |
| dim_payment_method | fact_payments_monthly, fact_gateway_daily, agg_declines_gateway_month | payment_method |
| dim_gateway | fact_payments_monthly, fact_gateway_daily, agg_declines_gateway_month | gateway |
| dim_status | fact_payments_monthly | status |
| dim_country | dim_merchant, fact_gateway_daily | country_code |

Country filters payments **through `dim_merchant`**. Don't relate `dim_country` directly to `fact_payments_monthly`, because
that creates an ambiguous path. Sort `dim_date[month_name]` by `fiscal_month_num` so axes start in July.

## 2. Global layout

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Page title  |  [Title Executive]                   Falak Payments | synthetic │
├──────────────────────────────────────────────────────────────────────────────┤
│ Overview · Merchants · Country · Segment & Vertical · Lifecycle · Profit · Quality │
│ Slicers: Fiscal year ▾  Fiscal quarter ▾  Country ▾  Segment ▾  Method ▾  Gateway ▾ │
├──────────────────────────────────────────────────────────────────────────────┤
│                                   page body                                   │
└──────────────────────────────────────────────────────────────────────────────┘
```
Page navigator buttons, slicers synced across pages, and status colors always paired with an icon or text.

## 3. Pages

### Page 1: Executive Payment Overview (`images/dashboard_overview.png`)
| Zone | Visual | Fields |
|---|---|---|
| KPI row | 6 cards | `[GMV]` + `[GMV YoY %]`, `[Revenue]` + `[Take Rate %]`, `[Gross Profit]` + `[GP Margin %]`, `[Success Rate %]` (color `[Status Color Success Rate]`), `[Active Merchants (Period End)]` + `[Merchant Growth %]`, `[GMV YoY %]` latest month |
| Middle left | Column | `dim_date[year_month]` × `[GMV]`, legend `fiscal_year_label` |
| Middle right | Clustered bar | Country × `[GMV]` by fiscal year, data label `[GMV YoY %]` |
| Bottom left | Clustered bar | Segment × share of GMV vs share of GP (`[GMV]`, `[Gross Profit]` shown as % of total) |
| Bottom right | Waterfall | Growth bridge from `reports/sql_results/q17_gmv_growth_bridge.csv` |

### Page 2: Merchant Performance (`images/performance_analysis.png`)
| Zone | Visual | Fields |
|---|---|---|
| Left | Table | Merchant, segment, country, `[GMV]`, `[GMV YoY %]`, `[Revenue]`, `[Gross Profit]`, `[GP Margin %]`, `[Success Rate %]`, `[Merchant GMV Rank]` (data bars on GMV, icons on GP) |
| Right top | Line (Pareto) | Merchant rank × `[Cumulative GMV Share %]`; card `[Top 10 Merchant GMV Share %]` |
| Right bottom | Scatter | X `[GMV]` (log), Y `[GP Margin %]`, legend segment, details merchant |
| Drill-through | `Merchant Profile` page | Monthly GMV / GP / success rate, method mix, decline reasons, health flags |

### Page 3: Country Performance
| Zone | Visual | Fields |
|---|---|---|
| KPI row | Cards per country (small multiples) | `[GMV]`, `[GMV YoY %]`, `[GMV YoY % (Local Currency)]`, `[GP Margin %]` |
| Middle | Line | Month × `[GMV]` by country |
| Bottom | Matrix | Country → segment: `[GMV]`, `[Revenue]`, `[GP Margin %]`, `[Success Rate %]`, `[Country Rank]` |

### Page 4: Segment & Vertical Analysis
| Zone | Visual | Fields |
|---|---|---|
| Left | Clustered column | Segment × `[GMV YoY %]`, `[GP bps of GMV]` (two visuals, one axis each) |
| Right | Treemap | Vertical sized by `[Transactions]`, colored by `[Success Rate %]` |
| Bottom | Table | Vertical: `[Transactions]`, `[GMV]`, `[AOV]`, `[Success Rate %]`, `[Refund Rate %]` |

### Page 5: Merchant Lifecycle
| Zone | Visual | Fields |
|---|---|---|
| KPI row | Cards | `[New Merchants]`, `[Activated Merchants]`, `[Activation Rate %]`, `[Median Days to Go-Live]` |
| Left | Funnel | Signed → Live → Transacted → Activated, by `dim_merchant[integration_type]` slicer |
| Middle | Matrix heatmap | `cohort_retention[cohort]` × `months_since_live`, value `active_share` (sequential blue) |
| Right | Bar | `merchant_health[health_status]` count; drill-through to the account-manager action list |
| Bottom | Line | Month × `[Active Merchants]` + column `[New Merchants]` |

### Page 6: Profitability (`images/profitability.png`)
| Zone | Visual | Fields |
|---|---|---|
| KPI row | Cards | `[Gross Profit]`, `[GP Margin %]`, `[Negative GP Merchants]`, `[Billing Leakage]`, `[Cost of Failed Attempts]` |
| Left | Column | Segment × `[GP bps of GMV]` with `[Take Rate %]` tooltip |
| Right | Matrix | Method × gateway: `[GP Margin %]` (red below 15%), `[GMV]` |
| Bottom | Tables | `negative_gp_merchants.csv` (root cause) and billing leakage (`q16`) |

### Page 7: Transaction Quality (`images/trend_analysis.png`)
| Zone | Visual | Fields |
|---|---|---|
| Top | Line | `dim_date[date]` × `[Daily Success Rate %]` by gateway (method slicer = CARD). Error bars: `[Success Rate 28D Baseline %]` |
| Middle left | Table | `gateway_incidents.csv` filtered to event_type = "Incident" |
| Middle right | Line | Month × `[Success Rate %]` for GW-NILE / WALLET (degradation) |
| Bottom | Stacked column | Gateway × decline reason (`agg_declines_gateway_month`), fiscal-year slicer; card `[Timeout Share %]` |

**Tooltip page** `Merchant Tooltip`: `[GMV]`, `[GMV YoY %]`, `[Gross Profit]`, `[Success Rate %]`, health status.

## 4. Validation before publishing (no filters)

| Measure | FY2025 | FY2026 |
|---|---:|---:|
| `[GMV]` | $955.4M | $1,236.4M |
| `[Revenue]` | $17.04M | $21.88M |
| `[Gross Profit]` | $4.21M | $5.36M |
| `[Success Rate %]` | 91.41% | 90.77% |

These must match `insights/kpi_summary.md`.

## 5. Screenshots for the README (1920 × 1080)

| Page | File |
|---|---|
| 1 Executive Payment Overview | `images/dashboard_overview.png` |
| 2 Merchant Performance (+ Lifecycle) | `images/performance_analysis.png` |
| 7 Transaction Quality | `images/trend_analysis.png` |
| 6 Profitability | `images/profitability.png` |
