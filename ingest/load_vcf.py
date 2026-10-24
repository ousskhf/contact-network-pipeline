"""Load a vCard (.vcf, 2.1/3.0) export into raw.contacts.

Cards are converted to the same wide shape as the Google Contacts CSV
(First Name, Last Name, Phone N - Value, E-mail N - Value), so staging and
dbt are unchanged. Photos and other properties are ignored.
"""
import csv
import quopri
import re
import tempfile

import duckdb

from ingest.load_contacts import load_contacts

_PROP = re.compile(r"^(?:item\d+\.)?([A-Za-z-]+)((?:;[^:]*)?):(.*)$")


def _unfold(text: str) -> list[str]:
    lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line[:1] in (" ", "\t") and lines:      # RFC folding / base64 continuation
            lines[-1] += line[1:]
        else:
            lines.append(line)
    out, i = [], 0
    while i < len(lines):                           # vCard 2.1 quoted-printable soft breaks
        line = lines[i]
        while "QUOTED-PRINTABLE" in line.upper() and line.endswith("=") and i + 1 < len(lines):
            i += 1
            line = line[:-1] + lines[i]
        out.append(line)
        i += 1
    return out


def _decode(params: str, value: str) -> str:
    if "QUOTED-PRINTABLE" not in params.upper():
        return value
    m = re.search(r"CHARSET=([\w-]+)", params, re.I)
    charset = m.group(1) if m else "utf-8"
    raw = quopri.decodestring(value.encode("ascii", "replace"))
    try:
        return raw.decode(charset)
    except (LookupError, UnicodeDecodeError):
        return raw.decode("utf-8", "replace")


def parse_vcf(text: str) -> list[dict]:
    cards, cur = [], None
    for line in _unfold(text):
        up = line.upper()
        if up.startswith("BEGIN:VCARD"):
            cur = {"tel": [], "email": [], "n": "", "fn": "", "adr": "", "org": "", "title": ""}
        elif up.startswith("END:VCARD"):
            if cur is not None:
                cards.append(cur)
            cur = None
        elif cur is not None:
            m = _PROP.match(line)
            if not m:
                continue
            name, params, value = m.group(1).upper(), m.group(2), m.group(3)
            if name == "TEL":
                cur["tel"].append(_decode(params, value).strip())
            elif name == "EMAIL":
                cur["email"].append(_decode(params, value).strip())
            elif name == "N":
                cur["n"] = _decode(params, value)
            elif name == "ADR" and not cur["adr"]:
                cur["adr"] = _decode(params, value)
            elif name == "ORG" and not cur["org"]:
                cur["org"] = _decode(params, value).replace(";", " ").strip()
            elif name == "TITLE" and not cur["title"]:
                cur["title"] = _decode(params, value).strip()
            elif name == "FN":
                cur["fn"] = _decode(params, value).strip()

    rows = []
    for c in cards:
        parts = (c["n"].split(";") + ["", ""])[:2]
        last, first = parts[0].strip(), parts[1].strip()
        if not (first or last):
            first = c["fn"]
        adr = (c["adr"].split(";") + [""] * 7)[:7]     # pobox;ext;street;city;region;zip;country
        row = {"First Name": first, "Last Name": last, "Address 1 - City": adr[3].strip(),
               "Address 1 - Region": adr[4].strip(), "Address 1 - Street": adr[2].strip(),
               "Address 1 - Country": adr[6].strip(), "Organization Name": c["org"], "Organization Title": c["title"]}
        for i, t in enumerate(t for t in c["tel"] if t):
            row[f"Phone {i + 1} - Value"] = t
        for i, e in enumerate(e for e in c["email"] if e):
            row[f"E-mail {i + 1} - Value"] = e
        rows.append(row)
    return rows


def load_vcf(con: duckdb.DuckDBPyConnection, path: str) -> int:
    with open(path, encoding="utf-8", errors="replace") as f:
        rows = parse_vcf(f.read())
    fields = ["First Name", "Last Name", "Address 1 - City", "Address 1 - Region", "Address 1 - Street",
              "Address 1 - Country", "Organization Name", "Organization Title"]
    for prefix, key in (("Phone", "Phone {} - Value"), ("E-mail", "E-mail {} - Value")):
        n = max((int(re.search(r"\d+", k).group()) for r in rows for k in r if k.startswith(prefix)), default=1)
        fields += [key.format(i) for i in range(1, n + 1)]
    with tempfile.NamedTemporaryFile("w", suffix=".csv", newline="", encoding="utf-8") as tmp:
        w = csv.DictWriter(tmp, fieldnames=fields, restval="")
        w.writeheader()
        w.writerows(rows)
        tmp.flush()
        return load_contacts(con, tmp.name)
