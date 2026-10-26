"""Write network members as vCard 3.0, the format Android Contacts and Google Contacts import.

Each card carries the name, the number in international form and, when ORG_NAME is set, that
organisation (shown under "Company" on the phone). The name comes from the environment, so it stays
out of the repo (set it in .env).
"""
import os
import re

COUNTRY_CODE = "+216"       # the pipeline strips +216 from Tunisian numbers (see the normalize_phone macro)


def e164(phone: str) -> str:
    """Tunisian numbers are stored as 8 digits; other country codes were kept with their '+'."""
    p = re.sub(r"[^\d+]", "", str(phone))
    if p.startswith("+"):
        return p
    return f"{COUNTRY_CODE}{p}" if len(p) == 8 else p


def _esc(text: str) -> str:
    return (str(text).replace("\\", "\\\\").replace("\r\n", "\n").replace("\n", "\\n")
            .replace(",", "\\,").replace(";", "\\;"))


def _fold(line: str) -> str:
    """RFC 6350 folding: at most 75 octets per line, never splitting a UTF-8 character."""
    out, cur, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > (75 if not out else 74):
            out.append(cur)
            cur, size = "", 0
        cur += ch
        size += n
    out.append(cur)
    return "\r\n ".join(out)


def org_name() -> str:
    return os.environ.get("ORG_NAME", "").strip()


def card(name: str, phone: str, org: str = "") -> str:
    parts = name.split()
    family, given = (parts[-1], " ".join(parts[:-1])) if len(parts) > 1 else ("", name)
    lines = ["BEGIN:VCARD", "VERSION:3.0", f"FN:{_esc(name)}", f"N:{_esc(family)};{_esc(given)};;;",
             f"TEL;TYPE=CELL:{e164(phone)}"]
    if org:
        lines.append(f"ORG:{_esc(org)}")
    lines.append("END:VCARD")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def to_vcard(people, org: str | None = None) -> str:
    """people: iterable of dicts with nom and téléphone. org defaults to the ORG_NAME setting."""
    org = org_name() if org is None else org
    return "".join(card(p["nom"], p["téléphone"], org) for p in people)
