# ============================================

# UPDATE OTF TGE EE -> DuckDB (OVH, standalone)

# ============================================

 

import duckdb

import pandas as pd

import datetime as dt

import requests

from io import StringIO

import re

import time

import random

 

# ============================================

# KONFIG

# ============================================

 

DB_PATH = "/home/ubuntu/db/forecast_db.duckdb"

TABLE_NAME = "otf_tge_ee"

OTF_URL_TEMPLATE = "https://tge.pl/energia-elektryczna-otf?dateShow={dateShow}"

 

DEFAULT_HEADERS = {

    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",

    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",

    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",

    "Connection": "close",

}

 

NA_TOKENS = {"-", "—", "", None}

 

EXPECTED_COLS = [

    "date", "product_name", "dkr",

    "vol_mwh", "trades", "value_pln",

    "lop_mwh", "min_price", "max_price"

]

 

# ============================================

# HELPERY DAT

# ============================================

 

def is_business_day(d: dt.date) -> bool:

    return d.weekday() < 5

 

def previous_business_day(d: dt.date) -> dt.date:

    x = d - dt.timedelta(days=1)

    while not is_business_day(x):

        x -= dt.timedelta(days=1)

    return x

 

def business_days_between(start_date: dt.date, end_date: dt.date) -> list[dt.date]:

    days = []

    cur = start_date

    while cur <= end_date:

        if is_business_day(cur):

            days.append(cur)

        cur += dt.timedelta(days=1)

    return days

 

# ============================================

# HELPERY TGE

# ============================================

 

def build_otf_url(date_obj: dt.date) -> str:

    return OTF_URL_TEMPLATE.format(dateShow=date_obj.strftime("%d-%m-%Y"))

 

def fetch_html(url: str, timeout: int = 30, retries: int = 6, base_sleep: float = 1.2) -> str:

    last_err = None

    for attempt in range(1, retries + 1):

        try:

            with requests.Session() as s:

                s.headers.update(DEFAULT_HEADERS)

                r = s.get(url, timeout=timeout, allow_redirects=True)

                if r.status_code != 200:

                    raise RuntimeError(f"HTTP {r.status_code} dla URL: {url}")

                return r.text

        except Exception as e:

            last_err = e

            sleep_s = base_sleep * (1.6 ** (attempt - 1)) + random.uniform(0.0, 0.7)

            print(f"    [retry {attempt}/{retries}] {type(e).__name__}: {e} | sleep {sleep_s:.1f}s")

            time.sleep(sleep_s)

    raise RuntimeError(f"Nie udało się pobrać: {url} | last_err={last_err}")

 

def _format_pl_decimal(value: float) -> str:

    return f"{value:.2f}".replace(".", ",")

 

def fix_pln_mwh_price_columns(df: pd.DataFrame) -> pd.DataFrame:

    df = df.copy()

    price_cols = [c for c in df.columns if "(PLN/MWh)" in str(c)]

    for c in price_cols:

        def _fix(x):

            if x in NA_TOKENS:

                return pd.NA

            x = str(x).strip().replace(" ", "")

            if "," in x:

                return x

            try:

                v = float(x)

                if v >= 1000:

                    v /= 100

                return _format_pl_decimal(v)

            except Exception:

                return x

        df[c] = df[c].map(_fix)

    return df

 

def parse_tables_with_kontrakt(html: str) -> list[pd.DataFrame]:

    try:

        tables = pd.read_html(StringIO(html), flavor="lxml")

    except ValueError:

        return []

    out = []

    for df in tables:

        df.columns = [str(c).strip() for c in df.columns]

        if "Kontrakt" in df.columns:

            df = fix_pln_mwh_price_columns(df)

            df = df.astype("string")

            out.append(df)

    return out

 

def infer_segment_from_contract(contract_value: str) -> str:

    if contract_value in NA_TOKENS:

        return "UNKNOWN"

    s = str(contract_value).strip()

    if "_" in s:

        seg = s.split("_", 1)[0]

    else:

        seg = s.split(" ", 1)[0]

    return re.sub(r"\s+", "", seg) or "UNKNOWN"

 

def name_tables_by_segment(tables: list[pd.DataFrame]) -> dict[str, pd.DataFrame]:

    named = {}

    for i, df in enumerate(tables, start=1):

        key = infer_segment_from_contract(df["Kontrakt"].iloc[0]) if len(df) else f"table_{i}"

        if key in named:

            k = 2

            while f"{key}_{k}" in named:

                k += 1

            key = f"{key}_{k}"

        named[key] = df

    return named

 

def pl_text_to_float_series(s: pd.Series) -> pd.Series:

    s = s.astype("string").str.strip()

    s = s.replace(list(NA_TOKENS), pd.NA)

    s = s.str.replace(" ", "", regex=False).str.replace(",", ".", regex=False)

    return pd.to_numeric(s, errors="coerce")

 

