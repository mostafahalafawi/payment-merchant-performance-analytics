-- =============================================================================
-- 01_schema.sql  |  Star schema for Payment & Merchant Performance Analytics
-- -----------------------------------------------------------------------------
-- Engine: SQLite 3.25+ (window functions). ANSI-style SQL; ports to PostgreSQL
-- / SQL Server with type changes only.
--
-- Grain
--   fact_payments_daily    date x merchant x payment method x gateway x status
--   fact_payments_monthly  month x merchant x payment method x gateway x status
--   fact_declines_monthly  month x merchant x payment method x gateway x decline reason
--   fact_gateway_daily     date x gateway x payment method x country (monitoring)
-- Money columns are USD. GMV = successful payment value only.
-- =============================================================================
PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS fact_payments_daily;
DROP TABLE IF EXISTS fact_payments_monthly;
DROP TABLE IF EXISTS fact_declines_monthly;
DROP TABLE IF EXISTS fact_gateway_daily;
DROP TABLE IF EXISTS dim_merchant_pricing;
DROP TABLE IF EXISTS dim_merchant;
DROP TABLE IF EXISTS dim_date;
DROP TABLE IF EXISTS dim_payment_method;
DROP TABLE IF EXISTS dim_gateway;
DROP TABLE IF EXISTS dim_country;
DROP TABLE IF EXISTS dim_status;
DROP TABLE IF EXISTS ref_gateway_costs;
DROP TABLE IF EXISTS ref_fx_rates;

CREATE TABLE dim_date (
    date_key          INTEGER PRIMARY KEY,         -- YYYYMMDD
    date              TEXT    NOT NULL,
    month_key         INTEGER NOT NULL,            -- YYYYMM
    year_month        TEXT    NOT NULL,
    year              INTEGER NOT NULL,
    month_num         INTEGER NOT NULL,
    month_name        TEXT    NOT NULL,
    fiscal_year       INTEGER NOT NULL,            -- FY ends in June: Jul-2025..Jun-2026 = 2026
    fiscal_year_label TEXT    NOT NULL,
    fiscal_month_num  INTEGER NOT NULL,            -- Jul = 1 ... Jun = 12
    fiscal_quarter    TEXT    NOT NULL,
    weekday_name      TEXT    NOT NULL,
    is_weekend        INTEGER NOT NULL             -- Fri/Sat
);
CREATE INDEX ix_date_month ON dim_date(month_key);

CREATE TABLE dim_country (
    country_code TEXT PRIMARY KEY,
    country_name TEXT NOT NULL,
    currency     TEXT NOT NULL,
    region       TEXT NOT NULL
);

CREATE TABLE dim_payment_method (
    payment_method      TEXT PRIMARY KEY,         -- CARD, LDEBIT, WALLET, TOKEN, BNPL, BANKTR
    payment_method_name TEXT NOT NULL,
    default_mdr_pct     REAL,
    default_cost_pct    REAL
);

CREATE TABLE dim_gateway (
    gateway           TEXT PRIMARY KEY,
    gateway_name      TEXT NOT NULL,
    gateway_countries TEXT,
    auth_fee_usd      REAL
);

CREATE TABLE dim_status (
    status                 TEXT PRIMARY KEY,      -- Success, Failed, Refunded, Voided
    counts_in_gmv          INTEGER NOT NULL,
    counts_in_success_rate INTEGER NOT NULL,
    sort_order             INTEGER NOT NULL
);

CREATE TABLE dim_merchant (
    merchant_key            INTEGER PRIMARY KEY,
    merchant_id             TEXT NOT NULL,
    mid                     TEXT NOT NULL UNIQUE,
    merchant_name           TEXT NOT NULL,
    country_code            TEXT NOT NULL REFERENCES dim_country(country_code),
    segment                 TEXT NOT NULL,        -- Enterprise, SME, Online, B2B
    vertical                TEXT NOT NULL,
    service                 TEXT NOT NULL,
    integration_type        TEXT NOT NULL,
    settlement_type         TEXT NOT NULL,
    account_manager         TEXT,
    signup_date             TEXT NOT NULL,
    live_date               TEXT,
    first_txn_date          TEXT,
    last_txn_date           TEXT,
    live_date_corrected     INTEGER,
    days_signup_to_live     REAL,
    days_live_to_first_txn  REAL,
    is_activated            INTEGER,              -- first success within activation window
    lifecycle_status        TEXT,                 -- Active / Dormant / Churned / Live - never transacted / Onboarding
    signup_cohort           TEXT,
    live_cohort             TEXT,
    live_fy                 REAL,
    is_new_in_period        INTEGER,
    signup_date_key         INTEGER,
    live_date_key           INTEGER,
    first_txn_date_key      INTEGER,
    last_txn_date_key       INTEGER
);

