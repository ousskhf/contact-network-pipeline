"""The test session must never reach the real data directory or the live Sheet."""
import os
from pathlib import Path

import duckdb
import pytest

from ingest import outreach


def test_no_setting_points_at_real_data_or_the_sheet():
    for name in ("CNP_DB", "CNP_OUTREACH", "CNP_EXPORT", "CNP_GOOGLE_CREDENTIALS"):
        assert "/data/" not in Path(os.environ[name]).resolve().as_posix() + "/", name
    for name in ("CNP_SHEET_ID", "CNP_SHEET_TAB", "ORG_NAME", "TAILSCALE_IP"):
        assert name not in os.environ, name
    assert not Path(os.environ["CNP_GOOGLE_CREDENTIALS"]).exists()
    assert os.environ["CNP_DATA_DIR"] == "fixtures"


def test_default_outreach_store_is_a_temp_file():
    assert Path(outreach.default_path()).resolve().is_relative_to(Path(os.environ["CNP_OUTREACH"]).resolve().parent)


@pytest.mark.parametrize("name", ["cnp.duckdb", "outreach.duckdb", "anything.duckdb"])
def test_opening_a_file_in_the_data_directory_fails(name):
    with pytest.raises(RuntimeError, match="real data"):
        duckdb.connect(f"data/{name}")


def test_memory_and_temp_databases_still_work(tmp_path):
    duckdb.connect(":memory:").close()
    duckdb.connect(str(tmp_path / "ok.duckdb")).close()
