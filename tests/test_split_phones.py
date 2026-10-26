import duckdb
import jinja2
import pytest

MACROS = "".join(open(f"dbt/macros/{m}.sql").read() for m in ("normalize_phone", "split_phones"))


def split(value):
    sql = jinja2.Template(MACROS + "select {{ split_phones('v') }} from (select ?::varchar as v)").render()
    return duckdb.connect().execute(sql, [value]).fetchone()[0]


@pytest.mark.parametrize("raw, expected", [
    ("98765432", ["98765432"]),
    ("98 765 432", ["98765432"]),
    ("98765432 / 21345678", ["98765432", "21345678"]),
    ("98765432/21345678", ["98765432", "21345678"]),
    ("98765432 /21345678", ["98765432", "21345678"]),
    ("98765432- 21345678", ["98765432", "21345678"]),
    ("9876543221345678", ["98765432", "21345678"]),
    ("+216 98 765 432 / 00216 21345678", ["98765432", "21345678"]),
    ("98-765-432", ["98765432"]),                 # separators inside one number are not a split
    ("98765432 / 123", ["98765432/123"]),          # a part that is not a number: left as before
    ("+33612345678", ["+33612345678"]),           # not Tunisian: untouched
    ("", [None]),
    (None, [None]),
])
def test_split_phones(raw, expected):
    assert split(raw) == expected