def tables_to_flat(df_tables_by_segment: dict[str, pd.DataFrame], session_date: dt.date) -> pd.DataFrame:

    frames = []

    for _, df in df_tables_by_segment.items():

        tmp = df.copy()

        tmp = tmp[[c for c in tmp.columns if not str(c).startswith("Unnamed")]]

        kontr = tmp["Kontrakt"].str.lower()

        tmp = tmp[~kontr.str.startswith(("suma", "razem", "total"))]

 

        if "DKR (PLN/MWh)" not in tmp.columns:

            continue

 

        flat = pd.DataFrame({

            "date": session_date.strftime("%Y-%m-%d"),

            "product_name": tmp["Kontrakt"],

            "dkr": pl_text_to_float_series(tmp["DKR (PLN/MWh)"]),

            "vol_mwh": pl_text_to_float_series(tmp.get("Łączny wolumen obrotu (MWh)")),

            "trades": pl_text_to_float_series(tmp.get("Liczba transakcji")),

            "value_pln": pl_text_to_float_series(tmp.get("Łączna wartość obrotu (PLN)")),

            "lop_mwh": pl_text_to_float_series(tmp.get("Łączna liczba otwartych pozycji LOP (MWh)")),

            "min_price": pl_text_to_float_series(tmp.get("Kurs min. na sesji (PLN/MWh)")),

            "max_price": pl_text_to_float_series(tmp.get("Kurs maks. na sesji (PLN/MWh)")),

        })

 

        flat = flat.dropna(subset=["dkr"])

        frames.append(flat)

 

    if not frames:

        return pd.DataFrame(columns=EXPECTED_COLS)

 

    return pd.concat(frames, ignore_index=True).drop_duplicates(

        subset=["date", "product_name"], keep="last"

    )

 

def fetch_one_day_flat(session_date: dt.date) -> pd.DataFrame:

    html = fetch_html(build_otf_url(session_date))

    tables = parse_tables_with_kontrakt(html)

    named = name_tables_by_segment(tables)

    return tables_to_flat(named, session_date)

 

# ============================================

# MAIN

# ============================================

 

print("[INFO] Start update OTF TGE EE")

 

con = duckdb.connect(DB_PATH)

 

# 1. odczyt ostatniej daty z bazy

last_date_row = con.execute(f"SELECT MAX(date) FROM {TABLE_NAME}").fetchone()

if last_date_row is None or last_date_row[0] is None:

    raise ValueError(f"[ERROR] Tabela {TABLE_NAME} jest pusta lub brak kolumny date.")

 

last_date_in_db = pd.to_datetime(last_date_row[0]).date()

 

# 2. wyznaczenie targetu

today = dt.date.today()

target_end_date = previous_business_day(today)

 

print("[INFO] Dzisiaj:", today)

print("[INFO] Ostatnia data w bazie:", last_date_in_db)

print("[INFO] Target end date:", target_end_date)

 

# 3. lista dni do pobrania

if last_date_in_db >= target_end_date:

    dates_to_fetch = []

    print("[OK] Baza aktualna. Brak dni do pobrania.")

else:

    start_fetch = last_date_in_db + dt.timedelta(days=1)

    dates_to_fetch = business_days_between(start_fetch, target_end_date)

    print(f"[INFO] Dni do pobrania: {len(dates_to_fetch)}")

    if dates_to_fetch:

        print("[INFO] Zakres:", dates_to_fetch[0], "->", dates_to_fetch[-1])

 

# 4. pobranie danych

rows = []

errors = []

 

for i, d in enumerate(dates_to_fetch, start=1):

    try:

        print(f"[DOWNLOAD] {d} ({i}/{len(dates_to_fetch)}) ...", end="")

        df_day = fetch_one_day_flat(d)

        print(f" OK ({len(df_day)})")

        if not df_day.empty:

            rows.append(df_day)

        time.sleep(1.0 + random.uniform(0.0, 0.8))

    except Exception as e:

        print(" ERROR")

        errors.append((d, str(e)))

        time.sleep(2.0)

 

# 5. budowa df_new

if rows:

    df_new = pd.concat(rows, ignore_index=True)

else:

    df_new = pd.DataFrame(columns=EXPECTED_COLS)

 

df_new = df_new.reindex(columns=EXPECTED_COLS)

df_new["date"] = pd.to_datetime(df_new["date"], errors="coerce")

df_new["product_name"] = df_new["product_name"].astype("string")

for col in ["dkr", "vol_mwh", "trades", "value_pln", "lop_mwh", "min_price", "max_price"]:

    df_new[col] = pd.to_numeric(df_new[col], errors="coerce")

 

df_new = df_new.dropna(subset=["date", "product_name"])

df_new = df_new.drop_duplicates(subset=["date", "product_name"], keep="last").reset_index(drop=True)

 

print("[INFO] df_new wierszy:", len(df_new))

print("[INFO] błędy dni:", len(errors))

 

# 6. update bazy

if not df_new.empty:

    con.register("df_tmp_new", df_new)

 

    # usuń stare rekordy dla dni, które właśnie odświeżasz

    con.execute(f"""

        DELETE FROM {TABLE_NAME}

        WHERE date IN (SELECT DISTINCT date FROM df_tmp_new)

    """)

 

    # wstaw świeże rekordy

    con.execute(f"""

        INSERT INTO {TABLE_NAME} (

            date, product_name, dkr, vol_mwh, trades,

            value_pln, lop_mwh, min_price, max_price

        )

        SELECT

            date, product_name, dkr, vol_mwh, trades,

            value_pln, lop_mwh, min_price, max_price

        FROM df_tmp_new

    """)

 

    print(f"[OK] Zaktualizowano bazę o {len(df_new)} rekordów.")

else:

    print("[OK] Brak nowych danych do update.")

 

con.close()

 

if errors:

    print("[WARN] Dni z błędami:")

    for d, e in errors:

        print(f"  - {d}: {e}")

 

print("[INFO] Koniec update OTF TGE EE")
