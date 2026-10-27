# contact-network-pipeline

A data pipeline and dashboard built with a member of a direct-selling company's sales network in
Tunisia, to support their day-to-day work: who to contact today, which members have gone inactive, and
how everyone is progressing towards the next grade. It merges their phone contacts with the network
export into one deduplicated list of people, never drops data silently, lists every merge for review,
and keeps sales, grades and activity over time. Because a spreadsheet is the tool they already know,
the same list lives in a shared Google Sheet that stays in step with the dashboard. It replaced a chain
of ad-hoc scripts.

The repository contains **no real data**. Contacts and network members are personal data, so real
exports and the warehouse stay out of git, and every screenshot below comes from synthetic fixtures.
The interface is in French, the language of its user.

| To do today | Overview and data quality |
|---|---|
| ![To do](docs/screenshots/todo.png) | ![Overview](docs/screenshots/overview.png) |
| **Network tree** | **Grade progress** |
| ![Network tree](docs/screenshots/network-tree.png) | ![Grade progress](docs/screenshots/grade-progress.png) |
| **Map by region** | **Route builder** |
| ![Map](docs/screenshots/carte.png) | ![Routes](docs/screenshots/trajets.png) |

## The problem

The person I built this for works with two lists that don't line up: the contacts on their phone, and
the export of their sales network (who recruited whom, grades, sales). They need to know who to contact
today, which members have gone quiet, and who is close to the next grade. The chain of scripts they had
before could not answer that reliably, for three reasons:

- **Lost data.** The tracker had three phone columns and silently dropped a fourth number.
- **Duplicates.** The same person appears several times in a phone export, under different names and
  numbers, and merging them by hand does not scale.
- **A phone number is a channel, not an identity.** Members give their number to people under them for
  deliveries, so one number can belong to several people, and matching the two lists on the number
  alone links the wrong people. The design decisions below show how this changed the pipeline.

So the goal was not a prettier sheet but a pipeline that can say what it did, and fails loudly when
it loses something.

## What it lets you do

The dashboard follows one rule: **information, then decision, then action.** Each screen shows only what
supports a decision, and each decision ends in something you can do from the same screen.

| Information | Decision | Action |
|---|---|---|
| Overdue follow-ups, and interested people with no follow-up date | Who to contact today | Open a WhatsApp chat in one tap (nothing is sent automatically), then record the outcome |
| Inactive members, ranked by the size of the branch that depends on them | Which members are worth reactivating | Contact them, or note them for replacement |
| Members at 60-99% of the next grade, with what is left to do | Who to help finish before the campaign ends | Contact them with a concrete target |
| Branch sizes, grade progress, and how sales, grade and activity changed over time | Where the network is growing or stalling | Choose which branch to support |
| People per region, and the people still to locate | Where to visit | Build a Google Maps route from the people chosen |
| Members not yet in the phone | Who to add to the contacts | Export them as a vCard |
| Birthdays in the next days | Who to greet | Open a WhatsApp chat |
| Status, dates and notes for each person | What happens next with each person | Record the status and the next follow-up date, which feeds the to-do lists |
| Merges and shared numbers | Which links to trust | Review them before relying on the data |

It is a view over the marts, not a second source of truth.

## Architecture

```
contacts.vcf/csv ─► raw.contacts ─► stg_contacts ────────┐
                                  └► stg_contact_phones ─┴► int_contact_person ─► dim_person
                                         (one row per        (connected          bridge_person_phone
                                          number, any N)      components)        merge_audit, merge_review
                                                                                       │
downline.json ─► raw.network ─► stg_network ─► phone_share ────────────────────────────┤
                                     │         (members per number)                    ▼
                                     └─────────────────────────────────► fct_network_membership
                                                                          (link_kind per member)
                                     └─────────────────────────────────► fct_network_history
                                                                          (one row per change)
                                                                                       │
                      dashboard (Streamlit) ◄──── tracker_export ──────────► Google Sheet
                      vCard export, Maps routes
```

| Layer | Role |
|---|---|
| raw | Loaded untouched, all text, so a bad rule downstream never costs the original. |
| staging | One row per phone number; separators and country prefixes normalised; a network field holding two numbers is split. |
| marts | People (contacts linked by a shared normalised number), the network with how each member links to a contact, its history, and the exported tracker. |
| tests | dbt tests on the data, pytest on the loaders, dashboard and sync, run in CI on every PR. |

**Stack:** Python, DuckDB, dbt, Streamlit, Airflow (DockerOperator), Docker Compose, Google Sheets API,
GitHub Actions.

## Data model

| Table | Grain | Key |
|---|---|---|
| `bridge_person_phone` | one row per person and number, no cap | person, number |
| `dim_person` | one row per merged contact person | `person_id` |
| `fct_network_membership` | one row per network member, current state | `user_id` (stable id from the source system) |
| `fct_network_history` | one row per member and change of state | `user_id`, `valide_du` to `valide_au` |
| `phone_share` | one row per number, with how many members use it | number |
| `tracker_export` | one row per contact person, plus members not in the contacts | phone, or phone and `user_id` for a member |

