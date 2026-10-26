"""Load contacts.vcf (or contacts.csv) and the network export (optional) from $CNP_DATA_DIR into $CNP_DB."""
import os
from pathlib import Path

import duckdb

from ingest.load_contacts import load_contacts
from ingest.load_network import load_network
from ingest.load_vcf import load_vcf


def main():
    data_dir = Path(os.environ.get("CNP_DATA_DIR", "fixtures"))
    db = os.environ.get("CNP_DB", "data/cnp.duckdb")
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(db)
    vcf, csv_ = data_dir / "contacts.vcf", data_dir / "contacts.csv"
    n = load_vcf(con, str(vcf)) if vcf.exists() else load_contacts(con, str(csv_))
    print(f"raw.contacts: {n} rows (from {(vcf if vcf.exists() else csv_).name})")
    # ingest.fetch_network writes downline_raw.json (real data, nightly); fixtures still ship as downline.json.
    raw, legacy = data_dir / "downline_raw.json", data_dir / "downline.json"
    network_path = raw if raw.exists() else legacy
    print(f"raw.network:  {load_network(con, str(network_path))} rows (+ raw.grades, raw.campaign, from {network_path.name})")


if __name__ == "__main__":
    main()
