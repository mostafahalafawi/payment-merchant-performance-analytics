# DAX Measures

Create a `_Measures` table and group measures into display folders. Table names match `data/processed/*.csv`.
The main fact is **`fact_payments_monthly`** (committed). `fact_gateway_daily` drives the daily quality visuals.
`dim_date` is marked as the date table, and fiscal-year time intelligence uses the year-end date **"6/30"**.

---

## 1. Volume (`1 Volume`)

```DAX
GMV =
SUM ( fact_payments_monthly[gmv_usd] )
-- Value of successful payments. The volume headline.

Refunds =
SUM ( fact_payments_monthly[refund_usd] )

Net GMV =
[GMV] - [Refunds]

Transactions =
CALCULATE ( SUM ( fact_payments_monthly[txn_count] ), dim_status[status] = "Success" )

Failed Transactions =
CALCULATE ( SUM ( fact_payments_monthly[txn_count] ), dim_status[status] = "Failed" )

AOV =
DIVIDE ( [GMV], [Transactions] )
-- Average ticket. B2B ~ $1,800, Food & Beverage ~ $10: never compare GMV without AOV.
```

## 2. Revenue & profitability (`2 Profitability`)

```DAX
Revenue =
SUM ( fact_payments_monthly[revenue_usd] )

Expected Revenue =
SUM ( fact_payments_monthly[expected_revenue_usd] )

Billing Leakage =
[Expected Revenue] - [Revenue]
-- Under-billing vs contract. Should be 0; any positive value is money not collected.

COGS =
SUM ( fact_payments_monthly[cost_usd] )

Cost of Failed Attempts =
CALCULATE ( [COGS], dim_status[status] IN { "Failed", "Voided" } )

Gross Profit =
SUM ( fact_payments_monthly[gp_usd] )

GP Margin % =
DIVIDE ( [Gross Profit], [Revenue] )

Take Rate % =
DIVIDE ( [Revenue], [GMV] )
-- Price realized per $ processed.

GP bps of GMV =
DIVIDE ( [Gross Profit], [GMV] ) * 10000
-- Compares segments fairly: Enterprise ~30 bps vs SME ~109 bps.

Negative GP Merchants =
COUNTROWS (
    FILTER ( VALUES ( dim_merchant[merchant_key] ), [Gross Profit] < 0 && [Revenue] > 1000 )
)
```

## 3. Payment quality (`3 Quality`)

```DAX
Success Rate % =
DIVIDE ( [Transactions], [Transactions] + [Failed Transactions] )

Failure Rate % =
1 - [Success Rate %]

Refund Rate % =
DIVIDE ( [Refunds], [GMV] )

-- daily monitoring table (fact_gateway_daily)
Daily Success Rate % =
DIVIDE (
    SUM ( fact_gateway_daily[success_count] ),
    SUM ( fact_gateway_daily[success_count] ) + SUM ( fact_gateway_daily[failed_count] )
)

Success Rate 28D Baseline % =
VAR _d = MAX ( dim_date[date] )
RETURN
    CALCULATE ( [Daily Success Rate %], DATESINPERIOD ( dim_date[date], _d - 1, -28, DAY ) )

Success Rate vs Baseline pp =
( [Daily Success Rate %] - [Success Rate 28D Baseline %] ) * 100
-- Conditional formatting: <= -3pp red. The full robust-z detector runs in analysis.py.

Timeout Share % =
DIVIDE (
    CALCULATE ( SUM ( agg_declines_gateway_month[failed_count] ), agg_declines_gateway_month[decline_reason] = "Gateway Timeout" ),
    SUM ( agg_declines_gateway_month[failed_count] )
)
```

## 4. Merchants & lifecycle (`4 Merchants`)

```DAX
Active Merchants =
CALCULATE (
    DISTINCTCOUNT ( fact_payments_monthly[merchant_key] ),
    dim_status[status] = "Success"
)

Active Merchants (Period End) =
VAR _m = MAX ( dim_date[month_key] )
RETURN CALCULATE ( [Active Merchants], dim_date[month_key] = _m )

New Merchants =
VAR _start = MIN ( dim_date[date] )
VAR _end   = MAX ( dim_date[date] )
RETURN
    CALCULATE (
        COUNTROWS ( dim_merchant ),
        dim_merchant[live_date] >= _start, dim_merchant[live_date] <= _end,
        REMOVEFILTERS ( dim_date )
    )

Activated Merchants =
VAR _start = MIN ( dim_date[date] )
VAR _end   = MAX ( dim_date[date] )
RETURN
    CALCULATE (
        COUNTROWS ( dim_merchant ),
        dim_merchant[live_date] >= _start, dim_merchant[live_date] <= _end,
        dim_merchant[is_activated] = 1,
        REMOVEFILTERS ( dim_date )
    )

Activation Rate % =
DIVIDE ( [Activated Merchants], [New Merchants] )

Merchants by Lifecycle Status =
COUNTROWS ( dim_merchant )            -- use with dim_merchant[lifecycle_status] on an axis

Median Days to Go-Live =
MEDIAN ( dim_merchant[days_signup_to_live] )
```

