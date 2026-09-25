# Data Dictionary

All data is **synthetic**. Money columns are USD unless the name says `local`. The fiscal year runs **July to June**; FY2026 is
Jul-2025 to Jun-2026.

## Raw layer (`data/raw/`, from `generate_data.py`, git-ignored)

| File | Grain | Contents / realism |
|---|---|---|
| `raw_transactions_daily.csv` | date × MID × method × gateway × status | Switch + billing export: `txn_count`, `amount_local`, `revenue_local`, `cost_local`, `gp_local`. Mixed status labels (e.g. CAPTURED, DECLINED); ~0.5% injected defects |
| `raw_merchants.csv` | merchant record | CRM onboarding master: MID, name, country, segment, vertical, service, integration, settlement, account manager, signup and go-live dates. Includes duplicate MIDs and missing values |
| `raw_merchant_pricing.csv` | merchant × method | Contracted MDR % and fixed fee |
| `raw_gateway_costs.csv` | gateway × method | Processing cost %, fixed cost, authorization fee per attempt |
| `raw_decline_reasons.csv` | month × MID × method × gateway × reason | Failed-payment reason codes |
| `raw_fx_rates.csv` | month × currency | Local units per USD |
| `raw_account_managers.csv` | account manager | Market of each account manager (used to impute missing country) |

## Dimensions

### dim_date
| Column | Description |
|---|---|
| date_key | YYYYMMDD, primary key |
| date, year, month_num, month_name, year_month, month_key (YYYYMM) | Calendar |
| fiscal_year / fiscal_year_label | FY ends in June (2026 / "FY2026") |
| fiscal_month_num | Jul = 1 … Jun = 12 |
| fiscal_quarter | Q1 = Jul-Sep |
| weekday_name, is_weekend | Weekend = Friday and Saturday |

### dim_merchant
| Column | Description |
|---|---|
| merchant_key | Surrogate key |
| merchant_id, mid | CRM ID and switch Merchant ID. `mid` is unique after de-duplication |
| merchant_name | Synthetic trade name |
| country_code, segment, vertical, service | Segment: Enterprise, SME, Online or B2B. Service: Online Checkout, POS Acceptance, Payment Links, Subscriptions or B2B Collections |
| integration_type | Direct API, Hosted Checkout, E-commerce Plugin, POS Terminal, Payment Links |
| settlement_type | T+1, T+2, Weekly, Instant |
| account_manager | Owner of the relationship |
| signup_date, live_date, first_txn_date, last_txn_date | Lifecycle milestones (`*_date_key` versions for joins) |
| live_date_corrected | 1 if go-live was moved to the first transaction date (DQ-M06) |
| days_signup_to_live, days_live_to_first_txn | Onboarding durations |
| is_activated | First successful payment within 30 days of go-live |
| lifecycle_status | Onboarding (not live) / Live - never transacted / Active / Dormant (>30 days without a success) / Churned (>90 days) |
| signup_cohort, live_cohort, live_fy, is_new_in_period | Cohort attributes |

### dim_payment_method · dim_gateway · dim_country · dim_status
| Table | Columns |
|---|---|
| dim_payment_method | `payment_method` (CARD, LDEBIT, WALLET, TOKEN, BNPL, BANKTR), name, default MDR and cost % |
| dim_gateway | `gateway` (GW-ATLAS, GW-NIMBUS, GW-ORION, GW-NILE), name, countries served, auth fee |
| dim_country | ISO-2 code, name, currency, region |
| dim_status | `status` (Success, Failed, Refunded, Voided), `counts_in_gmv`, `counts_in_success_rate`, sort order |

### dim_merchant_pricing
`merchant_key`, `payment_method`, `mdr_pct`, `fixed_fee_usd`: the contracted price used to calculate expected revenue.

## Facts

### fact_payments_daily (grain: date × merchant × method × gateway × status; about 1.95M rows, git-ignored)
| Column | Description |
|---|---|
| date_key, month_key, merchant_key, payment_method, gateway, status | Grain |
| txn_count | Number of transactions |
| amount_usd | Transaction value for the status |
| gmv_usd | Value of **successful** payments (0 for other statuses) |
| refund_usd | Value refunded (Refunded rows) |
| revenue_usd | Billed merchant fees (MDR + fixed fee) |
| expected_revenue_usd | Contracted pricing × volume. The gap to `revenue_usd` is billing leakage |
| cost_usd | COGS: interchange / scheme / processing cost + authorization fee per attempt + refund fee |
| gp_usd | revenue − cost |
| currency, amount_local | Source currency |

### fact_payments_monthly (month grain of the same fact; committed, Power BI source)
Same measures as the daily fact, aggregated to month × merchant × method × gateway × status, plus `date_key` (first of month).

### fact_declines_monthly · agg_declines_gateway_month
Failed-payment counts by decline reason: Issuer Decline, Insufficient Funds, 3DS Authentication Failed, Gateway Timeout,
Risk / Fraud Rule, Invalid Card / Account Data. The merchant-level table is git-ignored; the gateway-level aggregate is committed.

### fact_gateway_daily (grain: date × gateway × method × country)
`success_count`, `failed_count`, `gmv_usd`, used for transaction-quality monitoring and incident detection.

## KPI layer (`kpi_engine.py`)

| Table | Grain | Key columns |
|---|---|---|
| kpi_merchant_month | merchant × month | GMV, net GMV, refunds, success / failed / refunded / voided txn, revenue, expected revenue, billing leakage, COGS, cost of failed attempts, GP, GP margin, take rate, AOV, success rate, refund rate, is_active, is_live_month, is_first_txn_month, months_since_live, MoM, rank |
| kpi_dimension_month | dimension × value × month | Same KPIs by country / segment / vertical / method / gateway (long format), with YoY and rank |
| kpi_company_month | month | Company KPIs incl. active, new-live and activated merchants, MoM and YoY for GMV / revenue / GP / active merchants, 3M average, fiscal-YTD |

## Analysis outputs (`reports/analysis/`)
| File | Content |
|---|---|
| merchant_health.csv | Health status + 6 alert flags per merchant, as of the last month |
| cohort_retention.csv | Go-live quarter × months since live, active share (maturity-masked) |
| growth_bridge_segment.csv | New / expansion / contraction / churn by segment |
| gateway_daily_sr.csv, gateway_incidents.csv, gateway_degradation.csv | Transaction-quality monitoring |
| negative_gp_merchants.csv | Loss-making merchants with root cause |
| activation_by_integration.csv | Onboarding funnel and median durations |
| pbi_* helper tables | See `dashboard/README.md` |