CREATE TABLE dim_merchant_pricing (
    merchant_id    TEXT NOT NULL,
    payment_method TEXT NOT NULL REFERENCES dim_payment_method(payment_method),
    mdr_pct        REAL NOT NULL,
    fixed_fee_usd  REAL NOT NULL,
    effective_from TEXT,
    merchant_key   INTEGER NOT NULL REFERENCES dim_merchant(merchant_key),
    PRIMARY KEY (merchant_key, payment_method)
);

CREATE TABLE ref_gateway_costs (
    gateway        TEXT NOT NULL,
    gateway_name   TEXT,
    payment_method TEXT NOT NULL,
    cost_pct       REAL NOT NULL,
    cost_fixed_usd REAL NOT NULL,
    auth_fee_usd   REAL NOT NULL,
    PRIMARY KEY (gateway, payment_method)
);

CREATE TABLE ref_fx_rates (
    fx_month     TEXT NOT NULL,
    currency     TEXT NOT NULL,
    rate_per_usd REAL NOT NULL,
    PRIMARY KEY (fx_month, currency)
);

CREATE TABLE fact_payments_daily (
    date_key             INTEGER NOT NULL REFERENCES dim_date(date_key),
    month_key            INTEGER NOT NULL,
    merchant_key         INTEGER NOT NULL REFERENCES dim_merchant(merchant_key),
    payment_method       TEXT    NOT NULL REFERENCES dim_payment_method(payment_method),
    gateway              TEXT    NOT NULL REFERENCES dim_gateway(gateway),
    status               TEXT    NOT NULL REFERENCES dim_status(status),
    currency             TEXT    NOT NULL,
    txn_count            INTEGER NOT NULL CHECK (txn_count > 0),
    amount_usd           REAL    NOT NULL CHECK (amount_usd >= 0),
    gmv_usd              REAL    NOT NULL,         -- Success only
    refund_usd           REAL    NOT NULL,         -- Refunded only
    revenue_usd          REAL    NOT NULL,         -- billed revenue
    expected_revenue_usd REAL    NOT NULL,         -- contracted pricing x volume
    cost_usd             REAL    NOT NULL,         -- COGS: scheme / interchange / gateway fees
    gp_usd               REAL    NOT NULL,
    amount_local         REAL    NOT NULL,
    PRIMARY KEY (date_key, merchant_key, payment_method, gateway, status)
);
CREATE INDEX ix_fpd_month ON fact_payments_daily(month_key, merchant_key);

CREATE TABLE fact_payments_monthly (
    month_key            INTEGER NOT NULL,
    merchant_key         INTEGER NOT NULL REFERENCES dim_merchant(merchant_key),
    payment_method       TEXT    NOT NULL,
    gateway              TEXT    NOT NULL,
    status               TEXT    NOT NULL,
    txn_count            INTEGER NOT NULL,
    amount_usd           REAL    NOT NULL,
    gmv_usd              REAL    NOT NULL,
    refund_usd           REAL    NOT NULL,
    revenue_usd          REAL    NOT NULL,
    expected_revenue_usd REAL    NOT NULL,
    cost_usd             REAL    NOT NULL,
    gp_usd               REAL    NOT NULL,
    currency             TEXT    NOT NULL,
    gmv_local            REAL    NOT NULL,         -- successful payment value in local currency (constant-currency growth)
    date_key             INTEGER NOT NULL REFERENCES dim_date(date_key),
    PRIMARY KEY (month_key, merchant_key, payment_method, gateway, status)
);

CREATE TABLE fact_declines_monthly (
    month_key      INTEGER NOT NULL,
    date_key       INTEGER NOT NULL,
    merchant_key   INTEGER NOT NULL REFERENCES dim_merchant(merchant_key),
    payment_method TEXT    NOT NULL,
    gateway        TEXT    NOT NULL,
    decline_reason TEXT    NOT NULL,
    failed_count   INTEGER NOT NULL,
    PRIMARY KEY (month_key, merchant_key, payment_method, gateway, decline_reason)
);

CREATE TABLE fact_gateway_daily (
    date_key       INTEGER NOT NULL,
    gateway        TEXT    NOT NULL,
    payment_method TEXT    NOT NULL,
    country_code   TEXT    NOT NULL,
    success_count  INTEGER NOT NULL,
    failed_count   INTEGER NOT NULL,
    gmv_usd        REAL    NOT NULL,
    PRIMARY KEY (date_key, gateway, payment_method, country_code)
);
