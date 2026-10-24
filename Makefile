# demo = synthetic fixtures; run = real data from ./data (gitignored)
RUN = UID=$$(id -u) docker compose run --rm app

AIRFLOW_PLATFORM ?= ../airflow-platform
PLATFORM = docker compose -f $(AIRFLOW_PLATFORM)/docker-compose.yml -f $(AIRFLOW_PLATFORM)/docker-compose.projects.yml

.PHONY: fixtures test demo run build up down logs airflow-test export sync format-sheet
build:
	docker compose build
fixtures:
	$(RUN) python fixtures/generate.py
test:
	$(RUN) pytest -q
demo: fixtures
	$(RUN) python -m ingest.load_all
	$(RUN) dbt build --project-dir dbt --profiles-dir dbt
	CNP_EXPORT=data/demo_tracker.csv $(RUN) python -m ingest.export
	$(RUN) dbt docs generate --project-dir dbt --profiles-dir dbt
run:
	CNP_DATA_DIR=data $(RUN) python -m ingest.load_all
	$(RUN) dbt build --project-dir dbt --profiles-dir dbt
	$(RUN) python -m ingest.export
	$(RUN) dbt docs generate --project-dir dbt --profiles-dir dbt
export:
	$(RUN) python -m ingest.export
sync:                      # two-way sync with the shared Google Sheet (needs CNP_SHEET_ID, see README)
	$(RUN) python -m ingest.sheet_sync
format-sheet:              # dropdowns, colours, frozen header and help tab on the shared Sheet
	$(RUN) python -m ingest.sheet_format
up:
	UID=$$(id -u) docker compose up -d --build dashboard docs
	@echo "Dashboard   http://localhost:8501"
	@echo "dbt docs    http://localhost:8091"
	@echo "Airflow     http://localhost:8092  (shared platform: $(AIRFLOW_PLATFORM))"
down:
	UID=$$(id -u) docker compose down
logs:
	UID=$$(id -u) docker compose logs -f --tail=50
airflow-test: build   # run the DAG once on the shared platform (needs it to be up), no scheduler
	$(PLATFORM) exec -T scheduler airflow dags test cnp_refresh
