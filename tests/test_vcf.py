import duckdb

from ingest.load_vcf import load_vcf, parse_vcf

# Synthetic vCard 2.1 with the quirks seen in real phone exports.
VCF = (
    "BEGIN:VCARD\r\nVERSION:2.1\r\nN:Test;Amal;;;\r\nFN:Amal Test\r\n"
    "ADR;HOME:;;1 Rue Test;Sousse;Sahel;4000;Tunisie\r\nORG:Atelier Demo;Dept\r\nTITLE:Gérante\r\nTEL;CELL:+216 20 000 001\r\nTEL;HOME:20000002\r\nTEL;X-Custom(a):20000003\r\n"
    "TEL;CELL:20000004\r\nTEL;CELL:20000005\r\nEMAIL;HOME:amal@example.test\r\n"
    "PHOTO;ENCODING=BASE64;JPEG:AAAA\r\n BBBB\r\n CCCC\r\n\r\nEND:VCARD\r\n"
    # accented name, quoted-printable with a soft line break
    "BEGIN:VCARD\r\nVERSION:2.1\r\n"
    "N;ENCODING=QUOTED-PRINTABLE;CHARSET=UTF-8:=C3=89ric;=\r\n=C3=89lodie;;;\r\n"
    "FN;ENCODING=QUOTED-PRINTABLE;CHARSET=UTF-8:=C3=89lodie =C3=89ric\r\nTEL;CELL:00216 20 000 006\r\nEND:VCARD\r\n"
    # no N value, only FN
    "BEGIN:VCARD\r\nVERSION:2.1\r\nN:;;;;\r\nFN:Only Fullname\r\nTEL;CELL:20000007\r\nEND:VCARD\r\n"
)


def test_parse_quirks():
    rows = parse_vcf(VCF)
    assert len(rows) == 3
    assert [rows[0][f"Phone {i} - Value"] for i in range(1, 6)] == [
        "+216 20 000 001", "20000002", "20000003", "20000004", "20000005"]
    assert rows[0]["E-mail 1 - Value"] == "amal@example.test"
    assert (rows[0]["Address 1 - City"], rows[0]["Address 1 - Region"]) == ("Sousse", "Sahel")
    assert rows[0]["Address 1 - Street"] == "1 Rue Test"
    assert rows[0]["Address 1 - Country"] == "Tunisie"
    assert (rows[0]["Organization Name"], rows[0]["Organization Title"]) == ("Atelier Demo Dept", "Gérante")
    assert (rows[1]["First Name"], rows[1]["Last Name"]) == ("Élodie", "Éric")
    assert rows[2]["First Name"] == "Only Fullname"


def test_load_into_raw_and_no_number_lost(tmp_path):
    p = tmp_path / "c.vcf"
    p.write_text(VCF, encoding="utf-8")
    con = duckdb.connect(":memory:")
    assert load_vcf(con, str(p)) == 3
    cols = {r[0] for r in con.execute("describe raw.contacts").fetchall()}
    assert "Phone 5 - Value" in cols                      # no cap on numbers
    n = con.execute("select count(*) from raw.contacts where \"Phone 5 - Value\" = '20000005'").fetchone()[0]
    assert n == 1


def test_network_is_optional(tmp_path):
    from ingest.load_network import load_network
    con = duckdb.connect(":memory:")
    assert load_network(con, str(tmp_path / "missing.json")) == 0
    assert con.execute("select count(*) from raw.network").fetchone()[0] == 0
