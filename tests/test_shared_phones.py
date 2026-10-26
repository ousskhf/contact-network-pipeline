import duckdb
import jinja2
import pytest

MACROS = "".join(open(f"dbt/macros/{m}.sql").read() for m in ("name_match",))


def compatible(a, b):
    sql = jinja2.Template(MACROS + "select {{ names_compatible(name_tokens('a'), name_tokens('b')) }} "
                          "from (select ?::varchar as a, ?::varchar as b)").render()
    return duckdb.sql(sql, params=[a, b]).fetchone()[0]


@pytest.mark.parametrize("a, b, expected", [
    ("Amal Test", "amal  TEST", True),
    ("Amal Test", "Test Amal", True),                 # order does not matter
    ("Élodie Ben Salah", "Elodie Ben Salah", True),   # accents
    ("Amal", "Amal Test", True),                      # one name is enough when the other is a single token
    ("Amal Test", "", True),                          # nothing to compare
    ("Amal Test", None, True),
    ("Amal Test", "Besma Test", False),               # same surname is a family, not a match
    ("Amal Test", "Besma Demo", False),
])
def test_names_compatible(a, b, expected):
    assert compatible(a, b) is expected


def test_shared_number_is_flagged_and_linked_by_number_only(db):
    con = duckdb.connect(db, read_only=True)
    shared = con.execute("select * from main.phone_share where is_shared").fetchall()
    assert shared, "the fixtures put one contact number on a network member too"
    kinds = dict(con.execute("select link_kind, count(*) from main.fct_network_membership group by 1").fetchall())
    assert kinds.get("same_number", 0) >= 1               # member 0 shares a contact's number under another name
    assert set(kinds) <= {None, "name_match", "same_number"}
    assert con.execute("select count(*) from main.merge_review").fetchone()[0] == \
        con.execute("select count(*) from main.merge_audit").fetchone()[0]
