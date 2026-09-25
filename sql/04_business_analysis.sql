-- =============================================================================
-- 04_business_analysis.sql  |  One query per business question
-- -----------------------------------------------------------------------------
-- Each block: "-- name:" + "-- question:". python/database.py executes all of
-- them into reports/sql_results/<name>.csv. Fiscal year = Jul..Jun (FY2026 =
-- Jul-2025..Jun-2026). Depends on views in 03_kpi_analysis.sql.
-- =============================================================================


-- name: q01_executive_kpis_by_fy
-- question: What are total GMV, revenue, gross profit, success/failure rate and merchant counts per fiscal year?
WITH fy AS (
    SELECT fiscal_year,
           SUM(gmv) AS gmv, SUM(net_gmv) AS net_gmv, SUM(refunds) AS refunds, SUM(revenue) AS revenue,
           SUM(cogs) AS cogs, SUM(gp) AS gp, SUM(success_txn) AS success_txn, SUM(failed_txn) AS failed_txn,
           SUM(new_live_merchants) AS new_live_merchants, SUM(activated_merchants) AS activated_merchants,
           AVG(active_merchants) AS avg_monthly_active
      FROM vw_company_month GROUP BY fiscal_year
),
distinct_active AS (
    SELECT fiscal_year, COUNT(DISTINCT merchant_key) AS active_merchants_in_year
      FROM vw_merchant_month WHERE is_active = 1 GROUP BY fiscal_year
)
SELECT 'FY' || f.fiscal_year AS fiscal_year,
       ROUND(f.gmv / 1e6, 2)                                            AS gmv_musd,
       ROUND(f.net_gmv / 1e6, 2)                                        AS net_gmv_musd,
       ROUND(f.revenue / 1e6, 3)                                        AS revenue_musd,
       ROUND(f.cogs / 1e6, 3)                                           AS cogs_musd,
       ROUND(f.gp / 1e6, 3)                                             AS gp_musd,
       ROUND(100 * f.gp / f.revenue, 1)                                 AS gp_margin_pct,
       ROUND(100 * f.revenue / f.gmv, 3)                                AS take_rate_pct,
       f.success_txn                                                    AS transactions,
       ROUND(f.gmv / f.success_txn, 2)                                  AS aov_usd,
       ROUND(100.0 * f.success_txn / (f.success_txn + f.failed_txn), 2) AS success_rate_pct,
       ROUND(100.0 * f.failed_txn  / (f.success_txn + f.failed_txn), 2) AS failure_rate_pct,
       ROUND(100 * f.refunds / f.gmv, 2)                                AS refund_rate_pct,
       d.active_merchants_in_year,
       ROUND(f.avg_monthly_active, 0)                                   AS avg_monthly_active_merchants,
       f.new_live_merchants,
       f.activated_merchants,
       ROUND(100 * (f.gmv     / LAG(f.gmv)     OVER (ORDER BY f.fiscal_year) - 1), 1) AS gmv_growth_pct,
       ROUND(100 * (f.revenue / LAG(f.revenue) OVER (ORDER BY f.fiscal_year) - 1), 1) AS revenue_growth_pct,
       ROUND(100 * (f.gp      / LAG(f.gp)      OVER (ORDER BY f.fiscal_year) - 1), 1) AS gp_growth_pct,
       ROUND(100 * (1.0 * d.active_merchants_in_year
                    / LAG(d.active_merchants_in_year) OVER (ORDER BY f.fiscal_year) - 1), 1) AS merchant_growth_pct
  FROM fy f JOIN distinct_active d ON d.fiscal_year = f.fiscal_year
 ORDER BY f.fiscal_year;


