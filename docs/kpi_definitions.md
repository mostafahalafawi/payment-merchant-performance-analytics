# KPI Definitions

Each KPI is calculated in `python/kpi_engine.py` and independently in SQL (`sql/03_kpi_analysis.sql`). The pipeline
reconciles the two with 11 checks. Power BI uses the same definitions (`dashboard/dax_measures.md`).

## Volume & value

| KPI | Formula | Business meaning |
|---|---|---|
| **GMV** | Σ value of **successful** payments | Money processed for merchants: the volume headline |
| **Net GMV** | GMV − refunds | Volume that stayed processed |
| **Transactions** | Σ successful transaction count | Payment volume in units |
| **AOV** | GMV ÷ successful transactions | Average ticket size; drives fixed-fee economics |
| **GMV growth** | GMV ÷ GMV of the prior period − 1 (MoM, YoY, FY-over-FY) | Momentum |

## Revenue & profitability

| KPI | Formula | Business meaning |
|---|---|---|
| **Revenue** | Σ billed merchant fees (MDR % × value + fixed fee per txn) | What the PSP earns |
| **Expected revenue** | Contracted pricing × actual volume | What the PSP *should* have billed |
| **Billing leakage** | Expected revenue − revenue | Under-billing versus contract |
| **Take rate** | Revenue ÷ GMV | Price realized per $ processed |
| **COGS** | Interchange / scheme / processing cost + authorization fee per attempt (incl. failed & voided) + refund fees | Cost of processing |
| **Cost of failed attempts** | COGS on Failed + Voided rows | Money spent on payments that earn nothing |
| **Gross profit (GP)** | Revenue − COGS | Contribution before overheads |
| **GP margin** | GP ÷ revenue | Profitability of pricing |
| **GP per $ of GMV (bps)** | GP ÷ GMV × 10,000 | Compares profitability across segments with different ticket sizes |
| **Revenue / GP growth** | vs prior period | |

## Payment quality

| KPI | Formula | Business meaning |
|---|---|---|
| **Success rate** | successful ÷ (successful + failed) transactions | Share of attempts that complete; conversion for the merchant |
| **Failure rate** | 1 − success rate | |
| **Refund rate** | Refund value ÷ GMV | Post-sale reversals; chargeback-risk proxy |
| **Decline-reason mix** | failed count by reason ÷ total failed | Root cause of failures (issuer vs gateway vs risk) |

Refunds and voids are excluded from the success-rate denominator, because they are not authorization outcomes.

## Merchant lifecycle

| KPI | Definition |
|---|---|
| **Active merchants** | Merchants with ≥ 1 successful payment in the period (month or fiscal year) |
| **New merchants** | Merchants whose go-live date falls in the period |
| **Activated merchants** | New merchants with a first successful payment within **30 days** of go-live |
| **Merchant growth** | Active merchants ÷ active merchants in the prior period − 1 |
| **Dormant / churned** | No successful payment for > 30 / > 90 days as of period end |
| **Live - never transacted** | Went live, never had a successful payment |
| **Health status** | Growing (3M GMV ≥ +20% vs prior 3M) · Declining (≤ −25%) · Stable; only for merchants with ≥ $3K/month prior GMV |
| **Cohort retention** | Share of a go-live quarter's merchants that are active *k* months after go-live; shown only once every merchant in the cohort has reached month *k* |
| **Net GMV retention** | (Prior-year GMV + expansion − contraction − churn) ÷ prior-year GMV |
| **Time to go-live / to first transaction** | Median days signup → live, live → first success |

## Analytical methods

| Method | Rule (configurable in `config/config.yaml`) |
|---|---|
| **Incident detection** | Daily success rate per gateway × method vs a trailing 28-day **median**. Robust z = 0.6745 × (SR − median) ÷ MAD; anomaly if z ≤ −4 with ≥ 200 attempts. Consecutive days (≤ 3-day gaps) are grouped; ≥ 2 days = Incident, 1 day = blip |
| **Lost GMV (incident)** | Excess failed payments (attempts × baseline SR − successes) × AOV × (1 − 50% retry recovery) |
| **Degradation** | Slope of monthly success rate over the last 6 months ≤ −0.5pp per month |
| **Concentration** | Top-10 and top-10% share of GMV / GP; HHI = Σ share² × 10,000 |
| **Growth bridge** | Merchant-level FY-over-FY GMV classified as new, expansion, contraction or churn |
| **Negative-GP root cause** | "Billing leakage" if GP turns positive when billed at contract, otherwise "priced below cost" |
