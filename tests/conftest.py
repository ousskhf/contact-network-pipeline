import os
import subprocess
from pathlib import Path

import duckdb
import pytest

REAL_DATA = (Path(__file__).resolve().parent.parent / "data").resolve()
# Settings that point at real data or at the live Google Sheet; the tests never need them.
REAL_SETTINGS = ("CNP_SHEET_ID", "CNP_SHEET_TAB", "ORG_NAME", "TAILSCALE_IP")


def _inside_real_data(path) -> bool:
    try:
        return REAL_DATA in Path(path).resolve().parents or Path(path).resolve() == REAL_DATA
    except (OSError, TypeError, ValueError):
        return False


@pytest.fixture(scope="session", autouse=True)
def isolated_environment(tmp_path_factory):
    """Run the whole session on throwaway paths, with no Sheet and no organisation configured.

    The app and the pipeline fall back to data/... when a variable is missing, so a test that forgets one
    would read (or write) the real warehouse. Every path is set here, and opening anything under data/ fails.
    """
    scratch = tmp_path_factory.mktemp("isolated")
    mp = pytest.MonkeyPatch()
    mp.setenv("CNP_DATA_DIR", "fixtures")
    mp.setenv("CNP_DB", str(scratch / "cnp.duckdb"))
    mp.setenv("CNP_OUTREACH", str(scratch / "outreach.duckdb"))
    mp.setenv("CNP_EXPORT", str(scratch / "contact_tracker.csv"))
    mp.setenv("CNP_GOOGLE_CREDENTIALS", str(scratch / "no-service-account.json"))
    for name in REAL_SETTINGS:
        mp.delenv(name, raising=False)

    real_connect = duckdb.connect

    def guarded_connect(database=":memory:", *args, **kwargs):
        if isinstance(database, (str, os.PathLike)) and str(database) != ":memory:" and _inside_real_data(database):
            raise RuntimeError(f"a test tried to open real data: {database}")
        return real_connect(database, *args, **kwargs)

    mp.setattr(duckdb, "connect", guarded_connect)
    yield scratch
    mp.undo()


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("wh") / "cnp.duckdb")
    env = {**os.environ, "CNP_DB": path, "CNP_DATA_DIR": "fixtures"}
    subprocess.run(["python", "-m", "ingest.load_all"], env=env, check=True)
    subprocess.run(["dbt", "build", "--project-dir", "dbt", "--profiles-dir", "dbt"],
                   env=env, check=True, capture_output=True)
    return path
