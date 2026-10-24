# contact-network-pipeline

A small ELT pipeline for a contact list and a referral network (members with grades and
sales): load raw exports → clean and deduplicate with dbt → explore in a dashboard and a
shared Google Sheet. Built as a Data Engineering bootcamp project, replacing an earlier chain
of ad-hoc scripts.

**Contains no real data.** Real exports live in `data/` (gitignored); the repo
ships only synthetic fixtures. Contacts and network members are personal data —
keep real files and the warehouse out of git.

## Screenshots

All taken on the synthetic fixtures (`make demo`), so every name and number is fake. The UI is in French.

| To do today | Overview and data quality |
|---|---|
| ![To do](docs/screenshots/todo.png) | ![Overview](docs/screenshots/overview.png) |
| **Network tree** | **Grade progress** |
| ![Network tree](docs/screenshots/network-tree.png) | ![Grade progress](docs/screenshots/grade-progress.png) |

## Quickstart

Requires Docker. The web UIs listen on `127.0.0.1` only by default. They would hold personal data with real
exports, so do not expose them beyond your machine. To reach them from your other devices over Tailscale, set
`TAILSCALE_IP` in `.env` (gitignored, see `.env.example`): the ports then bind to that address only, never the
LAN, and the Homepage tile labels on the `dashboard` and `docs` services point at it. The URLs below use
`localhost`; swap in that address when it is set.

```
make build   # build the image once
make up      # start the dashboard and dbt docs (restart automatically)
make down    # stop them
```

| UI | URL | What it is |
|---|---|---|
| Dashboard | http://localhost:8501 | tabs: overview and data quality, network health, grade progress, birthdays, prospects, outreach editor; CSV downloads |
| Airflow | http://localhost:8092 (a shared Airflow platform, optional) | trigger or schedule `cnp_refresh` (the whole pipeline) |
| dbt docs | http://localhost:8091 | model documentation and lineage graph |

Other commands: `make demo` (pipeline on synthetic fixtures), `make run` (pipeline on `data/`,
same as triggering the DAG), `make test`, `make airflow-test` (run the DAG once on the platform, no scheduler),
`make logs`. Ports 8080/8081 are avoided on purpose (used by other local containers).

## Redo everything from the raw files

```
data/contacts.vcf     phone/Google Contacts vCard export   (or data/contacts.csv, Google CSV format)
data/downline.json    referral-network export, optional (same shape as fixtures/downline.json)
make build && make run
```

`make run` loads the raw files, runs every dbt model and test, and writes
**`data/contact_tracker.csv`**, the tracker sheet (one row per person plus network members
not in the contacts; Téléphone 1–3 plus "Autres numéros" for any further numbers; Email,
Pays/Région/Ville/Localité/Adresse, Profession, Grade/Actif; blank outreach columns for manual tracking). Import that
CSV into Google Sheets. `make demo` does the same on fixtures. A run takes seconds and is
idempotent: raw tables are replaced each time.

Not automated: exporting the contacts from the phone and the Sheets import.
Review after each run: the dbt `phone_format` warning (entries that aren't plausible
numbers, e.g. short codes) and the merge table in the dashboard.

## Lineage

```
contacts.csv ─► raw.contacts ─► stg_contacts ────────┐
                              └► stg_contact_phones ─┴► int_contact_person ─► dim_person
                                     (one row per        (connected          bridge_person_phone
                                      number, any N)      components)        merge_audit
downline.json ─► raw.network ─► stg_network ──────────────────────────────► fct_network_membership
 (password/RIB/CIN dropped                                                          │
  at load time)                                                          app/dashboard.py (Streamlit)
```

| Layer | Where | Notes |
|---|---|---|
| raw | `ingest/` | Stored untouched (all text). Sensitive API fields are dropped before storage. |
| staging | `dbt/models/staging/` | Unpivots every `Phone N - Value` column; `normalize_phone` macro strips separators and a leading +216/00216. |
| marts | `dbt/models/marts/` | People = contact rows linked by a shared normalised number. `tracker_export` is the sheet. |
| tests | `dbt/tests/`, `tests/` | No number lost, no contact lost, unique pairs, phone format; loader and dashboard tests. |

## Network tree

The **Arbre du réseau** tab draws who recruited whom from the export's sponsor links: an
interactive ECharts tree (click to open or close a branch, wheel to zoom, tooltip with grade, activity,
team sales, directs and branch size) plus a Plotly treemap whose block area is the size of each branch.
Pick a member in *Branche* to see only their branch (this is also how you see your own branch). Colours
run light to dark with the grade; inactive members are grey hollow circles. ECharts is downloaded when
the image is built (pinned by checksum) and embedded in the page, so nothing is loaded from the internet at
runtime. After pulling a change that touches the models, run `make build && make run`.

