import duckdb
import pytest

from ingest.load_contacts import load_contacts
from ingest.load_network import load_network

SENSITIVE = {"password", "rib", "cin"}


@pytest.fixture
def con():
    return duckdb.connect(":memory:")


def test_contacts_loaded_untouched(con):
    n = load_contacts(con, "fixtures/contacts.csv")
    assert n == 44
    # all four numbers of the multi-number contact survive in raw
    row = con.execute(
        "select \"Phone 1 - Value\", \"Phone 2 - Value\", \"Phone 3 - Value\", \"Phone 4 - Value\" "
        "from raw.contacts where \"First Name\" = 'Multi'"
    ).fetchone()
    assert all(row)
    # formatting variants are kept as-is (normalisation happens in staging)
    assert con.execute(
        "select count(*) from raw.contacts where \"Phone 1 - Value\" like '+216%' "
        "or \"Phone 1 - Value\" like '00216%'"
    ).fetchone()[0] == 2


def test_network_loaded_and_sensitive_fields_dropped(con):
    assert load_network(con, "fixtures/downline.json") == 12
    cols = {r[0] for r in con.execute("describe raw.network").fetchall()}
    assert not (SENSITIVE & cols)
    dump = con.execute("select * from raw.network").fetchall()
    assert not any("SENSITIVE" in str(v) for row in dump for v in row)
