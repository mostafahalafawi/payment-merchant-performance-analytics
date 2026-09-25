# Business Insights - Payment & Merchant Performance Analytics

> **Synthetic data.** Falak Payments is fictional and every number below comes from generated data.
> The point is the analytical method: each insight was derived from the pipeline outputs, not written in advance.

**Workflow:** generate → validate & model → calculate KPIs → run 17 SQL queries + Python analysis → read the results → write insights.
Each insight is split into **FACT** (a number produced by the pipeline, with its source file), **INTERPRETATION** (an analyst's
judgement) and **RECOMMENDATION**. Paths are relative to `reports/`. Fiscal year runs July to June (FY2026 = Jul-2025 to Jun-2026).

---

## 1. Growth is strong but slowing, and the slowdown comes from four large merchants

**FACT**
* FY2026 figures, with growth vs FY2025 (`sql_results/q01`):
  * GMV **$1.236B, +29.4%**
  * revenue **$21.9M, +28.4%**
  * gross profit **$5.36M, +27.5%**
* Year-on-year GMV growth slowed from **+37.7% (Jul-2025)** to **+19.3% (Jun-2026)** (`kpi_company_month`).
* 37 merchants are "Declining", meaning 3-month GMV is down at least 25% on the prior 3 months. Together they lost **$11.9M**, and four
  Enterprise merchants account for $9.7M of that (82%):
  * Prime Learning: −47%
  * Royal Cafe: −41%
  * Oasis Pharmacy: −37%
  * Urban EdTech: −32%
  (`analysis/merchant_health.csv`)
* Those four merchants are 9.1% of FY2026 GMV. Excluding them, Apr-Jun 2026 GMV growth would be **+33.4%** instead of **+20.8%**.
* Concentration: the top 10 merchants hold **36.6%** of GMV, and the top 10% of merchants hold **76.9%** (HHI 221).

**INTERPRETATION**
The core business is still growing at about a third a year. Headline growth is being pulled down by a few large accounts that are
moving volume away. They decline steadily rather than stopping outright, which is the typical pattern of a merchant shifting
share to a second acquirer. With GMV this concentrated, losing share at a handful of key accounts changes the whole trend.

**RECOMMENDATION**
Start a key-account retention program for the top 25 merchants: quarterly business reviews, dedicated routing and success-rate
reporting, and a pricing review before renewal. Monitor the 3-month GMV trend of every key account weekly, using the
`merchant_health` output.

---

## 2. GMV is not profit: Enterprise brings 63% of volume but 44% of gross profit

**FACT** (`sql_results/q03`, FY2026)

| Segment | GMV share | GP share | GP margin | GP per $ of GMV | GMV growth |
|---|---:|---:|---:|---:|---:|
| Enterprise | 63% | 43.5% | 17.3% | 30 bps | +25.0% |
| B2B | 17% | 9.3% | 24.7% | 24 bps | +39.4% |
| Online | 14% | 33.1% | 38.2% | 99 bps | +37.5% |
| SME | 6% | 14.1% | 43.7% | 109 bps | +34.5% |

**INTERPRETATION**
Every dollar of Online or SME volume earns 3-4 times more gross profit than a dollar of Enterprise volume. The fastest-growing
segments are also the most profitable, so the mix is improving. That improvement is hidden when the business is managed only on GMV.

**RECOMMENDATION**
Report GP per $ of GMV next to GMV in every sales review, and set targets on gross profit rather than volume alone. Point
acquisition spend at Online and SME merchants, where each merchant earns a far higher margin.

---

## 3. Nine contracts are priced below processing cost, and repricing them is worth about $284K a year

**FACT**
* **12 merchants** made negative gross profit in FY2026: **−$72K GP on $81M GMV** (`analysis/negative_gp_merchants.csv`).
  * 9 are contracts priced below processing cost: 8 Enterprise and 1 B2B.
  * The other 3 are caused by billing leakage (insight 4).
* The largest is **Oasis Connect**, a top-10 merchant by GMV: $27.0M GMV and **−$29K GP (−7.1% margin)**.
* By segment and method, Enterprise **BNPL runs at −21.9% GP margin**, and BNPL on GW-ATLAS at 0.7% (`sql_results/q11`, `q12`).
* Card processed on **GW-ATLAS earns an 11.4% margin**, against 25.3% on GW-NIMBUS and 26.3% on GW-ORION (`q12`).
* Repricing the 9 below-cost contracts to a 15% GP margin on the same volume adds **$284K of GP**, about 5.3% of FY2026 GP
  (`analysis_results.json → profitability`).

