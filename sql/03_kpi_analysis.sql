-- =============================================================================
-- 03_kpi_analysis.sql  |  KPI layer views
-- -----------------------------------------------------------------------------
-- KPI conventions
--   GMV            value of successful payments
--   Net GMV        GMV - refunds
--   Revenue        billed merchant fees (MDR + fixed fee)
--   COGS           scheme / interchange / gateway costs incl. fees on failed & voided attempts
--   GP             Revenue - COGS;  GP margin = GP / Revenue;  take rate = Revenue / GMV
--   Success rate   successful / (successful + failed) transactions
--   Active         merchant with >= 1 successful payment in the period
-- =============================================================================

-- -----------------------------------------------------------------------------
-- vw_merchant_month: one row per merchant x month with activity
-- -----------------------------------------------------------------------------
DROP VIEW IF EXISTS vw_merchant_month;
CREATE VIEW vw_merchant_month AS
WITH agg AS (
    SELECT f.merchant_key, f.month_key,
           SUM(f.gmv_usd)                                                         AS gmv,
           SUM(f.refund_usd)                                                      AS refunds,
           SUM(CASE WHEN f.status = 'Success'  THEN f.txn_count ELSE 0 END)       AS success_txn,
           SUM(CASE WHEN f.status = 'Failed'   THEN f.txn_count ELSE 0 END)       AS failed_txn,
           SUM(CASE WHEN f.status = 'Refunded' THEN f.txn_count ELSE 0 END)       AS refunded_txn,
           SUM(CASE WHEN f.status = 'Voided'   THEN f.txn_count ELSE 0 END)       AS voided_txn,
           SUM(f.revenue_usd)                                                     AS revenue,
           SUM(f.expected_revenue_usd)                                            AS expected_revenue,
           SUM(f.cost_usd)                                                        AS cogs,
           SUM(CASE WHEN f.status IN ('Failed', 'Voided') THEN f.cost_usd ELSE 0 END) AS cost_of_failed_attempts,
           SUM(f.gp_usd)                                                          AS gp
      FROM fact_payments_monthly f
     GROUP BY f.merchant_key, f.month_key
)
SELECT a.merchant_key, a.month_key,
       CASE WHEN a.month_key % 100 >= 7 THEN a.month_key / 100 + 1 ELSE a.month_key / 100 END AS fiscal_year,
       m.country_code, m.segment, m.vertical, m.service, m.integration_type,
       a.gmv, a.refunds, a.gmv - a.refunds                                      AS net_gmv,
       a.success_txn, a.failed_txn, a.refunded_txn, a.voided_txn,
       a.revenue, a.expected_revenue, a.expected_revenue - a.revenue            AS billing_leakage,
       a.cogs, a.cost_of_failed_attempts, a.gp,
       a.gp / NULLIF(a.revenue, 0)                                              AS gp_margin,
       a.revenue / NULLIF(a.gmv, 0)                                             AS take_rate,
       a.gmv / NULLIF(a.success_txn, 0)                                         AS aov,
       1.0 * a.success_txn / NULLIF(a.success_txn + a.failed_txn, 0)            AS success_rate,
       CASE WHEN a.success_txn > 0 THEN 1 ELSE 0 END                            AS is_active,
       CASE WHEN CAST(strftime('%Y%m', m.live_date) AS INTEGER) = a.month_key THEN 1 ELSE 0 END AS is_live_month,
       CASE WHEN CAST(strftime('%Y%m', m.first_txn_date) AS INTEGER) = a.month_key THEN 1 ELSE 0 END AS is_first_txn_month,
       ((a.month_key / 100) * 12 + a.month_key % 100)
         - (CAST(strftime('%Y', m.live_date) AS INTEGER) * 12 + CAST(strftime('%m', m.live_date) AS INTEGER)) AS months_since_live,
       LAG(a.gmv) OVER (PARTITION BY a.merchant_key ORDER BY a.month_key)        AS prev_month_gmv,
       RANK() OVER (PARTITION BY a.month_key ORDER BY a.gmv DESC)                 AS gmv_rank_in_month
  FROM agg a
  JOIN dim_merchant m ON m.merchant_key = a.merchant_key;


