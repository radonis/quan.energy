# ============================================
# MARKET_FEATURES.py
# Budowa tabeli market_features_raw
# ============================================

import duckdb

# ============================================
# KONFIG
# ============================================

DB_PATH = "/home/ubuntu/db/forecast_db.duckdb"

# ============================================
# POŁĄCZENIE
# ============================================

con = duckdb.connect(DB_PATH)
print("[OK] Połączono z bazą")

# ============================================
# MARKET FEATURES
# ============================================

con.execute("""
DROP TABLE IF EXISTS market_features_raw
""")

con.execute("""
CREATE TABLE market_features_raw AS

WITH pk5_latest AS (
    SELECT *
    FROM (
        SELECT
            *,
            ROW_NUMBER() OVER (
                PARTITION BY business_date, period
                ORDER BY snapshot_date DESC
            ) AS rn
        FROM pk5
    )
    WHERE rn = 1
),

fixing_latest AS (
    SELECT *
    FROM (
        SELECT
            *,
            ROW_NUMBER() OVER (
                PARTITION BY delivery_date, H
                ORDER BY fixing_date DESC
            ) AS rn
        FROM fixing_prices
    )
    WHERE rn = 1
)

SELECT
    p.plan_dtime AS Timestamp,

    s.f1_price_PLN   AS Fixing1,
    s.sdac_price_PLN AS Fixing2,

    p.grid_demand_fcst AS "Prognozowane zapotrzebowanie sieci [MW]",
    p.fcst_pv_tot_gen  AS "Generacja PV [MW]",
    p.fcst_wi_tot_gen  AS "Generacja wiatrowa [MW]",
    p.planned_exchange AS "Wymiana systemowa [MW]",
    p.fcst_unav_energy AS "Niedyspozycyjność sieci [MW]",

    (
        p.grid_demand_fcst
        - p.fcst_pv_tot_gen
        - p.fcst_wi_tot_gen
    ) AS RL

FROM pk5_latest p
LEFT JOIN fixing_latest s
    ON s.delivery_date = CAST(p.plan_dtime AS DATE)
   AND s.H = EXTRACT(HOUR FROM p.plan_dtime) + 1

ORDER BY p.plan_dtime
""")

print("[OK] market_features_raw utworzona")

# ============================================
# ZAMKNIĘCIE
# ============================================

con.close()
print("[INFO] market_features zakończony")