**INTERPRETATION**
Negotiated Enterprise pricing was set without a cost floor. It is thinnest where processing is most expensive: BNPL, and card
payments routed through the international acquirer. High volume does not make these contracts profitable. It scales the loss.

**RECOMMENDATION**
1. Introduce a deal-desk rule: minimum contract MDR = processing cost for the merchant's method mix plus a 15% margin.
2. Reprice the 9 contracts at renewal.
3. Where the market allows, route card volume from GW-ATLAS to GW-NIMBUS or GW-ORION.

---

## 4. Billing leakage: 13 merchants are billed about 40% below their contract

**FACT** (`sql_results/q16`)
* Recalculating revenue from contracted pricing (`dim_merchant_pricing`) and comparing it with billed revenue finds **13 merchants
  billed 35-40% below contract**.
* Each discrepancy starts on a specific date and continues every month after. Total leakage is **$52K**, of which $51K is in
  FY2026.
* The largest is Silver Basket (Online, Oman): $25.6K since July 2025.
* 3 of the 12 negative-GP merchants would be profitable if billed correctly.

**INTERPRETATION**
A sudden, persistent drop to the same ~60% of contract across unrelated merchants points to a pricing-configuration error in
the billing system, not to renegotiation. It continues until someone reconciles billed revenue against the contract.

**RECOMMENDATION**
Run the expected-vs-billed reconciliation (`DQ-B01`, `q16`) every month as a control. Correct the 13 pricing configurations and
raise arrears invoices where contracts allow. Require a second approval for any pricing change in the billing system.

---

## 5. A two-week gateway incident cost an estimated $1.2M of GMV and was detected automatically

**FACT** (`analysis/gateway_incidents.csv`)
* From **12 to 25 October 2025**, GW-ORION card success fell to **73.4%**, against a 91.7% trailing baseline. Tokenized payments on
  the same gateway fell to 78.5%, against 96.6%.
* That is about **62.9K extra failed payments**.
* Assuming half of customers retry successfully, the estimated loss is **~$1.17M GMV** and **~$23K revenue**.
* GW-ORION gateway-timeout failures rose **+335%** year on year (`sql_results/q14`).
* The robust anomaly detector (median/MAD, trailing 28 days) flagged 14 consecutive days. The other 44 flags were isolated one-day
  blips.

**INTERPRETATION**
The incident was sustained, confined to one gateway, and showed up as timeouts. That points to an infrastructure problem at the
gateway, not a change in issuer behavior. Routing did not fail over, so merchants on GW-ORION absorbed the full impact for two weeks.

**RECOMMENDATION**
1. Add real-time success-rate monitoring per gateway and method, alerting when the robust z-score stays at or below −4 for 2
   hours or more.
2. Set up automatic failover routing from GW-ORION to GW-NIMBUS for card and token payments.
3. Claim SLA credits for October 2025.

---

## 6. A slow wallet degradation is costing more each month, and daily anomaly detection cannot see it

**FACT**
* The mobile-wallet success rate on GW-NILE fell from **87.7% to 81.9% in six months**, a slope of **−1.17pp per month**
  (`analysis/gateway_degradation.csv`, `sql_results/q13`).
* GW-NILE gateway-timeout failures rose **+101%** year on year (`q14`).
* Company success rate slipped from **91.41% (FY2025) to 90.77% (FY2026)** (`q01`).
* The daily anomaly detector flagged no sustained GW-NILE wallet incident. Only the trend test caught it.

**INTERPRETATION**
Gradual degradation stays under daily alert thresholds because each day looks like the one before. Mobile wallet is an
Egypt-heavy method ($73M FY2026 GMV), so every lost point of success rate is lost volume in the fastest-growing large market.

**RECOMMENDATION**
Monitor on two timescales: sudden breaks (daily robust z-score) and slow drift (6-month slope). Escalate the GW-NILE wallet trend
with the provider now. Keep a second wallet processor as a fallback.

---

## 7. Onboarding: API merchants take 76 days to go live, and a fifth of payment-link merchants never transact

**FACT** (`analysis/activation_by_integration.csv`, `sql_results/q09`; merchants signed Jul-2024 to Mar-2026)

| Integration | Went live | Median days to go-live | Activated within 30 days | Live but never transacted |
|---|---:|---:|---:|---:|
| E-commerce Plugin | 97.2% | 16 | 91.7% | 2.8% |
| POS Terminal | 97.5% | 23 | 88.5% | 9.0% |
| Hosted Checkout | 91.8% | 25.5 | 68.9% | 18.0% |
| Payment Links | 95.3% | 6 | 68.5% | 20.5% |
| Direct API | 74.8% | 76 | 64.2% | 10.6% |

