"""Tunisian administrative hierarchy used by the Sheet's dependent dropdowns: Région -> Ville -> Localité.

ingest/tunisia_locations.json maps each of the 24 governorates (Région) to its délégations (Ville), each with its
localities (Localité: towns, cités, résidences, sorted by name). Compiled from the postal-code tables of La Poste
tunisienne as published by tuniscope.com and worldpostalcode.com (see README); the sources spell some names
differently, and the lists are not exhaustive, so the Sheet accepts other values as a warning, not a refusal.
"""
import json
from pathlib import Path

import pandas as pd

COUNTRY = "Tunisie"
_PATH = Path(__file__).with_name("tunisia_locations.json")


def load() -> dict[str, dict[str, list[str]]]:
    return json.loads(_PATH.read_text(encoding="utf-8"))


def regions() -> list[str]:
    return list(load())


def villes(region: str) -> list[str]:
    return list(load().get(region, {}))


def localites(region: str, ville: str) -> list[str]:
    return load().get(region, {}).get(ville, [])


SEPARATOR = " - "          # of the earlier "Région - Ville" entries of the Ville dropdown


def lieux_rows() -> list[tuple[str, str, str]]:
    """One (région, ville, localité) triple per localité, for the Sheet script that builds the dependent dropdowns."""
    return [(region, ville, item) for region, names in load().items() for ville, items in names.items() for item in items]


def strip_region(value) -> str:
    """"Ariana - Soukra" -> "Soukra": the Ville dropdown used to hold the région in front of every name."""
    text = "" if value is None or pd.isna(value) else str(value).strip()     # a missing cell, not the text "nan"
    for region, names in load().items():
        prefix = f"{region}{SEPARATOR}"
        if text.startswith(prefix) and text[len(prefix):] in names:
            return text[len(prefix):]
    return text
