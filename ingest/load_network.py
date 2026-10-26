"""Load the referral-network export into raw.network, raw.grades and raw.campaign.

Reads the shape ingest.fetch_network.py writes ({"members": [...], "campaign": {...}, ...}), and also
accepts the older {"data": [...], "campaign": {...}} shape fixtures/downline.json still uses.

Only business fields are kept: password hashes, RIB (bank), CIN (national ID), the fiscal id and
verification tokens/codes are dropped here, before anything is stored -- a second line of defence,
since fetch_network.py's own raw JSON dump keeps everything by design. Every other field not broken out
into a typed column is preserved losslessly in the user_json/progress_json passthrough columns, so
nothing non-sensitive is lost even if the source adds fields.

Grades are derived from each member's embedded "grade" object (there's no separate grades-list
endpoint), deduplicated by grade id.
"""
import json
import os

import duckdb

SECRET_USER_KEYS = {
    "password", "resetCode", "resetCodeCreatedAt", "verificationToken", "verificationTokenExpiresAt",
    "verificationCode", "verificationCodeExpiresAt", "matriculeFiscal", "rib", "ribUrl", "cinNumber",
}

NETWORK_COLUMNS = [
    ("id", "integer"), ("user_id", "integer"), ("sponsor_id", "integer"), ("path", "varchar"),
    ("depth", "integer"), ("direct_count", "integer"), ("total_excluding_director_networks", "integer"),
    ("created_at", "varchar"), ("updated_at", "varchar"),
    ("first_name", "varchar"), ("last_name", "varchar"), ("email", "varchar"), ("reference", "varchar"),
    ("role", "varchar"), ("is_blocked", "boolean"), ("is_verified", "boolean"), ("is_verified_mlm", "boolean"),
    ("birth_date", "varchar"), ("boutique_code", "varchar"), ("numero_membre", "varchar"),
    ("referred_by_boutique_code", "varchar"), ("gender", "varchar"), ("phone", "varchar"), ("phone2", "varchar"),
    ("has_completed_welcome", "boolean"), ("cumulated_credit", "varchar"), ("company_id", "integer"),
    ("grade_id", "integer"), ("grade", "varchar"), ("confirmed_director_at", "varchar"),
    # sales progress for the member's current campaign (progresses[0] -- one entry per campaign fetched)
    ("personal_sales_ttc", "double"), ("pending_personal_sales_ttc", "double"),
    ("personal_sales_ht", "double"), ("pending_personal_sales_ht", "double"),
    ("personal_sales_net", "double"), ("pending_personal_sales_net", "double"),
    ("team_sales_ttc", "double"), ("pending_team_sales_ttc", "double"),
    ("team_sales_ht", "double"), ("pending_team_sales_ht", "double"),
    ("team_sales_net", "double"), ("pending_team_sales_net", "double"),
    ("downline_sales_ttc", "double"), ("pending_downline_sales_ttc", "double"),
    ("downline_sales_ht", "double"), ("pending_downline_sales_ht", "double"),
    ("downline_sales_net", "double"), ("pending_downline_sales_net", "double"),
    ("parainage_sales_ttc", "double"), ("pending_parainage_sales_ttc", "double"),
    ("parainage_sales_ht", "double"), ("pending_parainage_sales_ht", "double"),
    ("parainage_sales_net", "double"), ("pending_parainage_sales_net", "double"),
    ("grade_at_start", "integer"), ("eligible_grade", "integer"), ("is_promoted", "boolean"),
    ("personal_referrals", "integer"),
    # lossless passthrough for every user/progress field not broken out above (secrets excluded)
    ("user_json", "varchar"), ("progress_json", "varchar"),
]
COLUMNS = [c for c, _ in NETWORK_COLUMNS]

GRADE_COLUMNS = [
    ("id", "integer"), ("name", "varchar"), ("sort_order", "integer"), ("objective", "double"),
    ("min_vente_perso", "double"), ("director_min_ca", "double"),
    ("required_confirmed_directors", "integer"), ("same_rank_earning_threshold", "double"),
    ("group_bonus_rate", "double"), ("personal_discount", "double"), ("pd_activation_value", "double"),
    ("personal_discount_less", "double"), ("pd_activation_value_less", "double"),
    ("sponsor_bonus_rate", "double"), ("guest_commission_rate", "double"),
    ("base_override_json", "varchar"), ("depth_override_json", "varchar"),
]
CAMPAIGN_COLUMNS = [("id", "integer"), ("name", "varchar"), ("start_date", "varchar"), ("end_date", "varchar"),
                    ("is_active", "boolean"), ("is_finalized", "boolean")]