* **150 merchants are live but have never transacted**, and **127 have not gone live**.

**INTERPRETATION**
Two different bottlenecks:
* **Direct API** loses merchants *before* go-live, through long integration projects.
* **Payment Links** loses them *after* go-live: it is easy to switch on but easy to never use.

**RECOMMENDATION**
For API merchants, add an integration-support track with a sandbox checklist and a technical account manager when a project
passes 45 days. For payment-link merchants, run an activation playbook: contact them within 7 days of go-live and help create the
first link. Track "time to first successful transaction" as an onboarding KPI.

---

## 8. The existing merchant base still grows on its own, with net volume retention of about 117%

**FACT** (`sql_results/q17`, `q10`, `q08`)
* The FY2025 to FY2026 GMV bridge:

  | Step | GMV |
  |---|---:|
  | FY2025 GMV | $955.4M |
  | New merchants | +$114.4M |
  | Expansion of existing merchants | +$247.6M |
  | Contraction | −$63.6M |
  | Churn | −$17.2M |
  | **FY2026 GMV** | **$1,236.4M** |

* Net GMV retention of the FY2025 base is **(955.4 + 247.6 − 63.6 − 17.2) / 955.4 ≈ 117%**.
* Merchants that go live stay active: **87.5-94.4%** are still active 12 months after go-live (`q10`).
* 60 merchants churned. They generated $28.2M of GMV in FY2025, and 22 were Online merchants (`q08`).

**INTERPRETATION**
Growth is healthy and mostly comes from existing merchants growing. New merchants add about a third of the net gain. The main
risk is contraction ($63.6M), not churn ($17.2M), which matches insight 1.

**RECOMMENDATION**
Put net GMV retention and contraction on the executive dashboard next to new-merchant GMV. Use the account-manager action list
(`reports/am_action_list.xlsx`, **284 merchants** flagged) as the weekly working list for the commercial team.

---

## 9. By country: Saudi Arabia is the largest, Egypt the fastest large market, Oman the thinnest margin

**FACT** (`sql_results/q02`)

| Country | FY2026 GMV | Share | Growth (USD) | Growth (local currency) | GP margin |
|---|---:|---:|---:|---:|---:|
| Saudi Arabia | $460M | 37.2% | +25.4% | +25.4% | 23.9% |
| UAE | $369M | 29.9% | +22.5% | +22.5% | 26.7% |
| Egypt | $347M | 28.1% | +40.4% | **+45.8%** | 23.5% |
| Oman | $60M | 4.9% | +51.1% | +51.1% | 20.7% |

**INTERPRETATION**
Egypt's growth in local currency is 5.4pp higher than in USD, the gap being the EGP's gradual depreciation. Judged on USD
figures alone, Egypt looks weaker than it is. Oman grows fastest but has the lowest margin, which suggests expansion pricing
that should be reviewed as it scales.

**RECOMMENDATION**
Report both USD and constant-currency growth for Egypt. Review Oman pricing before the next wave of contract renewals.

---

## 10. The cost of payment quality: failed attempts and refunds

**FACT**
* Authorization fees on failed and voided attempts cost **$71K** in FY2026 and earn no revenue (`analysis_results.json`).
* Refund exposure is concentrated in two verticals (`sql_results/q15`, full period):
  * **Travel & Hospitality: 6.2%** refund rate
  * **E-commerce: 4.7%** refund rate, **$14.8M** refunded
* 12 merchants processed at least 300 attempts in the last 3 months with a success rate below 85% (`merchant_health`).

**INTERPRETATION**
Failed payments cost money twice: once in lost volume (insights 5 and 6), and again in fees paid on attempts that earn nothing.
High-refund verticals carry chargeback and fraud risk that GMV figures don't show.

**RECOMMENDATION**
Add "cost of failed attempts" and refund rate to merchant scorecards. Review the risk rules and 3DS settings for the 12
low-success-rate merchants.

---

## Data-quality notes that affect interpretation

* 1,963,217 raw daily rows = **1,948,174 clean + 7,177 quarantined + 7,866 duplicates**. The row counts reconcile exactly
  (`data/processed/dq_report.md`).
* **6 duplicate MIDs** (re-onboarded merchants) were merged into the original merchant records.
* **3 go-live dates** were corrected to the first transaction date, because transactions existed before the recorded go-live.
* Quarantined rows include:
  * 2,942 invalid dates
  * 1,570 impossible statuses
  * 391 rows with revenue greater than GMV
  * 983 unknown MIDs

  None of these rows are in the KPIs above.
