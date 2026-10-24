"""Load the referral-network export into raw.network, plus raw.grades and raw.campaign.

Only business fields are kept: password hashes, RIB (bank), CIN (national ID) and any other
account fields are dropped here, before anything is stored (a fetcher should already whitelist them,
this is a second line of defence for hand-made dumps).
"""
import json
import os

import duckdb

NETWORK_COLUMNS = [
    ("first_name", "varchar"), ("last_name", "varchar"), ("phone", "varchar"), ("phone2", "varchar"),
    ("boutique_code", "varchar"), ("numero_membre", "varchar"), ("grade", "varchar"),
    ("is_blocked", "boolean"), ("personal_sales_ttc", "double"), ("pending_personal_sales_ttc", "double"),
    ("team_sales_ttc", "double"), ("pending_team_sales_ttc", "double"),
    ("birth_date", "varchar"), ("grade_id", "integer"), ("user_id", "integer"), ("sponsor_id", "integer"),
    ("depth", "integer"), ("direct_count", "integer"), ("downline_sales_ttc", "double"),
    ("pending_downline_sales_ttc", "double"), ("grade_at_start", "integer"), ("eligible_grade", "integer"),
    ("is_promoted", "boolean"), ("personal_referrals", "integer"),
]
COLUMNS = [c for c, _ in NETWORK_COLUMNS]
GRADE_COLUMNS = [("id", "integer"), ("name", "varchar"), ("sort_order", "integer"), ("objective", "double"),
                 ("min_vente_perso", "double"), ("director_min_ca", "double"),
                 ("required_confirmed_directors", "integer"), ("same_rank_earning_threshold", "double")]
CAMPAIGN_COLUMNS = [("id", "integer"), ("name", "varchar"), ("start_date", "varchar"), ("end_date", "varchar"),
                    ("is_active", "boolean"), ("is_finalized", "boolean")]


def flatten(item: dict) -> tuple:
    user = item["user"]
    progress = (item.get("progresses") or [{}])[0] or {}
    return (
        user.get("firstName"), user.get("lastName"),
        user.get("phoneNumber"), user.get("phoneNumber2"),
        user.get("boutiqueCode"), user.get("numeroMembre"),
        (user.get("grade") or {}).get("name"), bool(user.get("isBlocked")),
        progress.get("personalSalesTTC"), progress.get("pendingPersonalSalesTTC"),
        progress.get("teamSalesTTC"), progress.get("pendingTeamSalesTTC"),
        user.get("birthDate"), user.get("gradeId"), item.get("userId"), item.get("sponsorId"),
        item.get("depth"), item.get("directCount"), progress.get("downlineSalesTTC"),
        progress.get("pendingDownlineSalesTTC"), progress.get("gradeAtStart"), progress.get("eligibleGrade"),
        progress.get("isPromoted"), progress.get("personalReferrals"),
    )


def _table(con, name, columns, rows):
    con.execute("create schema if not exists raw")
    con.execute(f"create or replace table raw.{name} ({', '.join(f'{c} {t}' for c, t in columns)})")
    if rows:
        con.executemany(f"insert into raw.{name} values ({','.join('?' * len(columns))})", rows)
    return len(rows)


def _read(path):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}                                        # these exports are optional


def load_network(con: duckdb.DuckDBPyConnection, path: str) -> int:
    doc = _read(path)
    items = doc.get("data", [])
    c = doc.get("campaign") or {}
    _table(con, "campaign", CAMPAIGN_COLUMNS,
           [(c.get("id"), c.get("name"), c.get("startDate"), c.get("endDate"),
             c.get("isActive"), c.get("isFinalized"))] if c else [])
    return _table(con, "network", NETWORK_COLUMNS, [flatten(i) for i in items])


def load_grades(con: duckdb.DuckDBPyConnection, path: str) -> int:
    rows = [(g.get("id"), g.get("name"), g.get("sortOrder"), g.get("objectiveGrade"), g.get("minVentePerso"),
             g.get("directorMinCa"), g.get("requiredConfirmedDirectors"), g.get("sameRankEarningThreshold"))
            for g in _read(path).get("data", [])]
    return _table(con, "grades", GRADE_COLUMNS, rows)