## Grade progress and birthdays

The network export can also carry the grade ladder (`data/grades.json`), the active campaign and, per
member, birth date, campaign sales (confirmed and pending: personal, team, downline), the source's own
`isPromoted` / `eligibleGrade` flags and the grade at campaign start. dbt models: `dim_grade`,
`dim_campaign`, and a richer `fct_network_membership`.

- **Progression tab:** the published ladder, and each member's sales against the *next* grade's published
  objective. The source does not say which sales figure an objective measures, so you choose it
  (personal / team / downline, with or without pending) and the percentage is indicative, not the
  official promotion rule. Sales are per campaign, so the early days of a campaign show little.
- **Anniversaires tab:** upcoming birthdays of network members (today / 7 / 30 / 90 days) with a WhatsApp
  link that only opens a chat. Only members who filled in a birth date on the source appear, and phone
  contacts have none. The tracker CSV gets an `Anniversaire` column for network members.

## Outreach tracking (the one thing you type)

The dashboard's **Suivi** tab lets you edit status, contact dates, follow-up date, who contacted,
interest and notes for each person. Entries are saved in `data/outreach.duckdb`, separate from the
warehouse, so re-running or rebuilding the pipeline never erases them. They are keyed by phone and
matched through any of a person's numbers (so a re-export or re-ordered numbers is fine), and
`contact_tracker.csv` is exported with them filled in, so importing it into Sheets keeps your work.
**This file cannot be regenerated from the raw exports. Back it up** (copy `data/outreach.duckdb`).
If a number disappears from your contacts, its entry is reported as unmatched, not deleted.

## Network input

`ingest/load_network.py` reads `downline.json` (and `grades.json`) from the data folder. Only whitelisted
business fields are stored: password hashes, bank details and national IDs are dropped in memory at load
time and never reach the warehouse. Producing that file is up to you; this repo ships no client for any
real system, only the synthetic `fixtures/downline.json` that documents the expected shape.

## Shared Sheet (two-way sync)