- **Linking a member to a contact** is done on the number, then classified by `link_kind`:
  `name_match` when the contact's name fits the member's, `same_number` when only the number does (a
  shared number, so probably someone else's contact), and empty when there is no link.
- **History** keeps every state a member has had (sales, grade, activity) with a validity range, so a
  change shows up as a new row instead of overwriting the old one.
- **Bad data** is kept and flagged, not dropped: invalid numbers carry `is_valid = false`, merges are
  listed in `merge_audit`, and merged people whose names disagree are listed in `merge_review`.

## Key decisions, and why

**One row per phone number, not Phone 1/2/3 columns.** This fixes the dropped fourth number directly.
`bridge_person_phone` has no cap, and a dbt test, `no_phone_lost`, fails the build if any number
disappears.

**A shared number merges contacts, but only suggests a link to a member.** Among phone contacts a shared
number is the one signal I trust, and it matches the old behaviour. The cost is that two relatives
sharing a phone get merged, so I made the cost visible: `merge_audit` lists every merge and the dashboard
shows the ones whose names disagree for review. For network members I started with the same rule and
revised it: many members share a number, so a match on the number alone is now marked `same_number`,
listed for review, and such a member is offered in the vCard export under their own name instead of as
the contact. I kept the contact merge rule as it is until the review is done, because changing it
changes tracker rows, Sheet rows and saved outreach keys.

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
touches it. Entries are keyed by phone (and by `user_id` for a member who is not in the phone contacts,
since members can share a phone) and matched through any of a person's numbers, so a re-export or
re-ordered numbers is fine.

**Keep the history, key it on the source system's id.** A member's name and row order change between
exports, so `user_id` is the key everywhere and the history stores changes as validity ranges. A row
number would have silently re-pointed saved notes at the wrong person.

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

**Information, then decision, then action.** The dashboard shows a figure only when it supports a
decision, and a decision only when there is something to do about it from the same screen. That is why
the list of members close to the next grade shows what is left to reach the objective, and why the
lists carry a link to act on them. New features follow the same test.

**DuckDB.** One local file, no server to run, and fast enough for this volume. Its single-writer limit is
a known trade-off, handled by not refreshing while the dashboard holds a long query.

**Airflow runs the project's own image.** Each DAG task starts the project container with
`DockerOperator`, so Airflow carries none of its dependencies. The DAG runs daily:
`fetch_network → check_inputs → load_raw → dbt_build → sheet_sync → export_tracker`, and a failing dbt
test fails the run.

## Testing

145 pytest tests (loaders, vCard parsing and export, dashboard queries and launch, outreach, sheet sync and
formatting, locations, shared-number links, the map and route tabs) plus dbt tests that fail the build
when a person or a number is lost or a pair is duplicated. All of it runs on the synthetic fixtures, so
the same suite can live in a public repo, and GitHub Actions runs it on every pull request. The test
session is isolated from real data: it points every path at a temporary directory and refuses to open
anything under `data/`.

## Results

- **Nothing is lost silently.** A number that disappears fails the build; every merge and every
  weak link is listed for review.
- **Members and contacts are told apart.** Members sharing a number are no longer treated as the same
  person as the contact who has that number.
- **Changes are visible over time.** A member's sales, grade and activity are kept as dated states
  instead of being overwritten by the next export.
- **Less manual work.** One command rebuilds everything the old script chain did, and `make sync` keeps
  the Sheet and the dashboard in step without copy and paste.

The fixtures are small on purpose (a few dozen contacts and a dozen members), so figures from a real run
are not shown here.

## Run it

```bash
cp .env.example .env              # variable names only; put nothing sensitive in git
make build
make demo                         # builds the warehouse from the synthetic fixtures
make test                         # 145 tests, a few minutes
```

`make demo` has its own warehouse and outreach store (`data/demo.duckdb`, `data/demo_outreach.duckdb`),
reads only the fixtures and never touches the Sheet, so it cannot overwrite a real warehouse built with
`make run`. To browse the demo in the dashboard:

```bash
CNP_DB=data/demo.duckdb CNP_OUTREACH=data/demo_outreach.duckdb make up
```

The dashboard needs the pinned ECharts file (`CNP_ECHARTS`, fetched in the Dockerfile and in CI).

## Limitations

- **Merging contacts on a shared number is a heuristic.** It can join two people who share a phone;
  the review lists exist to catch that, and the rule will be tightened once the review is done.
- **A member linked by number only is a guess.** `same_number` marks it, but only a person can settle it.
- **Addresses are sparse.** The map and the route builder are only as good as the addresses entered in
  the Sheet; the source system has no address field.
- **DuckDB allows one writer.** A refresh has to wait for a long dashboard query.
- **No cloud deployment yet.** It runs on one machine behind a private network.

## What I learned

The identity question took longer than the code. I first treated a phone number as an identity, it worked
on my own contacts, and it failed as soon as the network's members shared numbers. Making the merges
visible (an audit table, a review list) mattered more than making the rule smarter, and keying everything
on the source system's stable id saved me from a class of silent mix-ups.

## Layout

```
ingest/       raw loaders, vCard export and Google Sheet sync
dbt/          staging and mart models, macros, singular tests
app/          Streamlit dashboard
dags/         Airflow DAG
apps_script/  script pasted once into the Sheet (locality dropdown)
fixtures/     synthetic data and its generator
tests/        pytest suite
```

## Next

Tighten the contact merge rule after the review, turn the daily sync on, and add cloud deployment and
infrastructure as code.