-- name: q02_country_contribution
-- question: Which countries contribute the most, and how fast is each growing (USD and local currency)?
WITH c AS (
    SELECT m.country_code,
           CASE WHEN d.month_num >= 7 THEN d.year + 1 ELSE d.year END AS fy,
           SUM(f.gmv_usd) AS gmv, SUM(f.revenue_usd) AS revenue, SUM(f.gp_usd) AS gp,
           SUM(CASE WHEN f.status = 'Success' THEN f.amount_local ELSE 0 END) AS gmv_local
      FROM fact_payments_daily f
      JOIN dim_merchant m ON m.merchant_key = f.merchant_key
      JOIN dim_date d     ON d.date_key = f.date_key
     GROUP BY m.country_code, fy
)
SELECT dc.country_name,
       ROUND(SUM(CASE WHEN fy = 2025 THEN gmv END) / 1e6, 1)                         AS gmv_fy25_musd,
       ROUND(SUM(CASE WHEN fy = 2026 THEN gmv END) / 1e6, 1)                         AS gmv_fy26_musd,
       ROUND(100 * SUM(CASE WHEN fy = 2026 THEN gmv END)
                 / SUM(SUM(CASE WHEN fy = 2026 THEN gmv END)) OVER (), 1)            AS gmv_share_fy26_pct,
       ROUND(100 * (SUM(CASE WHEN fy = 2026 THEN gmv END) / SUM(CASE WHEN fy = 2025 THEN gmv END) - 1), 1) AS gmv_growth_usd_pct,
       ROUND(100 * (SUM(CASE WHEN fy = 2026 THEN gmv_local END) / SUM(CASE WHEN fy = 2025 THEN gmv_local END) - 1), 1) AS gmv_growth_local_ccy_pct,
       ROUND(SUM(CASE WHEN fy = 2026 THEN revenue END) / 1e6, 2)                     AS revenue_fy26_musd,
       ROUND(100 * SUM(CASE WHEN fy = 2026 THEN gp END) / SUM(CASE WHEN fy = 2026 THEN revenue END), 1) AS gp_margin_fy26_pct,
       RANK() OVER (ORDER BY SUM(CASE WHEN fy = 2026 THEN gmv END) DESC)            AS gmv_rank
  FROM c JOIN dim_country dc ON dc.country_code = c.country_code
 GROUP BY dc.country_name
 ORDER BY gmv_rank;


-- name: q03_segment_growth
-- question: Which segments are growing, and how does their profitability compare?
SELECT dimension_value AS segment,
       ROUND(SUM(CASE WHEN fiscal_year = 2025 THEN gmv END) / 1e6, 1)                AS gmv_fy25_musd,
       ROUND(SUM(CASE WHEN fiscal_year = 2026 THEN gmv END) / 1e6, 1)                AS gmv_fy26_musd,
       ROUND(100 * (SUM(CASE WHEN fiscal_year = 2026 THEN gmv END) / SUM(CASE WHEN fiscal_year = 2025 THEN gmv END) - 1), 1) AS gmv_growth_pct,
       ROUND(100 * (SUM(CASE WHEN fiscal_year = 2026 THEN gp END)  / SUM(CASE WHEN fiscal_year = 2025 THEN gp END) - 1), 1)  AS gp_growth_pct,
       ROUND(100 * SUM(CASE WHEN fiscal_year = 2026 THEN revenue END) / SUM(CASE WHEN fiscal_year = 2026 THEN gmv END), 3) AS take_rate_fy26_pct,
       ROUND(100 * SUM(CASE WHEN fiscal_year = 2026 THEN gp END) / SUM(CASE WHEN fiscal_year = 2026 THEN revenue END), 1)  AS gp_margin_fy26_pct,
       ROUND(100 * SUM(CASE WHEN fiscal_year = 2026 THEN gp END) / SUM(SUM(CASE WHEN fiscal_year = 2026 THEN gp END)) OVER (), 1) AS gp_share_fy26_pct,
       MAX(CASE WHEN month_key = (SELECT MAX(month_key) FROM vw_company_month) THEN active_merchants END) AS active_merchants_latest_month
  FROM vw_dimension_month
 WHERE dimension_name = 'segment'
 GROUP BY dimension_value
 ORDER BY gmv_fy26_musd DESC;


-- name: q04_vertical_volume
-- question: Which verticals have the highest transaction volume, success rate and refund rate?
SELECT m.vertical,
       SUM(CASE WHEN f.status = 'Success' THEN f.txn_count ELSE 0 END)                AS transactions_fy26,
       ROUND(SUM(f.gmv_usd) / 1e6, 1)                                               AS gmv_fy26_musd,
       ROUND(SUM(f.gmv_usd) / SUM(CASE WHEN f.status = 'Success' THEN f.txn_count ELSE 0 END), 2) AS aov_usd,
       ROUND(100.0 * SUM(CASE WHEN f.status = 'Success' THEN f.txn_count ELSE 0 END)
             / SUM(CASE WHEN f.status IN ('Success', 'Failed') THEN f.txn_count ELSE 0 END), 2) AS success_rate_pct,
       ROUND(100 * SUM(f.refund_usd) / SUM(f.gmv_usd), 2)                            AS refund_rate_pct,
       COUNT(DISTINCT CASE WHEN f.status = 'Success' THEN f.merchant_key END)          AS active_merchants,
       RANK() OVER (ORDER BY SUM(CASE WHEN f.status = 'Success' THEN f.txn_count ELSE 0 END) DESC) AS volume_rank
  FROM fact_payments_monthly f
  JOIN dim_merchant m ON m.merchant_key = f.merchant_key
 WHERE f.month_key >= 202507
 GROUP BY m.vertical
 ORDER BY volume_rank;