`ingest/sheet_sync.py` keeps a Google Sheet in step with the pipeline, so a second person can edit it. It holds
every person: the contacts and the source network members who are not in the contacts (with their Grade and Actif,
which the source data always overwrites). Rows are matched by phone number (leading zeros ignored); network-only
members also use their name, because members can share a phone (a sponsor's, for example). Per cell,
the last synced value is the base: if only the Sheet changed, it is stored in `data/outreach.duckdb`; if only
the dashboard changed, it is written to the Sheet; if both changed, the Sheet wins and the conflict is printed.
Name, phones and the import notes belong to the pipeline. Corrections to country, region, town, locality, address, e-mail and profession are
kept as overrides of the phone export. Columns added in the Sheet are stored but not shown in the dashboard.
People new to the pipeline are appended; rows typed by hand in the Sheet are left alone.
A Sheet that still has the old `Ville/Région` column (or the short-lived four-column layout, where `Localité` held
the town) is migrated by the next sync: that column is renamed `Ville` (its values and position are kept), `Pays` and
`Région` are inserted before it, `Localité` and `Adresse` after it, and stored corrections move to `Ville`. Re-run
`make format-sheet` afterwards.

Setup (once): create a Google service account with the Sheets API enabled, save its key as
`data/google-service-account.json` (gitignored), share the Sheet with the account's e-mail as editor, and
set `CNP_SHEET_ID` (the long id in the Sheet's URL; for Airflow, the Variable `cnp_sheet_id`). Copy
`.env.example` to `.env` to set it and the other `CNP_*` variables; Docker Compose reads `.env` automatically.
`make sync` runs it once; the DAG runs it daily after `dbt_build`. Without the id or the key it is skipped.
Back up `data/outreach.duckdb` as before: it now also holds the last synced values.

`make format-sheet` (`ingest/sheet_format.py`) sets up the Sheet for editing: dropdowns (status, interest type, gender,
language, age range, and the location chain below), date pickers, status colours, overdue follow-ups in red, frozen header, filter, greyed
pipeline columns with a warning, and a "Mode d'emploi" tab. It can be run again; it never changes cell values (except the help and list tabs).

**Location dropdowns.** `Pays` accepts only Tunisie and `Région` only the 24 governorates. `Ville` and `Localité` are
chained to them: the Ville list of a row shows only the villes (délégations) of its Région, and its Localité list only
the localités of its Ville (66 at most), so the lists stay short enough for a tablet. The Sheets API cannot do this
(it ignores `INDIRECT` in validation rules, and one rule plus one helper formula per row made the Sheet too slow), so a
small script does it:

1. `make format-sheet` writes the hidden `Lieux` tab (région, ville, localité, one row per localité).
2. In the Sheet, **Extensions > Apps Script**, paste `apps_script/Localites.gs` (replacing any earlier version) and
   save. It is free and sends nothing anywhere.
3. In the editor's function list, run `refreshAll` once and accept the authorisation Google asks for (Review
   permissions, your account, Advanced, Go to the project, Allow: the warning is normal for your own script), then run
   `installTrigger` once and accept again. `refreshAll` gives every row its lists; `installTrigger` adds a nightly
   refresh at about 3 am, after the sync.
4. Afterwards, choosing a Région gives the Ville cell of that row its list, and choosing a Ville gives the Localité cell
   its list, about 3 seconds later (the script reads the `Lieux` tab). Pick them in that order. Other values can still
   be typed (a warning). With no Région, a Ville that exists in only one région still gets its localités.

Ville names are plain ("Soukra"). The first version prefixed them with the région ("Ariana - Soukra"); the next sync
rewrites such cells and stored values (`strip_region`). The sync writes through the API, which does not fire the script,
so a Ville that arrives from the dashboard gets its Localité list at the next nightly refresh (or when `refreshAll` is
run, or when a Région or Ville is edited in the Sheet). The script also has an `onOpen` that adds a **Lieux** menu and
refreshes on open, but in our test it did not fire by itself (only from the editor), so nothing relies on it. Without
the script, Ville and Localité are free text. The Apps Script "Executions" page lists every run and any error.

`Adresse` is free text. The data is `ingest/tunisia_locations.json` (24 régions, 257 délégations, 4 671 localités),
compiled from the postal-code tables of La Poste tunisienne as published on tuniscope.com (16 governorates) and
worldpostalcode.com (the other 8, Manouba completed from both), so some places are missing and some names are spelled
differently from one governorate to the next (accents, "Cite"/"Cité"). To refresh or complete it, edit the JSON and run
`make format-sheet` again.

## Orchestration

`dags/cnp_refresh.py` runs on a shared Airflow platform (`AIRFLOW_PLATFORM`, default `../airflow-platform`, mounted
through its `docker-compose.projects.yml`; set `CNP_HOST_PROJECT` to this folder's host path). Each task starts this project's image
(`cnp-app`) with `DockerOperator`, so Airflow carries none of our dependencies; run
`make build` after changing `requirements.txt`. `@daily`, no catch-up: `check_inputs` → `load_raw` →
`dbt_build` → `export_tracker`. A failing dbt test fails the run. It reads `fixtures/` by default;
the Airflow Variable `cnp_data_dir` selects the folder (`data` for real exports).
DuckDB allows one writer, so don't refresh while the dashboard holds the file
open for a long query.

## Design decisions

- **One row per number** (`bridge_person_phone`) instead of Phone/Phone 2/Phone 3
  columns. The old tracker had three phone columns and silently dropped a
  fourth number; here there is no cap, and `no_phone_lost` enforces it.
- **Shared number = same person.** Matches the old pipeline, but two relatives
  sharing a phone get merged. `merge_audit` (and the dashboard table) lists every
  merge so they can be reviewed.
- **Only valid numbers merge people.** Short codes or entries with letters are kept in
  the bridge with `is_valid = false` (and reported as a dbt warning) but never link two
  contacts, so two people saved with the same short code stay separate.
- **Typos are not fixed.** Numbers one digit apart stay separate; there is no
  fuzzy matching.
- **Location in five columns.** `Pays`, `Région`, `Ville`, `Localité`, `Adresse`, wide to precise. The phone export only
  has country, region, city and street: `Pays` is the address country, `Région` its region, `Ville` its city and
  `Adresse` its street. `Localité` (a cité or quartier inside a ville) is never in a phone export, so it is filled
  by hand in the Sheet. Phone exports often keep the whole address as free text in the street field, so a trailing
  ", Tunisia" / "/Egypt" there is read as the country (`normalize_country`, which knows Tunisie and Égypte; other
  names are kept as typed) and a street that is only a country name is empty. With no city and no region, the street
  is also the `Ville`. Nothing is guessed beyond that: a missing country stays empty.
- **DuckDB** keeps the warehouse a single local file, with no server to run.

## Layout

```
ingest/     raw loaders (contacts CSV, network JSON)
dbt/        staging + mart models, macros, singular tests
app/        Streamlit dashboard and its queries
dags/       Airflow DAG
apps_script/ script pasted once into the Sheet (Localité dropdown)
fixtures/   synthetic data and generator (python fixtures/generate.py)
data/       real inputs and warehouse (gitignored)
```

## Next

Cloud deployment and infrastructure as code.
