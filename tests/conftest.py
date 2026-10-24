import os
import subprocess

import pytest


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("wh") / "cnp.duckdb")
    env = {**os.environ, "CNP_DB": path, "CNP_DATA_DIR": "fixtures"}
    subprocess.run(["python", "-m", "ingest.load_all"], env=env, check=True)
    subprocess.run(["dbt", "build", "--project-dir", "dbt", "--profiles-dir", "dbt"],
                   env=env, check=True, capture_output=True)
    return path
