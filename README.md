# contact-network-pipeline

An ELT pipeline that turns a messy phone contact list and a referral-network export into one clean,
deduplicated view of every person I need to follow up with, explored in a dashboard and kept in step
with a shared Google Sheet. Built as a Data Engineering bootcamp project, replacing an earlier chain of
ad-hoc scripts.

This README explains why it is built the way it is. The repo contains **no real data**: contacts and
network members are personal data, so real exports and the warehouse stay out of git and every
screenshot below comes from synthetic fixtures (the UI is in French).

| To do today | Overview and data quality |
|---|---|
| ![To do](docs/screenshots/todo.png) | ![Overview](docs/screenshots/overview.png) |
| **Network tree** | **Grade progress** |
| ![Network tree](docs/screenshots/network-tree.png) | ![Grade progress](docs/screenshots/grade-progress.png) |

## The problem

I kept a contact tracker for people I follow up with, fed by two sources: my phone contacts and the
export of a referral network (who recruited whom, grades, sales). The earlier scripts had two problems
I could not live with:

- **Lost data.** The tracker had three phone columns and silently dropped a fourth number.
- **Duplicates.** The same person appears several times in a phone export, under different names and
  numbers, and merging them by hand does not scale.

So the goal was not a prettier sheet but a pipeline that can say what it did, and fails loudly when
it loses something.

## Architecture

```
contacts.vcf/csv ─► raw.contacts ─► stg_contacts ────────┐
                                  └► stg_contact_phones ─┴► int_contact_person ─► dim_person
                                         (one row per        (connected          bridge_person_phone
                                          number, any N)      components)        merge_audit
downline.json ─► raw.network ─► stg_network ──────────────────────────────────► fct_network_membership
                                                                                       │
                                                  dashboard (Streamlit) ◄── tracker_export ──► Google Sheet
```

| Layer | Role |
|---|---|
| raw | Loaded untouched, all text, so a bad rule downstream never costs the original. |
| staging | One row per phone number; separators and country prefixes normalised. |
| marts | People (contacts linked by a shared normalised number), the network, and the exported tracker. |
| tests | dbt tests on the data, pytest on the loaders, dashboard and sync. |

**Stack:** Python, DuckDB, dbt, Streamlit, Airflow (DockerOperator), Docker Compose, Google Sheets API.

## Key decisions, and why

**One row per phone number, not Phone 1/2/3 columns.** This fixes the dropped fourth number directly.
`bridge_person_phone` has no cap, and a dbt test, `no_phone_lost`, fails the build if any number
disappears.

**A shared number means the same person.** It is the one signal I trust, and it matches the old
behaviour. The cost is that two relatives sharing a phone get merged, so I made the cost visible:
`merge_audit` lists every merge and the dashboard shows it for review.

**Only valid numbers can merge people.** Short codes and entries with letters are kept, flagged
`is_valid = false` and reported as a dbt warning, but never link two contacts. Otherwise two unrelated
people saved with the same short code would collapse into one.

**No fuzzy matching.** Numbers one digit apart stay separate. A wrong merge is worse than a missed
one, because it hides a person, so I chose to under-merge and show the rest.

**Sensitive fields never reach the warehouse.** The network export carries password hashes, bank
details and national IDs. The loader whitelists business fields and drops the rest in memory at load
time, so there is nothing to leak later.

**Outreach notes live in their own database.** What I type (status, dates, notes) cannot be rebuilt
from the exports, so it sits in a separate DuckDB file. Re-running or rebuilding the warehouse never
touches it. Entries are keyed by phone and matched through any of a person's numbers, so a re-export
or re-ordered numbers is fine.

**Two-way sync with a shared Sheet, with clear ownership.** A second person edits the Sheet, so for each
cell the last synced value is the base: if only the Sheet changed, I keep it; if only the dashboard
changed, I write it out; if both changed, the Sheet wins and the conflict is printed. Name, phones and
import notes belong to the pipeline; corrections like town or e-mail are stored as overrides of the
phone export.

**Location in five columns (country, region, town, locality, address).** Phone exports keep the whole
address as free text, so the pipeline reads a trailing country name as the country and nothing more:
no guessing beyond that. Town and locality dropdowns are chained to the region from a Tunisian locations
table (24 regions, 257 delegations, 4,671 localities). The Sheets API cannot do dependent dropdowns, so
a small Apps Script does it.

**DuckDB.** One local file, no server to run, and fast enough for this volume. Its single-writer limit is
a known trade-off, handled by not refreshing while the dashboard holds a long query.

**Airflow runs the project's own image.** Each DAG task starts the project container with
`DockerOperator`, so Airflow carries none of its dependencies. The DAG runs daily:
`check_inputs → load_raw → dbt_build → export_tracker`, and a failing dbt test fails the run.

## What the dashboard is for

A "to do today" list of follow-ups, data-quality and merge review, the referral network as an
interactive tree, grade progress against the next grade's published objective, upcoming birthdays, and
the outreach editor. It is a view over the marts, not a second source of truth.

## Testing

68 pytest tests (loaders, vCard parsing, dashboard queries and launch, outreach, sheet sync and formatting,
locations) plus dbt tests that fail the build when a person or a number is lost or a pair is duplicated.
All of it runs on the synthetic fixtures, so the same suite can live in a public repo.

## Layout

```
ingest/       raw loaders and Google Sheet sync
dbt/          staging and mart models, macros, singular tests
app/          Streamlit dashboard
dags/         Airflow DAG
apps_script/  script pasted once into the Sheet (locality dropdown)
fixtures/     synthetic data and its generator
tests/        pytest suite
```

## Next

Cloud deployment and infrastructure as code.
