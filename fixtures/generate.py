"""Generate synthetic, obviously fake fixtures (stdlib only, deterministic).

Writes fixtures/contacts.csv (Google Contacts export shape) and
fixtures/downline.json (API shape, including sensitive fields that the
loader must drop). Edge cases covered on purpose: formatting variants of one
number, a contact with 4 numbers, a one-digit-swap typo pair, duplicate rows,
a number shared by two network members and a contact.
"""
import csv
import json
import random
from pathlib import Path

OUT = Path(__file__).parent
random.seed(42)

FIRST = ["Amal", "Besma", "Chadia", "Dorra", "Emna", "Farah", "Ghada", "Hela"]
LAST = ["Test", "Demo", "Sample", "Fixture", "Mock"]


def num():
    return str(random.choice([20, 21, 22, 50, 52, 53, 90, 94, 98])) + "".join(
        random.choice("0123456789") for _ in range(6)
    )


def contacts():
    rows = []
    for i in range(40):
        n = num()
        rows.append({"First Name": random.choice(FIRST), "Last Name": f"{random.choice(LAST)}{i}",
                     "Phone 1 - Value": n})
    base = rows[0]["Phone 1 - Value"]
    rows[1]["Phone 1 - Value"] = f"+216 {base[:2]} {base[2:5]} {base[5:]}"   # same number, other format
    rows[2]["Phone 1 - Value"] = "00216" + base                                # same number, prefix
    four = {"First Name": "Multi", "Last Name": "Numbers", "Phone 1 - Value": "98000001",
            "Phone 2 - Value": "70123456", "Phone 3 - Value": "22000003", "Phone 4 - Value": "70132456"}
    rows.append(four)                                                          # 4 numbers + typo pair
    rows.append(dict(rows[5]))                                                 # exact duplicate row
    for k in ("A", "B"):                                                        # same short code, different people
        rows.append({"First Name": f"Short{k}", "Last Name": "Code", "Phone 1 - Value": "190"})
    return rows


GRADES = [("Bronze", 100), ("Silver", 120), ("Gold", 900), ("Platinum", 24000)]


def _phone(i, shared):
    n = num() if i else shared          # keep the random sequence: member 1 only swaps its number for the shared one
    return shared if i == 1 else n      # two members behind one number, like a delivery handler


def downline(contact_rows):
    items = []
    shared = contact_rows[3]["Phone 1 - Value"]
    for i in range(12):
        gid = random.randint(1, len(GRADES))
        items.append({
            "userId": 500 + i, "sponsorId": 500 if i else 1, "depth": 1 if i < 6 else 2, "directCount": i % 3,
            "user": {"firstName": random.choice(FIRST), "lastName": f"Net{i}",
                     "phoneNumber": _phone(i, shared), "phoneNumber2": None,
                     "boutiqueCode": f"B{i:03d}", "numeroMembre": 1000 + i,
                     "birthDate": f"19{80 + i}-{(i % 12) + 1:02d}-{(i * 2) % 27 + 1:02d}T00:00:00.000Z",
                     "gradeId": gid, "grade": {"name": GRADES[gid - 1][0]},
                     "isBlocked": i % 4 == 0,
                     "password": "SENSITIVE", "rib": "SENSITIVE", "cin": "SENSITIVE"},
            "progresses": [{"personalSalesTTC": str(random.randint(0, 900)), "pendingPersonalSalesTTC": "0",
                            "teamSalesTTC": str(random.randint(0, 3000)), "pendingTeamSalesTTC": "0",
                            "downlineSalesTTC": 0, "pendingDownlineSalesTTC": 0, "gradeAtStart": max(1, gid - (i % 2)),
                            "eligibleGrade": None, "isPromoted": i % 2 == 1, "personalReferrals": i % 4}],
        })
    campaign = {"id": 3, "name": "Campagne démo", "startDate": "2026-10-01T00:00:00.000Z",
                "endDate": "2026-10-31T23:59:59.000Z", "isActive": True, "isFinalized": False}
    return {"data": items, "campaign": campaign}


def grades():
    return {"data": [{"id": i + 1, "name": n, "sortOrder": i + 1, "objectiveGrade": str(o), "minVentePerso": "0",
                      "directorMinCa": "0", "requiredConfirmedDirectors": 0, "sameRankEarningThreshold": "0"}
                     for i, (n, o) in enumerate(GRADES)]}


if __name__ == "__main__":
    rows = contacts()
    fields = ["First Name", "Last Name", "Phone 1 - Value", "Phone 2 - Value",
              "Phone 3 - Value", "Phone 4 - Value", "E-mail 1 - Value", "E-mail 2 - Value",
              "Address 1 - City", "Address 1 - Region", "Address 1 - Street", "Address 1 - Country", "Organization Name", "Organization Title"]
    for i, r in enumerate(rows[:10]):
        r["Address 1 - City"] = "Sousse" if i % 2 else ""
        r["Address 1 - Region"] = "Sahel" if i % 2 == 0 else ""
    rows[11]["Last Name"], rows[11]["Address 1 - Street"] = "StreetOnly", "Monastir"   # town typed in the street field
    rows[2]["Address 1 - Country"], rows[2]["Address 1 - Street"] = "Tunisie", "12 Rue Demo"
    rows[12]["Last Name"], rows[12]["Address 1 - Street"] = "FreeText", "Tunis, Tunisia"   # whole address in the street field
    rows[13]["Last Name"], rows[13]["Address 1 - Street"] = "CountryOnly", "Tunisia"
    for i, r in enumerate(rows[14:34]):                                          # spread over a few governorates, for the map
        r["Address 1 - Region"] = ["Tunis", "Tunis", "Tunis", "Sfax", "Sfax", "Sousse", "Nabeul", "Gabès", "Ariana"][i % 9]
    rows[34]["Address 1 - City"] = "Hammamet"                                     # a ville only: the région is deduced
    rows[35]["Address 1 - Region"], rows[35]["Address 1 - Country"] = "Paris", "France"
    rows[0]["E-mail 1 - Value"] = "amal@example.test"
    rows[0]["Organization Name"], rows[0]["Organization Title"] = "Atelier Demo", "Gérante"
    rows[1]["E-mail 1 - Value"] = "amal@example.test"                      # same person (shares number), same email
    with open(OUT / "contacts.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, restval="")
        w.writeheader()
        w.writerows(rows)
    (OUT / "downline.json").write_text(json.dumps(downline(rows), ensure_ascii=False, indent=1))
    (OUT / "grades.json").write_text(json.dumps(grades(), ensure_ascii=False, indent=1))
    print(f"contacts.csv: {len(rows)} rows | downline.json: 12 members")
