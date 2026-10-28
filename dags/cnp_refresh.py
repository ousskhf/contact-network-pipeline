"""Daily refresh: check inputs -> load raw -> dbt build (models + tests) -> sync the shared Sheet -> export tracker CSV.

Runs on a shared Airflow platform: every task starts the
project's own image (cnp-app) through DockerOperator, with the project folder bind-mounted
at /work, exactly like `make run`. Airflow itself carries none of the project's dependencies.

Runs against the Airflow Variable `cnp_data_dir` (fixtures by default, `data` for real exports).
A failing dbt test (e.g. a lost phone number) fails the run.
"""
import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.providers.docker.operators.docker import DockerOperator
from docker.types import Mount

IMAGE = "cnp-app:latest"
HOST_PROJECT = os.environ.get("CNP_HOST_PROJECT", "/opt/contact-network-pipeline")  # host path: the Docker daemon resolves the bind mount
DATA_DIR = "{{ var.value.get('cnp_data_dir', 'fixtures') }}"


def cnp_task(task_id: str, command: str, operator_args: dict | None = None, **extra_env: str) -> DockerOperator:
    return DockerOperator(
        task_id=task_id,
        image=IMAGE,
        command=["bash", "-c", command],
        working_dir="/work",
        user="1000:1000",
        mounts=[Mount(source=HOST_PROJECT, target="/work", type="bind")],
        mount_tmp_dir=False,
        auto_remove="success",
        environment={
            "CNP_DATA_DIR": DATA_DIR,
            "CNP_DB": "data/cnp.duckdb",
            "HOME": "/tmp",
            "PYTHONPATH": "/work",
            **extra_env,
        },
        **(operator_args or {}),
    )


with DAG(
    dag_id="cnp_refresh",
    schedule="@daily",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=5)},
    tags=["cnp"],
) as dag:
    # Retry policy: ingest.fetch_network already retries each request (3 tries, 1 s then 2 s backoff). If
    # an account still fails, it exits non-zero and keeps the previous downline_raw.json; the task is then
    # retried 3 more times with exponential backoff (10, 20, 40 min), so an outage of a few hours is
    # absorbed. Only when those run out is the task marked failed -- visibly, not as a silent success --
    # and check_inputs (trigger_rule all_done) still lets the refresh go on with yesterday's file.
    # Skipped entirely against fixtures.
    # CNP_NETWORK_PASSWORD is an Airflow Variable (masked in logs/UI because its key contains "password").
    fetch_network = cnp_task(
        "fetch_network",
        "[ \"$CNP_DATA_DIR\" = fixtures ] || python -m ingest.fetch_network",
        operator_args={
            "retries": 3,
            "retry_delay": timedelta(minutes=10),
            "retry_exponential_backoff": True,
            "max_retry_delay": timedelta(hours=1),
        },
        CNP_NETWORK_API_BASE="{{ var.value.get('cnp_network_api_base', '') }}",
        CNP_NETWORK_EMAIL="{{ var.value.get('cnp_network_email', '') }}",
        CNP_NETWORK_PASSWORD="{{ var.value.get('cnp_network_password', '') }}",
    )
    check_inputs = cnp_task(
        "check_inputs",
        "test -f $CNP_DATA_DIR/contacts.vcf || test -f $CNP_DATA_DIR/contacts.csv",
        operator_args={"trigger_rule": "all_done"},   # runs even if fetch_network used up its retries
    )
    load_raw = cnp_task("load_raw", "python -m ingest.load_all")
    dbt_build = cnp_task("dbt_build", "dbt build --project-dir dbt --profiles-dir dbt")
    # Soft-fail: a Google outage must not block the export. Skipped when no sheet id is set.
    sheet_sync = cnp_task(
        "sheet_sync",
        "python -m ingest.sheet_sync || echo 'WARNING: sheet sync failed, will retry on the next run'",
        CNP_SHEET_ID="{{ var.value.get('cnp_sheet_id', '') }}",
    )
    export_tracker = cnp_task(
        "export_tracker",
        "python -m ingest.export",
        CNP_EXPORT="data/contact_tracker.csv",
    )

    fetch_network >> check_inputs >> load_raw >> dbt_build >> sheet_sync >> export_tracker
