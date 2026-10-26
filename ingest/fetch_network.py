"""Fetch everything reachable from one or more ambassador accounts on the source system and save it raw.

For each account, logs in (POST /auth/login) and pulls:
  - the account's own profile (/auth/loadMe)
  - the active campaign (/mlm-campagne/compagne/active)
  - the full downline for that campaign (/mlm-referral/downline/{boutiqueCode}, paginated),
    including per-member sales progress (includeProgress=true) and grade detail (includeGrade=true)

By default, every account listed in accounts.json is fetched and merged into one member list,
deduplicated by user_id (a member can legitimately appear in more than one account's downline --
e.g. one account is upline of another). Depth/sponsor/path are relative to the viewing account, so
when a member is seen more than once the copy with the smallest depth (the more senior vantage
point) is kept; duplicate_members in the output reports how many were resolved this way. Pass
--label (repeatable) to fetch only specific accounts instead.

By explicit choice (2026-10-26), nothing is stripped from a member's own record: this includes
each member's password hash, RIB/CIN and verification tokens, exactly as the API returns them. The
output is written to CNP_DATA_DIR/downline_raw.json, which is gitignored and must stay that way --
this is the richest, most sensitive file the pipeline touches. Deciding what (if anything) of this
reaches the dashboard or the Sheet happens downstream, in ingest/load_network.py and the dbt
models, not here.

The API's base URL is never hardcoded here (see accounts.example.json / .env.example): set it in
.env as CNP_NETWORK_API_BASE, the same way ORG_NAME and TAILSCALE_IP are kept out of git.

Credentials: CNP_NETWORK_EMAIL / CNP_NETWORK_PASSWORD env vars for a single account, or
accounts.json (gitignored; see accounts.example.json for the shape: a list of
{"label", "email", "password"}) for one or many.
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


def _all_accounts(data_dir: str) -> list[dict]:
    path = _accounts_path(data_dir)
    if not path:
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _credentials(label: str | None, data_dir: str) -> tuple[str, str, str]:
    """Returns (label, email, password). label falls back to the matched/first account's own label,
    or "default" when there's no accounts.json at all (plain env-var credentials)."""
    env_email, env_password = os.environ.get("CNP_NETWORK_EMAIL"), os.environ.get("CNP_NETWORK_PASSWORD")
    accounts = _all_accounts(data_dir)
    if not accounts:
        if env_email and env_password:
            return label or "default", env_email, env_password
        sys.exit("No credentials: set CNP_NETWORK_EMAIL/CNP_NETWORK_PASSWORD or add accounts.json "
                 "(see accounts.example.json)")
    match = next((a for a in accounts if a.get("label") == label), accounts[0] if accounts else None)
    if not match:
        sys.exit(f"No account labelled {label!r} in {_accounts_path(data_dir)}")
    return match.get("label") or "default", match["email"], match["password"]


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


def fetch_account(base: str, label: str | None, data_dir: str) -> dict:
    """One account's own profile, active campaign and full downline."""
    account_label, email, password = _credentials(label, data_dir)
    token = login(base, email, password)
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

    return {"label": account_label, "me": me, "campaign": campaign, "members": members}


def merge_members(per_account_members: list[list[dict]]) -> tuple[list[dict], int]:
    """Dedup by userId across accounts, keeping the smallest-depth (most senior vantage point) copy.
    Returns (merged members, duplicates resolved)."""
    best: dict[int, dict] = {}
    duplicates = 0
    for members in per_account_members:
        for m in members:
            uid = m.get("userId")
            if uid is None:
                best[id(m)] = m                        # no stable id to dedup on: keep as-is
                continue
            current = best.get(uid)
            if current is None:
                best[uid] = m
            else:
                duplicates += 1
                if (m.get("depth") if m.get("depth") is not None else float("inf")) < \
                   (current.get("depth") if current.get("depth") is not None else float("inf")):
                    best[uid] = m
    return list(best.values()), duplicates


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--label", action="append", default=None,
                   help="accounts.json entry to fetch; repeatable. Default: every entry in accounts.json "
                        "(or the single CNP_NETWORK_EMAIL/PASSWORD account if there's no accounts.json).")
    args = p.parse_args()

    base = api_base()
    data_dir = os.environ.get("CNP_DATA_DIR", "data")
    labels = args.label or [a.get("label") for a in _all_accounts(data_dir)] or [None]

    fetched, failed = [], []
    for label in labels:
        try:
            fetched.append(fetch_account(base, label, data_dir))
            print(f"  {label or 'default'}: ok")
        except Exception as e:                        # one bad account must not lose the others
            failed.append(label)
            print(f"  {label or 'default'}: FAILED ({e})", file=sys.stderr)

    if not fetched:
        sys.exit("Every account failed to fetch; nothing written.")

    members, duplicates = merge_members([a["members"] for a in fetched])
    doc = {
        "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "accounts": [{"label": a["label"], "boutiqueCode": a["me"].get("boutiqueCode")} for a in fetched],
        "campaign": fetched[0]["campaign"],
        "members": members,
    }

    out_path = os.path.join(data_dir, "downline_raw.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print(f"Fetched {len(members)} unique network members from {len(fetched)} account(s) "
          f"({duplicates} duplicate(s) merged) -> {out_path}")
    if failed:
        print(f"{len(failed)} account(s) failed and were skipped: {', '.join(str(l) for l in failed)}",
              file=sys.stderr)


if __name__ == "__main__":
    main()
