#!/bin/bash
# Daily cron script — runs data pipelines for quant_energy app
# Crontab entries (add via: crontab -e):
#
#   0 4         * * * /home/ubuntu/quant_energy/procedures/cron_daily.sh night >> /home/ubuntu/quant_energy/logs/cron.log 2>&1
#   0 6         * * * /home/ubuntu/quant_energy/procedures/cron_daily.sh morning >> /home/ubuntu/quant_energy/logs/cron.log 2>&1
#   0 7         * * * /home/ubuntu/quant_energy/procedures/cron_daily.sh tso >> /home/ubuntu/quant_energy/logs/cron.log 2>&1
#   15 7        * * * /home/ubuntu/quant_energy/procedures/cron_daily.sh rmb >> /home/ubuntu/quant_energy/logs/cron.log 2>&1
#   0 7-21/2    * * * /home/ubuntu/quant_energy/procedures/cron_daily.sh cen_fast >> /home/ubuntu/quant_energy/logs/cron.log 2>&1
#   10 7        * * * /home/ubuntu/quant_energy/procedures/cron_daily.sh de_efde >> /home/ubuntu/quant_energy/logs/cron.log 2>&1
#   25 7        * * * /home/ubuntu/quant_energy/procedures/cron_daily.sh fc >> /home/ubuntu/quant_energy/logs/cron.log 2>&1

APP_DIR="/home/ubuntu/quant_energy"
PYTHON="$APP_DIR/venv/bin/python"
LOG_DIR="$APP_DIR/logs"
mkdir -p "$LOG_DIR"

echo "========================================"
echo "$(date '+%Y-%m-%d %H:%M:%S')  START [$1]"
echo "========================================"

cd "$APP_DIR"

if [ "$1" = "night" ]; then
    echo "--- de_prices (EPEX day-ahead, Electricity Maps) ---"
    $PYTHON procedures/de_prices.py

    echo "--- de_spot (EPEX day-ahead, netztransparenz.de, auto-backfill) ---"
    $PYTHON procedures/de_spot.py

elif [ "$1" = "morning" ]; then
    echo "--- tge_fixing (F1 + SDAC) ---"
    $PYTHON procedures/tge_fixing.py

    echo "--- rb_prices fast (CEN forecast for today) ---"
    $PYTHON procedures/rb_prices.py fast

    echo "--- rb_prices confirm (CEN F->H) ---"
    $PYTHON procedures/rb_prices.py confirm

    echo "--- ets_co2 (DEC26 + DEC27) ---"
    $PYTHON procedures/ets_co2.py

    echo "--- tge_otf_ee (OTF energy) ---"
    $PYTHON procedures/tge_otf_ee.py

    echo "--- tge_otf_gas (OTF gas) ---"
    $PYTHON procedures/tge_otf_gas.py

elif [ "$1" = "tso" ]; then
    echo "--- pk5_pipeline (PSE 5-day plan) ---"
    $PYTHON procedures/pk5_pipeline.py

    echo "--- pse_demand (KSE load actual + forecast) ---"
    $PYTHON procedures/pse_demand.py

elif [ "$1" = "cen_fast" ]; then
    echo "--- rb_prices fast load (CEN forecast, every 2h 07:00-21:00) ---"
    $PYTHON procedures/rb_prices.py fast

elif [ "$1" = "rmb" ]; then
    echo "--- rmb_pipeline (RMB ancillary market prices: FCR, aFRR, mFRR, RR) ---"
    $PYTHON procedures/rmb_pipeline.py

elif [ "$1" = "de_efde" ]; then
    echo "--- de_forecast_efde (DE-LU 48h forecast, energyforecast.de) ---"
    $PYTHON procedures/de_forecast_efde.py

elif [ "$1" = "fc" ]; then
    echo "--- fc_pipeline (Forward Curve generation, Procedure 2) ---"
    $PYTHON procedures/fc_pipeline.py cron

else
    echo "Usage: cron_daily.sh [night|morning|tso|rmb|cen_fast|de_efde|fc]"
    exit 1
fi

echo "$(date '+%Y-%m-%d %H:%M:%S')  DONE [$1]"
echo ""