-- -----------------------------------------------------------------------------
-- vw_company_month: company KPIs incl. merchant counts, MoM / YoY, 3M average
-- -----------------------------------------------------------------------------
DROP VIEW IF EXISTS vw_company_month;
CREATE VIEW vw_company_month AS
WITH m AS (
    SELECT month_key, fiscal_year,
           SUM(gmv) AS gmv, SUM(net_gmv) AS net_gmv, SUM(refunds) AS refunds,
           SUM(revenue) AS revenue, SUM(cogs) AS cogs, SUM(gp) AS gp,
           SUM(success_txn) AS success_txn, SUM(failed_txn) AS failed_txn,
           SUM(is_active) AS active_merchants,
           SUM(is_first_txn_month) AS newly_transacting_merchants
      FROM vw_merchant_month
     GROUP BY month_key, fiscal_year
),
newlive AS (
    SELECT CAST(strftime('%Y%m', live_date) AS INTEGER) AS month_key, COUNT(*) AS new_live_merchants,
           SUM(is_activated) AS activated_merchants
      FROM dim_merchant WHERE live_date IS NOT NULL
     GROUP BY 1
)
SELECT m.*,
       COALESCE(n.new_live_merchants, 0)                                     AS new_live_merchants,
       COALESCE(n.activated_merchants, 0)                                    AS activated_merchants,
       m.gp / NULLIF(m.revenue, 0)                                           AS gp_margin,
       m.revenue / NULLIF(m.gmv, 0)                                          AS take_rate,
       m.gmv / NULLIF(m.success_txn, 0)                                      AS aov,
       1.0 * m.success_txn / NULLIF(m.success_txn + m.failed_txn, 0)         AS success_rate,
       1.0 * m.failed_txn  / NULLIF(m.success_txn + m.failed_txn, 0)         AS failure_rate,
       m.refunds / NULLIF(m.gmv, 0)                                          AS refund_rate,
       (m.gmv - LAG(m.gmv) OVER w) / NULLIF(LAG(m.gmv) OVER w, 0)            AS gmv_mom,
       (m.gmv - LAG(m.gmv, 12) OVER w) / NULLIF(LAG(m.gmv, 12) OVER w, 0)    AS gmv_yoy,
       (m.revenue - LAG(m.revenue, 12) OVER w) / NULLIF(LAG(m.revenue, 12) OVER w, 0) AS revenue_yoy,
       (m.gp - LAG(m.gp, 12) OVER w) / NULLIF(LAG(m.gp, 12) OVER w, 0)       AS gp_yoy,
       (1.0 * m.active_merchants - LAG(m.active_merchants, 12) OVER w)
         / NULLIF(LAG(m.active_merchants, 12) OVER w, 0)                     AS active_merchant_yoy,
       AVG(m.gmv) OVER (ORDER BY m.month_key ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS gmv_3m_avg,
       SUM(m.gmv) OVER (PARTITION BY m.fiscal_year ORDER BY m.month_key)     AS fytd_gmv
  FROM m
  LEFT JOIN newlive n ON n.month_key = m.month_key
WINDOW w AS (ORDER BY m.month_key);


-- -----------------------------------------------------------------------------
-- vw_dimension_month: the same KPIs by country / segment / vertical / method / gateway
-- (long format: dimension_name, dimension_value) with a rank per month
-- -----------------------------------------------------------------------------
DROP VIEW IF EXISTS vw_dimension_month;
CREATE VIEW vw_dimension_month AS
WITH base AS (
    SELECT f.month_key, m.country_code, m.segment, m.vertical, f.payment_method, f.gateway,
           f.gmv_usd, f.refund_usd, f.revenue_usd, f.cost_usd, f.gp_usd,
           CASE WHEN f.status = 'Success' THEN f.txn_count ELSE 0 END AS s,
           CASE WHEN f.status = 'Failed'  THEN f.txn_count ELSE 0 END AS fl,
           f.merchant_key
      FROM fact_payments_monthly f JOIN dim_merchant m ON m.merchant_key = f.merchant_key
),
long AS (
    SELECT 'country' AS dimension_name, country_code AS dimension_value, * FROM base
    UNION ALL SELECT 'segment',  segment,        * FROM base
    UNION ALL SELECT 'vertical', vertical,       * FROM base
    UNION ALL SELECT 'method',   payment_method, * FROM base
    UNION ALL SELECT 'gateway',  gateway,        * FROM base
),
agg AS (
    SELECT dimension_name, dimension_value, month_key,
           SUM(gmv_usd) AS gmv, SUM(refund_usd) AS refunds, SUM(revenue_usd) AS revenue,
           SUM(cost_usd) AS cogs, SUM(gp_usd) AS gp, SUM(s) AS success_txn, SUM(fl) AS failed_txn,
           COUNT(DISTINCT CASE WHEN s > 0 THEN merchant_key END) AS active_merchants
      FROM long
     GROUP BY dimension_name, dimension_value, month_key
)
SELECT a.*,
       CASE WHEN a.month_key % 100 >= 7 THEN a.month_key / 100 + 1 ELSE a.month_key / 100 END AS fiscal_year,
       a.gp / NULLIF(a.revenue, 0)                                        AS gp_margin,
       a.revenue / NULLIF(a.gmv, 0)                                       AS take_rate,
       1.0 * a.success_txn / NULLIF(a.success_txn + a.failed_txn, 0)      AS success_rate,
       (a.gmv - LAG(a.gmv, 12) OVER w) / NULLIF(LAG(a.gmv, 12) OVER w, 0) AS gmv_yoy,
       RANK() OVER (PARTITION BY a.dimension_name, a.month_key ORDER BY a.gmv DESC) AS gmv_rank
  FROM agg a
WINDOW w AS (PARTITION BY a.dimension_name, a.dimension_value ORDER BY a.month_key);
