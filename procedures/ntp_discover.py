"""
netztransparenz.de API — endpoint discovery script.
Run once to find the correct spot price endpoint path.

Usage:
    python procedures/ntp_discover.py
"""

import os
import sys
import requests
from datetime import date, timedelta

CLIENT_ID     = "cm_app_ntp_id_fed7cedbb22045b6b26eebef52f1df98"
CLIENT_SECRET = "ntp_eBBbHiFZ9kqvq3if3LBY"
TOKEN_URL     = "https://identity.netztransparenz.de/users/connect/token"
BASE_URL      = "https://ds.netztransparenz.de/api/v1"

YESTERDAY = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
TODAY     = date.today().strftime("%Y-%m-%d")

# Candidate paths to probe — sorted by most likely first
CANDIDATES = [
    "/Spotmarktpreise",
    "/SpotmarktpreisHourly",
    "/Spotmarktpreis",
    "/EpexSpot/DayAhead",
    "/EpexSpot",
    "/prices/Spotmarkt",
    "/prices/DayAhead",
    "/prices/spot",
    "/MarktpreisEpex",
    "/Marktpreis/Epex",
    "/EEG/Marktpraemie/Spotmarktpreis",
    "/DayAheadPrices",
    "/DayAhead",
]

PARAM_VARIANTS = [
    {"from": YESTERDAY, "to": TODAY},
    {"dateFrom": YESTERDAY, "dateTo": TODAY},
    {"startDate": YESTERDAY, "endDate": TODAY},
    {"date": YESTERDAY},
    {},
]


def get_token():
    r = requests.post(TOKEN_URL, data={
        "grant_type":    "client_credentials",
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }, timeout=20)
    if not r.ok:
        print(f"[ERROR] Token request failed: {r.status_code} {r.reason}", file=sys.stderr)
        sys.exit(1)
    token = r.json()["access_token"]
    print("[OK] Token acquired.\n")
    return token


def probe(token, path, params):
    url = BASE_URL + path
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        return r.status_code, r.text[:300]
    except Exception as e:
        return None, str(e)


def main():
    token = get_token()

    # Health check
    status, body = probe(token, "/health", {})
    print(f"Health: {status}  →  {body}\n")
    print("=" * 60)
    print("Probing candidate endpoints...\n")

    for path in CANDIDATES:
        for params in PARAM_VARIANTS:
            status, body = probe(token, path, params)
            param_str = "&".join(f"{k}={v}" for k, v in params.items())
            label = f"{path}?{param_str}" if params else path
            print(f"[{status}]  {label}")
            if status == 200:
                print(f"       >>> FOUND IT! Response preview: {body[:200]}")
            print()
            if status == 200:
                break   # found working params for this path


if __name__ == "__main__":
    main()
