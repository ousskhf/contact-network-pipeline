"""Fetch everything reachable from an ambassador's own account on the source system and save it raw.

Logs in (POST /auth/login), then pulls:
  - the account's own profile (/auth/loadMe)
  - the active campaign (/mlm-campagne/compagne/active)
  - the full downline for that campaign (/mlm-referral/downline/{boutiqueCode}, paginated),
    including per-member sales progress (includeProgress=true) and grade detail (includeGrade=true)

By explicit choice (2026-10-26), nothing is stripped: this includes each member's password
hash, RIB/CIN and verification tokens, exactly as the API returns them. The output is written
to CNP_DATA_DIR/downline_raw.json, which is gitignored and must stay that way -- this is the
richest, most sensitive file the pipeline touches. Deciding what (if anything) of this reaches
the dashboard or the Sheet happens downstream, in ingest/load_network.py and the dbt models,
not here.

The API's base URL is never hardcoded here (see accounts.example.json / .env.example): set it in
.env as CNP_NETWORK_API_BASE, the same way ORG_NAME and TAILSCALE_IP are kept out of git.

Credentials: CNP_NETWORK_EMAIL / CNP_NETWORK_PASSWORD env vars, or --label picks a matching entry
from accounts.json (gitignored; see accounts.example.json for the shape: a list of
{"label", "email", "password"}).
"""
import argparse
import json
import os
import sys
import time

import requests

PAGE_LIMIT = 100
MAX_RETRIES = 3


def api_base() -> str:
    base = os.environ.get("CNP_NETWORK_API_BASE", "")
    if not base:
        sys.exit("CNP_NETWORK_API_BASE is not set (see .env.example)")
    return base.rstrip("/")


def _accounts_path(data_dir: str) -> str:
    for candidate in (os.path.join(data_dir, "accounts.json"), "accounts.json"):
        if os.path.exists(candidate):
            return candidate
    return ""


def _credentials(label: str | None, data_dir: str) -> tuple[str, str]:
    email, password = os.environ.get("CNP_NETWORK_EMAIL"), os.environ.get("CNP_NETWORK_PASSWORD")
    if email and password:
        return email, password
    path = _accounts_path(data_dir)
    if not path:
        sys.exit("No credentials: set CNP_NETWORK_EMAIL/CNP_NETWORK_PASSWORD or add accounts.json "
                 "(see accounts.example.json)")
    with open(path, encoding="utf-8") as f:
        accounts = json.load(f)
    match = next((a for a in accounts if a.get("label") == label), accounts[0] if accounts else None)
    if not match:
        sys.exit(f"No account labelled {label!r} in {path}")
    return match["email"], match["password"]


def _get(base: str, url: str, headers: dict, params: dict | None = None) -> dict:
    for attempt in range(MAX_RETRIES):
        resp = requests.get(f"{base}{url}", headers=headers, params=params, timeout=30)
        if resp.status_code < 500:
            break
        time.sleep(2 ** attempt)                      # backoff on transient 5xx
    resp.raise_for_status()
    return resp.json()


def login(base: str, email: str, password: str) -> str:
    r = requests.post(f"{base}/auth/login", json={"email": email, "password": password}, timeout=20)
    r.raise_for_status()
    return r.json()["accessToken"]


def fetch_all(base: str, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    me = _get(base, "/auth/loadMe", headers)
    campaign = _get(base, "/mlm-campagne/compagne/active", headers)

    members, page, total_pages = [], 1, 1
    while page <= total_pages:
        params = {
            "includeUserData": "true", "includeProgress": "true", "includeGrade": "true",
            "campagneId": campaign["id"], "page": page, "limit": PAGE_LIMIT,
            "excludeDirectorNetworks": "false",
        }
        doc = _get(base, f"/mlm-referral/downline/{me['boutiqueCode']}", headers, params)
        members.extend(doc.get("data", []))
        total_pages = (doc.get("meta") or {}).get("totalPages", 1)
        page += 1

    return {
        "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "me": me,
        "campaign": campaign,
        "members": members,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--label", default=None, help="accounts.json entry to use (default: the first one)")
    args = p.parse_args()

    base = api_base()
    data_dir = os.environ.get("CNP_DATA_DIR", "data")
    email, password = _credentials(args.label, data_dir)
    token = login(base, email, password)
    doc = fetch_all(base, token)

    out_path = os.path.join(data_dir, "downline_raw.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print(f"Fetched {len(doc['members'])} network members (campaign {doc['campaign']['name']}) -> {out_path}")


if __name__ == "__main__":
    main()
