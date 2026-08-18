#!/bin/bash
SRC=/home/ubuntu/quant_energy
DEST=/home/ubuntu/backups/quant_energy
SNAP=$DEST/$(date +%Y-%m-%d_%H%M)

mkdir -p "$SNAP"

# Code files only — no parquets, no data dirs
cp "$SRC/app.py"    "$SNAP/"
cp "$SRC/shared.py" "$SNAP/"
cp "$SRC"/*.json    "$SNAP/" 2>/dev/null || true
cp "$SRC"/*.bat     "$SNAP/" 2>/dev/null || true

cp -r "$SRC/page_modules" "$SNAP/"
cp -r "$SRC/procedures"   "$SNAP/"

# energy_charts scripts only (not parquets)
mkdir -p "$SNAP/energy_charts"
cp "$SRC/energy_charts/"*.py "$SNAP/energy_charts/" 2>/dev/null || true

# Keep last 30 snapshots, delete older ones
ls -1dt "$DEST"/*/ | tail -n +31 | xargs rm -rf

echo "Backup done: $SNAP"
