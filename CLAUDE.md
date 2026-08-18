# Project: Quant Energy Trading App

Streamlit intraday/spot trading dashboard for the Polish energy market.

> **Environment note**: The local machine (`c:\Users\rlucz\OneDrive\Pulpit\Data\Aplikacja\`) is a **testing environment only**. OVH is the canonical production environment — all data, pipelines, and live trade data live there. When developing, pull fresh data from the server first (see "Data sync from server"), then test locally, then deploy `app.py` back to the server.

## Key files
- `app.py` — main Streamlit app (single file, ~6000 lines, all pages)
- `trades.json` — FixTrade entries
- `tso_trades.json` — TSOTrade entries
- `FixingPricesH.parquet` — TGE fixing prices (F1/SDAC hourly)
- `cds_params.json` — Coal Dark Spread model config (block efficiencies, ETS/coal/swap deltas)
- `ccs_params.json` — Clean Crack Spread model config (CCGT/OCGT technology parameters)
- `prices/` — market price parquets + pipeline scripts:
  - `EURPLN_Rate.parquet`, `pse_prices.parquet`, `RB_prices_H.parquet`, `pscmi.parquet`
  - `de_spot.parquet`, `ets_co2.parquet`, `tge_otf_gas.parquet`, `tge_otf_ee.parquet`
  - Pipeline scripts: `ets_co2.py`, `nbp_eurpln.py`, `de_spot.py`
- `PK5/` — PSE 5-day generation plan data (`pk5.parquet`, `pk5for.parquet`)
- `procedures/` — data pipeline scripts:
  - Run from Admin page: `tge_fixing.py`, `pse_prices.py`, `pk5_pipeline.py`, `tge_otf_ee.py`, `tge_otf_gas.py`
  - Run from Forecast page: `forecast.py`
  - Standalone (no UI trigger): `rb_prices.py`, `ntp_discover.py`
- `energy_charts/` — DE data pipeline scripts + parquets (`de_prices.parquet`, `de_totalload.parquet`, `de_netload.parquet`)
- `pics/` — UI assets (`icon2.png` app icon, `NJGT.jpg` login background)

## Pages (sidebar navigation)
- **Prices**: Prices, FixTrade, TSOTrade, P&L Dashboard, FixHeatmap, TSOHeatmap, PSE, German SPOT, PK5
- **Forecast**: Forecast, Plotting, Model Performance
- **Forward Market**: OTF/EE, OTF/Gas, ETS1, CurrentCDS, CurrentCCS, Coal, Compare
- **Admin**: Parquet, Logs, Admin, PSE_Viewer, CDS, CCS

## Auth
- Password: `qe2026`, 14-day cookie persistence via `extra_streamlit_components`
- Cookie name: `qe_auth`, value: `qe_ok_2026`

## Environment variables
- `FORECAST_DB_PATH` — DuckDB forecast database (default: `/home/ubuntu/db/forecast_db.duckdb`)
- `DE_FORE_PATH` — DE 72H price forecast parquet (default: `/home/ubuntu/data/de/DE_Price_72H_Forecast.parquet`)

## Production server (OVH)
- **SSH**: `ssh ubuntu@51.254.131.14` (password auth)
- **App directory**: `~/quant_energy/`
- **Deploy app**: `scp app.py ubuntu@51.254.131.14:~/quant_energy/app.py`
- **Restart service**: `ssh ubuntu@51.254.131.14 "sudo systemctl restart quant_energy"`
- **Domains**: `enpuls.pl`, `arvedi.pl`, `quan.energy` → port 8501
- **Nginx config**: `/etc/nginx/sites-available/enpuls`

## Data sync from server
See `procedura_kopiowania_danych_z_OVH.txt` for full SCP commands. Key directories to sync:
```
scp ubuntu@51.254.131.14:~/quant_energy/FixingPricesH.parquet .
scp ubuntu@51.254.131.14:~/quant_energy/trades.json .
scp ubuntu@51.254.131.14:~/quant_energy/tso_trades.json .
scp -r ubuntu@51.254.131.14:~/quant_energy/prices .
scp -r ubuntu@51.254.131.14:~/quant_energy/PK5 .
scp -r ubuntu@51.254.131.14:~/quant_energy/energy_charts .
```

## Run locally
```
start_app.bat
```
or
```
streamlit run app.py
```

## Deploy workflow
1. Test locally
2. `scp app.py ubuntu@51.254.131.14:~/quant_energy/app.py`
3. `ssh ubuntu@51.254.131.14 "sudo systemctl restart quant_energy"`