def _num(v):
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def flatten(item: dict) -> tuple:
    user = item.get("user") or {}
    progress = (item.get("progresses") or [{}])[0] or {}
    grade = user.get("grade") or {}
    clean_user = {k: v for k, v in user.items() if k not in SECRET_USER_KEYS}
    return (
        item.get("id"), item.get("userId"), item.get("sponsorId"), item.get("path"),
        item.get("depth"), item.get("directCount"), item.get("totalExcludingDirectorNetworks"),
        item.get("createdAt"), item.get("updatedAt"),
        user.get("firstName"), user.get("lastName"), user.get("email"), user.get("reference"),
        user.get("role"), bool(user.get("isBlocked")), user.get("isVerified"), user.get("isVerifiedMlm"),
        user.get("birthDate"), user.get("boutiqueCode"), user.get("numeroMembre"),
        user.get("referredByBoutiqueCode"), user.get("gender"), user.get("phoneNumber"), user.get("phoneNumber2"),
        user.get("hasCompletedWelcome"), user.get("cumulatedCredit"), user.get("companyId"),
        user.get("gradeId"), grade.get("name"), user.get("confirmedDirectorAt"),
        _num(progress.get("personalSalesTTC")), _num(progress.get("pendingPersonalSalesTTC")),
        _num(progress.get("personalSalesHT")), _num(progress.get("pendingPersonalSalesHT")),
        _num(progress.get("personalSalesNET")), _num(progress.get("pendingPersonalSalesNET")),
        _num(progress.get("teamSalesTTC")), _num(progress.get("pendingTeamSalesTTC")),
        _num(progress.get("teamSalesHT")), _num(progress.get("pendingTeamSalesHT")),
        _num(progress.get("teamSalesNET")), _num(progress.get("pendingTeamSalesNET")),
        _num(progress.get("downlineSalesTTC")), _num(progress.get("pendingDownlineSalesTTC")),
        _num(progress.get("downlineSalesHT")), _num(progress.get("pendingDownlineSalesHT")),
        _num(progress.get("downlineSalesNET")), _num(progress.get("pendingDownlineSalesNET")),
        _num(progress.get("parainageSalesTTC")), _num(progress.get("pendingParainageSalesTTC")),
        _num(progress.get("parainageSalesHT")), _num(progress.get("pendingParainageSalesHT")),
        _num(progress.get("parainageSalesNET")), _num(progress.get("pendingParainageSalesNET")),
        progress.get("gradeAtStart"), progress.get("eligibleGrade"), progress.get("isPromoted"),
        progress.get("personalReferrals"),
        json.dumps(clean_user, ensure_ascii=False), json.dumps(progress, ensure_ascii=False),
    )


def _grades_from_members(items) -> list:
    seen = {}
    for item in items:
        grade = (item.get("user") or {}).get("grade") or {}
        gid = grade.get("id")
        if gid is not None and gid not in seen:
            seen[gid] = grade
    return [(
        g.get("id"), g.get("name"), g.get("sortOrder"), _num(g.get("objectiveGrade")),
        _num(g.get("minVentePerso")), _num(g.get("directorMinCa")), g.get("requiredConfirmedDirectors"),
        _num(g.get("sameRankEarningThreshold")), _num(g.get("groupBonusRate")), _num(g.get("personalDiscount")),
        _num(g.get("pdActivationValue")), _num(g.get("personalDiscountLess")), _num(g.get("pdActivationValueLess")),
        _num(g.get("sponsorBonusRate")), _num(g.get("guestCommissionRate")),
        json.dumps(g.get("baseOverride") or {}, ensure_ascii=False),
        json.dumps(g.get("depthOverride") or {}, ensure_ascii=False),
    ) for g in seen.values()]


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
    items = doc.get("members", doc.get("data", []))   # fetch_network.py shape, or the older {"data": [...]}
    c = doc.get("campaign") or {}
    _table(con, "campaign", CAMPAIGN_COLUMNS,
           [(c.get("id"), c.get("name"), c.get("startDate"), c.get("endDate"),
             c.get("isActive"), c.get("isFinalized"))] if c else [])
    _table(con, "grades", GRADE_COLUMNS, _grades_from_members(items))
    return _table(con, "network", NETWORK_COLUMNS, [flatten(i) for i in items])
