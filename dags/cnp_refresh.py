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


def cnp_task(task_id: str, command: str, **extra_env: str) -> DockerOperator:
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
    )


with DAG(
    dag_id="cnp_refresh",
    schedule="@daily",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=5)},
    tags=["cnp"],
) as dag:
    # Soft-fail: a source-system outage or a credential issue must not block the rest of the refresh --
    # load_raw then falls back to yesterday's downline_raw.json. Skipped entirely against fixtures.
    # CNP_NETWORK_PASSWORD is an Airflow Variable (masked in logs/UI because its key contains "password").
    fetch_network = cnp_task(
        "fetch_network",
        "[ \"$CNP_DATA_DIR\" = fixtures ] || python -m ingest.fetch_network "
        "|| echo 'WARNING: network fetch failed, reusing last downline_raw.json'",
        CNP_NETWORK_API_BASE="{{ var.value.get('cnp_network_api_base', '') }}",
        CNP_NETWORK_EMAIL="{{ var.value.get('cnp_network_email', '') }}",
        CNP_NETWORK_PASSWORD="{{ var.value.get('cnp_network_password', '') }}",
    )
    check_inputs = cnp_task(
        "check_inputs",
        "test -f $CNP_DATA_DIR/contacts.vcf || test -f $CNP_DATA_DIR/contacts.csv",
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
