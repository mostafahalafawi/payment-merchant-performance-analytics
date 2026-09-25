-- =============================================================================
-- 02_cleaning.sql  |  In-database data-quality assertions
-- -----------------------------------------------------------------------------
-- Cleaning happens in python/etl.py. These assertions independently re-check
-- the loaded model; every check must return failing_rows = 0.
-- =============================================================================
DROP VIEW IF EXISTS vw_dq_assertions;
CREATE VIEW vw_dq_assertions AS

-- A01: GMV exists only on successful payments
SELECT 'A01' AS check_id, 'GMV on non-success rows' AS check_name,
       (SELECT COUNT(*) FROM fact_payments_daily WHERE status <> 'Success' AND gmv_usd <> 0) AS failing_rows

UNION ALL -- A02: revenue can never exceed the payment value
SELECT 'A02', 'Revenue greater than GMV on success rows',
       (SELECT COUNT(*) FROM fact_payments_daily WHERE status = 'Success' AND revenue_usd > gmv_usd + 0.01)

UNION ALL -- A03: gross profit identity
SELECT 'A03', 'GP <> revenue - cost',
       (SELECT COUNT(*) FROM fact_payments_daily WHERE ABS(gp_usd - (revenue_usd - cost_usd)) > 0.01)

UNION ALL -- A04: no activity before the merchant went live
SELECT 'A04', 'Transactions before merchant go-live',
       (SELECT COUNT(*) FROM fact_payments_daily f
          JOIN dim_merchant m ON m.merchant_key = f.merchant_key
         WHERE f.date_key < m.live_date_key)

UNION ALL -- A05: one merchant per MID
SELECT 'A05', 'Duplicate MIDs in dim_merchant',
       (SELECT COUNT(*) - COUNT(DISTINCT mid) FROM dim_merchant)

UNION ALL -- A06: monthly fact ties to daily fact (GMV and revenue)
SELECT 'A06', 'Monthly fact does not tie to daily fact',
       (SELECT CASE WHEN ABS((SELECT SUM(gmv_usd) FROM fact_payments_daily) - (SELECT SUM(gmv_usd) FROM fact_payments_monthly)) > 1
                      OR ABS((SELECT SUM(revenue_usd) FROM fact_payments_daily) - (SELECT SUM(revenue_usd) FROM fact_payments_monthly)) > 1
                    THEN 1 ELSE 0 END)

UNION ALL -- A07: every payment row has contracted pricing
SELECT 'A07', 'Merchant-method combinations without contracted pricing',
       (SELECT COUNT(*) FROM (SELECT DISTINCT merchant_key, payment_method FROM fact_payments_monthly) f
         WHERE NOT EXISTS (SELECT 1 FROM dim_merchant_pricing p
                            WHERE p.merchant_key = f.merchant_key AND p.payment_method = f.payment_method))

UNION ALL -- A08: gateway monitoring table ties to the payment fact
SELECT 'A08', 'Gateway daily table does not tie to payment fact (success count)',
       (SELECT CASE WHEN (SELECT SUM(success_count) FROM fact_gateway_daily)
                       = (SELECT SUM(txn_count) FROM fact_payments_daily WHERE status = 'Success') THEN 0 ELSE 1 END)

UNION ALL -- A09: decline-reason detail roughly reconciles to failed transactions (<2% gap)
SELECT 'A09', 'Decline reasons differ from failed transactions by more than 2%',
       (SELECT CASE WHEN ABS(1.0 * (SELECT SUM(failed_count) FROM fact_declines_monthly)
                           / (SELECT SUM(txn_count) FROM fact_payments_daily WHERE status = 'Failed') - 1) > 0.02
                    THEN 1 ELSE 0 END)

UNION ALL -- A10: first transaction never before go-live, never before signup
SELECT 'A10', 'Merchant timeline out of order (signup > live or live > first txn)',
       (SELECT COUNT(*) FROM dim_merchant
         WHERE (live_date IS NOT NULL AND live_date < signup_date)
            OR (first_txn_date IS NOT NULL AND first_txn_date < live_date));