-- name: q05_top_merchants_gmv
-- question: Which merchants generate the highest GMV, and how concentrated is volume (Pareto)?
WITH mg AS (
    SELECT merchant_key, SUM(gmv) AS gmv, SUM(revenue) AS revenue, SUM(gp) AS gp
      FROM vw_merchant_month WHERE fiscal_year = 2026 GROUP BY merchant_key
),
ranked AS (
    SELECT mg.*, RANK() OVER (ORDER BY gmv DESC) AS gmv_rank,
           SUM(gmv) OVER (ORDER BY gmv DESC ROWS UNBOUNDED PRECEDING) / SUM(gmv) OVER () AS cumulative_share
      FROM mg
)
SELECT r.gmv_rank, m.mid, m.merchant_name, m.country_code, m.segment, m.vertical,
       ROUND(r.gmv / 1e6, 2) AS gmv_fy26_musd, ROUND(100 * r.cumulative_share, 1) AS cumulative_gmv_share_pct,
       ROUND(r.revenue / 1e3, 1) AS revenue_kusd, ROUND(r.gp / 1e3, 1) AS gp_kusd,
       ROUND(100 * r.gp / r.revenue, 1) AS gp_margin_pct, m.lifecycle_status
  FROM ranked r JOIN dim_merchant m ON m.merchant_key = r.merchant_key
 WHERE r.gmv_rank <= 15
 ORDER BY r.gmv_rank;


-- name: q06_merchant_profitability
-- question: Which merchants generate the highest GP, and which are unprofitable (negative GP)?
WITH mg AS (
    SELECT merchant_key, SUM(gmv) AS gmv, SUM(revenue) AS revenue, SUM(cogs) AS cogs, SUM(gp) AS gp,
           SUM(cost_of_failed_attempts) AS failed_cost
      FROM vw_merchant_month WHERE fiscal_year = 2026 GROUP BY merchant_key
),
ranked AS (
    SELECT mg.*, RANK() OVER (ORDER BY gp DESC) AS gp_rank_top, RANK() OVER (ORDER BY gp ASC) AS gp_rank_bottom
      FROM mg
)
SELECT CASE WHEN r.gp_rank_top <= 10 THEN 'Top 10 GP' ELSE 'Negative GP' END AS list,
       m.mid, m.merchant_name, m.country_code, m.segment,
       ROUND(r.gmv / 1e6, 2) AS gmv_fy26_musd, ROUND(r.revenue / 1e3, 1) AS revenue_kusd,
       ROUND(r.cogs / 1e3, 1) AS cogs_kusd, ROUND(r.gp / 1e3, 1) AS gp_kusd,
       ROUND(100 * r.gp / NULLIF(r.revenue, 0), 1) AS gp_margin_pct,
       ROUND(100 * r.revenue / NULLIF(r.gmv, 0), 3) AS take_rate_pct,
       ROUND(r.failed_cost / 1e3, 1) AS cost_of_failed_attempts_kusd
  FROM ranked r JOIN dim_merchant m ON m.merchant_key = r.merchant_key
 WHERE r.gp_rank_top <= 10 OR (r.gp < 0 AND r.revenue > 1000)      -- ignore merchants with no real FY26 activity
 ORDER BY r.gp DESC;


-- name: q07_declining_merchants
-- question: Which merchants have declining activity (last 3 months GMV vs the prior 3 months)?
WITH w AS (
    SELECT merchant_key,
           SUM(CASE WHEN month_key BETWEEN 202604 AND 202606 THEN gmv ELSE 0 END) AS gmv_last_3m,
           SUM(CASE WHEN month_key BETWEEN 202601 AND 202603 THEN gmv ELSE 0 END) AS gmv_prior_3m
      FROM vw_merchant_month GROUP BY merchant_key
)
SELECT m.mid, m.merchant_name, m.country_code, m.segment, m.account_manager,
       ROUND(w.gmv_prior_3m / 1e3, 1) AS gmv_prior_3m_kusd,
       ROUND(w.gmv_last_3m / 1e3, 1)  AS gmv_last_3m_kusd,
       ROUND(100 * (w.gmv_last_3m / w.gmv_prior_3m - 1), 1) AS change_pct,
       ROUND((w.gmv_last_3m - w.gmv_prior_3m) / 1e3, 1)     AS gmv_change_kusd
  FROM w JOIN dim_merchant m ON m.merchant_key = w.merchant_key
 WHERE w.gmv_prior_3m >= 3000 * 3
   AND w.gmv_last_3m > 0
   AND w.gmv_last_3m / w.gmv_prior_3m - 1 <= -0.25
 ORDER BY gmv_change_kusd;


