"""Load contacts.vcf (or contacts.csv) and downline.json (optional) from $CNP_DATA_DIR into $CNP_DB."""
import os
from pathlib import Path

import duckdb

from ingest.load_contacts import load_contacts
from ingest.load_network import load_grades, load_network
from ingest.load_vcf import load_vcf


def main():
    data_dir = Path(os.environ.get("CNP_DATA_DIR", "fixtures"))
    db = os.environ.get("CNP_DB", "data/cnp.duckdb")
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(db)
    vcf, csv_ = data_dir / "contacts.vcf", data_dir / "contacts.csv"
    n = load_vcf(con, str(vcf)) if vcf.exists() else load_contacts(con, str(csv_))
    print(f"raw.contacts: {n} rows (from {(vcf if vcf.exists() else csv_).name})")
    print(f"raw.network:  {load_network(con, str(data_dir / 'downline.json'))} rows")
    print(f"raw.grades:   {load_grades(con, str(data_dir / 'grades.json'))} rows")


if __name__ == "__main__":
    main()