## 5. Growth & time intelligence (`5 Growth`)

```DAX
GMV PY =
CALCULATE ( [GMV], SAMEPERIODLASTYEAR ( dim_date[date] ) )

GMV YoY % =
DIVIDE ( [GMV] - [GMV PY], [GMV PY] )

GMV PM =
CALCULATE ( [GMV], DATEADD ( dim_date[date], -1, MONTH ) )

GMV MoM % =
DIVIDE ( [GMV] - [GMV PM], [GMV PM] )

Revenue YoY % =
VAR _py = CALCULATE ( [Revenue], SAMEPERIODLASTYEAR ( dim_date[date] ) )
RETURN DIVIDE ( [Revenue] - _py, _py )

GP YoY % =
VAR _py = CALCULATE ( [Gross Profit], SAMEPERIODLASTYEAR ( dim_date[date] ) )
RETURN DIVIDE ( [Gross Profit] - _py, _py )

Merchant Growth % =
VAR _py = CALCULATE ( [Active Merchants], SAMEPERIODLASTYEAR ( dim_date[date] ) )
RETURN DIVIDE ( [Active Merchants] - _py, _py )

GMV FYTD =
TOTALYTD ( [GMV], dim_date[date], "6/30" )            -- fiscal year ends 30 June

GMV FYTD PY =
CALCULATE ( [GMV FYTD], SAMEPERIODLASTYEAR ( dim_date[date] ) )

GMV 3M Avg =
DIVIDE ( CALCULATE ( [GMV], DATESINPERIOD ( dim_date[date], MAX ( dim_date[date] ), -3, MONTH ) ), 3 )

GMV Local Currency =
IF ( HASONEVALUE ( dim_country[currency] ), SUM ( fact_payments_monthly[gmv_local] ) )
-- Only meaningful for one currency at a time (blank otherwise).

GMV YoY % (Local Currency) =
VAR _py = CALCULATE ( [GMV Local Currency], SAMEPERIODLASTYEAR ( dim_date[date] ) )
RETURN DIVIDE ( [GMV Local Currency] - _py, _py )
-- Egypt FY2026: +45.8% in EGP vs +40.4% in USD: the gap is FX, not performance.
```

## 6. Ranking & concentration (`6 Rank`)

```DAX
Merchant GMV Rank =
RANKX ( ALLSELECTED ( dim_merchant[merchant_name] ), [GMV], , DESC, DENSE )

Top 10 Merchant GMV Share % =
VAR _top = TOPN ( 10, ALLSELECTED ( dim_merchant[merchant_key] ), [GMV], DESC )
RETURN DIVIDE ( CALCULATE ( [GMV], _top ), CALCULATE ( [GMV], ALLSELECTED ( dim_merchant ) ) )

Cumulative GMV Share % =
VAR _cur = [GMV]
VAR _above =
    FILTER ( ALLSELECTED ( dim_merchant[merchant_key] ), [GMV] >= _cur )
RETURN DIVIDE ( SUMX ( _above, [GMV] ), CALCULATE ( [GMV], ALLSELECTED ( dim_merchant ) ) )
-- Pareto curve on a merchant-level table sorted by GMV.

Country Rank =
RANKX ( ALLSELECTED ( dim_country[country_name] ), [GMV], , DESC, DENSE )
```

## 7. Narrative (`7 Narrative`)

```DAX
Title Executive =
"GMV " & FORMAT ( [GMV] / 1e6, "$#,0" ) & "M ("
    & FORMAT ( [GMV YoY %], "+0.0%;-0.0%" ) & " YoY) | GP margin "
    & FORMAT ( [GP Margin %], "0.0%" ) & " | Success rate " & FORMAT ( [Success Rate %], "0.00%" )

Status Color Success Rate =
SWITCH ( TRUE (), [Success Rate %] >= 0.91, "#0CA30C", [Success Rate %] >= 0.88, "#FAB219", "#D03B3B" )
```