-- name: q08_inactive_merchants
-- question: Which merchants became inactive (dormant / churned), and how much GMV did they bring before?
SELECT m.lifecycle_status, m.segment,
       COUNT(*)                                            AS merchants,
       ROUND(SUM(h.gmv_prev_12m) / 1e6, 2)                 AS their_gmv_fy25_musd,
       ROUND(AVG(julianday('2026-06-30') - julianday(m.last_txn_date)), 0) AS avg_days_since_last_txn
  FROM dim_merchant m
  LEFT JOIN (SELECT merchant_key, SUM(gmv) AS gmv_prev_12m FROM vw_merchant_month
              WHERE fiscal_year = 2025 GROUP BY merchant_key) h ON h.merchant_key = m.merchant_key
 WHERE m.lifecycle_status IN ('Dormant', 'Churned')
 GROUP BY m.lifecycle_status, m.segment
 ORDER BY m.lifecycle_status, their_gmv_fy25_musd DESC;


-- name: q09_activation_funnel
-- question: What is merchant activation performance by integration type (signed -> live -> first txn -> activated)?
SELECT integration_type,
       COUNT(*)                                                             AS signed_in_period,
       SUM(CASE WHEN live_date IS NOT NULL THEN 1 ELSE 0 END)               AS went_live,
       SUM(CASE WHEN first_txn_date IS NOT NULL THEN 1 ELSE 0 END)          AS transacted,
       SUM(is_activated)                                                    AS activated_within_30d,
       ROUND(100.0 * SUM(CASE WHEN live_date IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 1) AS live_rate_pct,
       ROUND(100.0 * SUM(is_activated) / NULLIF(SUM(CASE WHEN live_date IS NOT NULL THEN 1 ELSE 0 END), 0), 1) AS activation_rate_of_live_pct,
       ROUND(100.0 * SUM(is_activated) / COUNT(*), 1)                      AS signed_to_activated_pct,
       ROUND(AVG(days_signup_to_live), 1)                                   AS avg_days_signup_to_live,
       ROUND(AVG(days_live_to_first_txn), 1)                                AS avg_days_live_to_first_txn
  FROM dim_merchant
 WHERE signup_date >= '2024-07-01' AND signup_date <= '2026-03-31'     -- allow >= 90 days to mature
 GROUP BY integration_type
 ORDER BY signed_to_activated_pct;


-- name: q10_cohort_retention
-- question: How well do merchant cohorts (by go-live quarter) stay active over their first 12 months?
WITH cohort AS (
    SELECT merchant_key,
           strftime('%Y', live_date) || '-Q' || ((CAST(strftime('%m', live_date) AS INTEGER) + 2) / 3) AS live_quarter,
           CAST(strftime('%Y', live_date) AS INTEGER) * 12 + CAST(strftime('%m', live_date) AS INTEGER) AS live_idx
      FROM dim_merchant WHERE live_date >= '2024-07-01' AND first_txn_date IS NOT NULL
),
maturity AS (          -- months of history the YOUNGEST merchant in each cohort has had
    SELECT live_quarter, (2026 * 12 + 6) - MAX(live_idx) AS months_observed FROM cohort GROUP BY live_quarter
),
act AS (
    SELECT c.live_quarter, v.merchant_key, v.months_since_live
      FROM vw_merchant_month v JOIN cohort c ON c.merchant_key = v.merchant_key
     WHERE v.is_active = 1
)
SELECT c.live_quarter,
       COUNT(DISTINCT c.merchant_key)                                                          AS cohort_size,
       -- a retention point is shown only once every merchant in the cohort has reached that age (NULL = not yet observable)
       CASE WHEN mt.months_observed >= 1  THEN ROUND(100.0 * COUNT(DISTINCT CASE WHEN a.months_since_live = 1  THEN a.merchant_key END) / COUNT(DISTINCT c.merchant_key), 1) END AS m1_active_pct,
       CASE WHEN mt.months_observed >= 3  THEN ROUND(100.0 * COUNT(DISTINCT CASE WHEN a.months_since_live = 3  THEN a.merchant_key END) / COUNT(DISTINCT c.merchant_key), 1) END AS m3_active_pct,
       CASE WHEN mt.months_observed >= 6  THEN ROUND(100.0 * COUNT(DISTINCT CASE WHEN a.months_since_live = 6  THEN a.merchant_key END) / COUNT(DISTINCT c.merchant_key), 1) END AS m6_active_pct,
       CASE WHEN mt.months_observed >= 12 THEN ROUND(100.0 * COUNT(DISTINCT CASE WHEN a.months_since_live = 12 THEN a.merchant_key END) / COUNT(DISTINCT c.merchant_key), 1) END AS m12_active_pct
  FROM cohort c
  JOIN maturity mt ON mt.live_quarter = c.live_quarter
  LEFT JOIN act a ON a.merchant_key = c.merchant_key
 GROUP BY c.live_quarter, mt.months_observed
 ORDER BY c.live_quarter;


-- name: q11_gmv_vs_revenue
-- question: What is the relationship between GMV and revenue (take rate by segment and payment method)?
SELECT m.segment, f.payment_method,
       ROUND(SUM(f.gmv_usd) / 1e6, 1)                           AS gmv_fy26_musd,
       ROUND(SUM(f.revenue_usd) / 1e3, 1)                       AS revenue_fy26_kusd,
       ROUND(100 * SUM(f.revenue_usd) / SUM(f.gmv_usd), 3)      AS take_rate_pct,
       ROUND(100 * SUM(f.gp_usd) / SUM(f.revenue_usd), 1)       AS gp_margin_pct,
       ROUND(10000 * SUM(f.gp_usd) / SUM(f.gmv_usd), 1)         AS gp_bps_of_gmv
  FROM fact_payments_monthly f JOIN dim_merchant m ON m.merchant_key = f.merchant_key
 WHERE f.month_key >= 202507
 GROUP BY m.segment, f.payment_method
HAVING SUM(f.gmv_usd) > 0
 ORDER BY m.segment, gmv_fy26_musd DESC;


-- name: q12_profitability_by_method_gateway
-- question: What drives profitability - pricing vs cost by payment method and gateway, incl. the cost of failed attempts?
SELECT f.payment_method, f.gateway,
       ROUND(SUM(f.gmv_usd) / 1e6, 1)                                                     AS gmv_fy26_musd,
       ROUND(SUM(f.revenue_usd) / 1e3, 1)                                                 AS revenue_kusd,
       ROUND(SUM(f.cost_usd) / 1e3, 1)                                                    AS cogs_kusd,
       ROUND(SUM(CASE WHEN f.status IN ('Failed', 'Voided') THEN f.cost_usd ELSE 0 END) / 1e3, 1) AS failed_attempt_cost_kusd,
       ROUND(SUM(f.gp_usd) / 1e3, 1)                                                      AS gp_kusd,
       ROUND(100 * SUM(f.gp_usd) / NULLIF(SUM(f.revenue_usd), 0), 1)                      AS gp_margin_pct
  FROM fact_payments_monthly f
 WHERE f.month_key >= 202507
 GROUP BY f.payment_method, f.gateway
 ORDER BY gp_kusd DESC;


-- name: q13_success_rate_gateway_month
-- question: Where are the payment performance issues - success rate by gateway and method over time?
SELECT d.year_month, g.gateway, g.payment_method,
       SUM(g.success_count) AS success_txn, SUM(g.failed_count) AS failed_txn,
       ROUND(100.0 * SUM(g.success_count) / (SUM(g.success_count) + SUM(g.failed_count)), 2) AS success_rate_pct,
       ROUND(100.0 * SUM(g.success_count) / (SUM(g.success_count) + SUM(g.failed_count))
             - 100.0 * SUM(SUM(g.success_count)) OVER (PARTITION BY g.gateway, g.payment_method)
                     / SUM(SUM(g.success_count) + SUM(g.failed_count)) OVER (PARTITION BY g.gateway, g.payment_method), 2) AS vs_24m_avg_pp
  FROM fact_gateway_daily g JOIN dim_date d ON d.date_key = g.date_key
 GROUP BY d.year_month, g.gateway, g.payment_method
HAVING SUM(g.success_count) + SUM(g.failed_count) > 5000
 ORDER BY vs_24m_avg_pp
 LIMIT 25;


-- name: q14_decline_reasons
-- question: What are the main reasons for failed payments, and which gateways show rising timeouts?
SELECT gateway, decline_reason,
       SUM(CASE WHEN month_key < 202507 THEN failed_count ELSE 0 END)  AS failed_fy25,
       SUM(CASE WHEN month_key >= 202507 THEN failed_count ELSE 0 END) AS failed_fy26,
       ROUND(100.0 * SUM(CASE WHEN month_key >= 202507 THEN failed_count ELSE 0 END)
             / SUM(SUM(CASE WHEN month_key >= 202507 THEN failed_count ELSE 0 END)) OVER (PARTITION BY gateway), 1) AS share_of_gateway_fy26_pct,
       ROUND(100.0 * (1.0 * SUM(CASE WHEN month_key >= 202507 THEN failed_count ELSE 0 END)
             / NULLIF(SUM(CASE WHEN month_key < 202507 THEN failed_count ELSE 0 END), 0) - 1), 1) AS yoy_change_pct
  FROM fact_declines_monthly
 GROUP BY gateway, decline_reason
 ORDER BY gateway, failed_fy26 DESC;


-- name: q15_refund_rate_vertical
-- question: Which verticals carry the highest refund exposure?
SELECT m.vertical,
       ROUND(SUM(f.gmv_usd) / 1e6, 1)                  AS gmv_musd,
       ROUND(SUM(f.refund_usd) / 1e6, 2)               AS refunds_musd,
       ROUND(100 * SUM(f.refund_usd) / SUM(f.gmv_usd), 2) AS refund_rate_pct,
       SUM(CASE WHEN f.status = 'Refunded' THEN f.txn_count ELSE 0 END) AS refund_count,
       ROUND(SUM(CASE WHEN f.status = 'Refunded' THEN f.cost_usd ELSE 0 END) / 1e3, 1) AS refund_cost_kusd
  FROM fact_payments_monthly f JOIN dim_merchant m ON m.merchant_key = f.merchant_key
 GROUP BY m.vertical
 ORDER BY refund_rate_pct DESC;


-- name: q16_billing_leakage
-- question: Where is billed revenue below contracted pricing (revenue leakage), since when, and how much?
WITH mm AS (
    SELECT merchant_key, month_key, SUM(revenue) AS billed, SUM(expected_revenue) AS expected
      FROM vw_merchant_month GROUP BY merchant_key, month_key
),
flag AS (
    SELECT merchant_key, MIN(month_key) AS leakage_since_month,
           SUM(expected - billed) AS leakage_usd, SUM(expected) AS expected_usd
      FROM mm WHERE expected - billed > 0.02 * expected AND expected > 50
     GROUP BY merchant_key
)
SELECT m.mid, m.merchant_name, m.country_code, m.segment, m.account_manager,
       f.leakage_since_month,
       ROUND(f.leakage_usd, 0)                        AS leakage_usd,
       ROUND(100 * f.leakage_usd / f.expected_usd, 1) AS billed_below_contract_pct
  FROM flag f JOIN dim_merchant m ON m.merchant_key = f.merchant_key
 ORDER BY f.leakage_usd DESC;


-- name: q17_gmv_growth_bridge
-- question: Where did FY2026 GMV growth come from - new merchants, expansion, contraction or churn?
WITH m AS (
    SELECT merchant_key,
           SUM(CASE WHEN fiscal_year = 2025 THEN gmv ELSE 0 END) AS gmv25,
           SUM(CASE WHEN fiscal_year = 2026 THEN gmv ELSE 0 END) AS gmv26
      FROM vw_merchant_month GROUP BY merchant_key
),
c AS (
    SELECT CASE WHEN gmv25 = 0 AND gmv26 > 0 THEN '2 New merchants'
                WHEN gmv25 > 0 AND gmv26 = 0 THEN '5 Churned merchants'
                WHEN gmv26 >= gmv25          THEN '3 Expansion (existing)'
                ELSE '4 Contraction (existing)' END AS bridge_step,
           gmv25, gmv26
      FROM m
)
SELECT '1 FY2025 GMV' AS bridge_step, NULL AS merchants, ROUND(SUM(gmv25) / 1e6, 1) AS gmv_musd FROM m
UNION ALL
SELECT bridge_step, COUNT(*), ROUND(SUM(gmv26 - gmv25) / 1e6, 1) FROM c GROUP BY bridge_step
UNION ALL
SELECT '6 FY2026 GMV', NULL, ROUND(SUM(gmv26) / 1e6, 1) FROM m
ORDER BY bridge_step;
