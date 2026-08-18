# Trading / VAR Page: Functional Specification

## Overview
New page under the **Trading** section, named **VAR**. It calculates risk parameters (volatility of the relevant spread) from historical data, and uses them to flag — as a percentage of an accepted limit — how risky the current day's open position is. Two fully independent metrics: **SPOT** and **RB**. This is an **informational red-flag system**, not a blocking mechanism (decision on blocking deferred to a later iteration).

---

## Core Principles (already agreed)
- Two independent metrics, calculated and displayed separately: **SPOT** (F1/F2 vs SDAC spread) and **RB** (SDAC vs CEN spread).
- Both SPOT and RB positions reset daily — zero at the start of the day, closed/flat by end of day. No carry-over.
- V1 risk calculation: simplest possible method.
  - Volatility = standard deviation of the historical spread, per hour bucket (H01–H24).
  - Daily VaR = simple sum of per-hour risk contributions (no inter-hour correlation matrix in V1).
- Result is shown as **% of accepted limit** (e.g. "SPOT: 67% of limit"), not just a binary breach/no-breach flag.
- Calibration step (Section A) is **manual** — system proposes new parameters, user reviews and accepts. No silent background recalculation.
- Daily check (Section B) is **manual / button-triggered**, consistent with the existing "Calculate VAR" button planned on the Trading tab.

---

## Section A: Risk Parameter Calibration

**Trigger:** Manual buttons — e.g. **"Recalculate SPOT Parameters"** and **"Recalculate RB Parameters"** (same interaction pattern as the existing "Update FIX1 / Update FIX2" buttons).

**Lookback window:** Parameterized, not hardcoded. Editable control on the page (numeric input or dropdown, e.g. 30 / 60 / 90 / 180 days). **Default: 90 days.**

**Calculation, per hour bucket (H01–H24):**
- **SPOT:** historical spread = Fixing (F1 or F2) − SDAC, over the lookback window.
- **RB:** historical spread = SDAC − CEN, over the lookback window.
- Volatility = standard deviation of each per-hour spread series.

**Review & Accept workflow:**
- After clicking recalculate, system displays the **proposed** 24-row volatility table (one value per hour) — does not apply it automatically.
- User reviews and clicks **"Accept"** to make this the active parameter set used in Section B.
- Until accepted, the previously active parameter set remains in effect.
- Alongside the volatility table, user sets/confirms the **Accepted Daily VaR Limit** — one PLN value for SPOT, one for RB (defaults to last accepted value, editable).

**Stored per calibration (for audit/history):**
- Calibration date/time
- Lookback window used
- Per-hour volatility table
- Accepted limit values (SPOT, RB)

---

## Section B: Daily VAR Monitor

**Trigger:** Manual — a **"Calculate VAR"** button, available both on this page and on the main Trading tab (so the check can be run right where trades are placed, no navigation needed).

**Inputs:**
- Today's open position per hour, long/short volume in MW — pulled separately for SPOT and RB (reset daily, per agreed principle).
- Latest **accepted** volatility table from Section A.

**Calculation, per hour:**
```
Risk_hour = |Volume_MW| × σ_hour × z
```
- `σ_hour` = accepted volatility for that hour (from latest calibration)
- `z` = z-score for chosen confidence level (**open item — see below**)

**Daily aggregation (V1 — simplest method):**
```
Daily_VAR = Σ Risk_hour   (hours H01–H24, simple sum, no correlation between hours)
```
Calculated independently for SPOT and for RB.

**Limit comparison:**
```
% of limit = (Daily_VAR / Accepted_Limit) × 100
```

**Display:**
- Two values/gauges: **"SPOT: X% of limit"**, **"RB: Y% of limit"**
- Color band (suggested starting point, confirm before building):
  - 🟢 Green: < 70%
  - 🟡 Yellow: 70–100%
  - 🔴 Red: > 100%
- Per-hour breakdown table showing: hour, position (MW, long/short), volatility used, risk contribution (PLN) — so the user can see *why* the flag is raised and which hour is driving it.
- Last calibration date and lookback window shown for context (so it's clear which parameter set is currently active).

---

## Open Items Requiring a Decision

1. **Confidence level / z-score** — 95% (z ≈ 1.645) or 99% (z ≈ 2.33)? This directly scales the Daily VAR number.
2. **Color band thresholds** — the 70% / 100% breakpoints above are a starting suggestion, not final.
3. **Fixing selection for SPOT spread** — should the calibration use F1 only, F2 only, or be selectable?
4. **Accepted Limit input** — simple editable PLN field, or does it need its own confirmation/audit step separate from the volatility table acceptance?

---

## Answers to Your Two Questions

**Manual vs. automatic:** Manual for both sections. Section A (calibration) matches the "system proposes, I accept" workflow already agreed — automatic background recalculation would change risk parameters without your awareness, which defeats the purpose of a deliberate weekly review. Section B (daily check) stays button-triggered, consistent with the "Calculate VAR" button already planned on the Trading tab — a deliberate look at risk rather than a constantly-shifting background number.

**Hardcoded vs. parameterized lookback window:** Parameterized, default 90 days. Implementation cost is low (just a date-range input feeding the historical query), and the flexibility is genuinely useful early on — you'll want to compare 30/60/90/180-day windows to sanity-check that the model behaves sensibly before trusting its output. Hardcoding can be revisited later if one window proves clearly sufficient.
