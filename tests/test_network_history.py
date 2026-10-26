"""The history snapshot: a changed member gets a new row (old one closed), an unchanged member
doesn't. Runs its own two-load pipeline (fixtures mutated between loads), so it can't use the
shared `db` fixture from conftest.py (built once, static)."""
import json
import os
import shutil
import subprocess

import duckdb
import pandas as pd
import pytest


@pytest.fixture
def two_day_db(tmp_path):
    """Loads fixtures/ twice into the same warehouse, with member 500's personalSalesTTC bumped
    by 500 on the second load, simulating two nightly runs. Returns the duckdb path."""
    data_dir = tmp_path / "fixtures"
    shutil.copytree("fixtures", data_dir)
    db = str(tmp_path / "cnp.duckdb")
    env = {**os.environ, "CNP_DATA_DIR": str(data_dir), "CNP_DB": db}

    def run():
        subprocess.run(["python", "-m", "ingest.load_all"], env=env, check=True)
        subprocess.run(["dbt", "build", "--project-dir", "dbt", "--profiles-dir", "dbt"],
                       env=env, check=True, capture_output=True)

    run()                                              # day 1

    doc = json.loads((data_dir / "downline.json").read_text())
    member = next(m for m in doc["members"] if m["userId"] == 500)
    member["progresses"][0]["personalSalesTTC"] = str(
        float(member["progresses"][0]["personalSalesTTC"]) + 500)
    (data_dir / "downline.json").write_text(json.dumps(doc))

    run()                                              # day 2
    return db


def test_changed_member_gets_a_new_row_unchanged_members_dont(two_day_db):
    con = duckdb.connect(two_day_db, read_only=True)
    try:
        total = con.execute("select count(*) from main.fct_network_history").fetchone()[0]
        current = con.execute(
            "select count(*) from main.fct_network_history where valide_au is null").fetchone()[0]
        n_members = con.execute("select count(*) from main.stg_network").fetchone()[0]
        assert current == n_members                    # exactly one current row per member
        assert total == n_members + 1                   # one extra: member 500's closed-out old row

        rows = con.execute(
            "select personal_sales_ttc, valide_du, valide_au from main.fct_network_history "
            "where user_id = 500 order by valide_du").df()
        assert len(rows) == 2
        assert rows["personal_sales_ttc"].tolist() == [114.0, 614.0]
        assert pd.notna(rows["valide_au"].iloc[0]) and rows["valide_au"].iloc[0] == rows["valide_du"].iloc[1]
        assert pd.isna(rows["valide_au"].iloc[1])        # the new row is current
    finally:
        con.close()


def test_one_current_row_dbt_test_passes(two_day_db):
    r = subprocess.run(
        ["dbt", "test", "--project-dir", "dbt", "--profiles-dir", "dbt", "--select", "network_history_one_current_row"],
        env={**os.environ, "CNP_DB": two_day_db}, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:]
