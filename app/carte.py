"""Where the network lives: people counted per région from the Région / Ville columns of the tracker.

A person is placed on the map at the centre of their région (governorate). The Région cell is used when it names one;
otherwise the Ville is looked up (a ville that is itself a région name, or one that exists in a single région).
Streamlit-free so it can be tested on its own.
"""
import json
import re
import unicodedata
from functools import cache
from pathlib import Path

import pandas as pd

from ingest import locations

_CENTROIDS = Path(__file__).with_name("tunisia_centroids.json")
HOME_COUNTRIES = ("tunisie", "tunisia")


def fold(value) -> str:
    """"Béja " -> "beja": lowercase, no accents, no punctuation, so spelling variants of one name compare equal."""
    text = "" if value is None or value is pd.NA or value != value else str(value)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


@cache
def centroids() -> dict[str, tuple[float, float]]:
    return {k: tuple(v) for k, v in json.loads(_CENTROIDS.read_text(encoding="utf-8")).items()}


@cache
def _region_names() -> dict[str, str]:
    return {fold(r): r for r in centroids()}


@cache
def _ville_regions() -> dict[str, str]:
    """Folded ville -> its région, for the villes that exist in exactly one région."""
    found: dict[str, set] = {}
    for region, names in locations.load().items():
        for ville in names:
            found.setdefault(fold(ville), set()).add(region)
    return {v: next(iter(rs)) for v, rs in found.items() if len(rs) == 1}


def region_of(region="", ville=""):
    """The région a person belongs to, or None when neither cell names a known one."""
    names = _region_names()
    if fold(region) in names:
        return names[fold(region)]
    ville = fold(locations.strip_region(ville))
    return names.get(ville) or _ville_regions().get(ville)


def is_abroad(pays) -> bool:
    return fold(pays) != "" and fold(pays) not in HOME_COUNTRIES


def place(people: pd.DataFrame) -> pd.Series:
    """The région of each row (None when unknown or when the person lives abroad)."""
    return pd.Series([None if is_abroad(p) else region_of(r, v)
                      for r, v, p in zip(people["Région"], people["Ville"], people["Pays"])], index=people.index)


def by_region(people: pd.DataFrame) -> pd.DataFrame:
    """One row per région with at least one person: Région, Personnes, lat, lon (largest first)."""
    counts = place(people).dropna().value_counts().rename_axis("Région").reset_index(name="Personnes")
    counts["lat"] = counts["Région"].map(lambda r: centroids()[r][0])
    counts["lon"] = counts["Région"].map(lambda r: centroids()[r][1])
    return counts.sort_values(["Personnes", "Région"], ascending=[False, True], ignore_index=True)


def by_ville(people: pd.DataFrame) -> pd.DataFrame:
    """Région / Ville / Personnes for the placed people who filled a Ville."""
    df = pd.DataFrame({"Région": place(people), "Ville": people["Ville"].map(locations.strip_region)})
    df = df[df["Région"].notna() & df["Ville"].fillna("").astype(str).str.strip().ne("")]
    if df.empty:
        return pd.DataFrame({"Région": [], "Ville": [], "Personnes": []})
    return df.groupby(["Région", "Ville"]).size().reset_index(name="Personnes").sort_values(
        ["Personnes", "Région", "Ville"], ascending=[False, True, True], ignore_index=True)


def countries(people: pd.DataFrame) -> pd.DataFrame:
    """Pays / Personnes for everyone who filled a Pays, as typed."""
    pays = people["Pays"].dropna().astype(str).str.strip()
    return pays[pays != ""].value_counts().rename_axis("Pays").reset_index(name="Personnes")


def unplaced(people: pd.DataFrame) -> pd.DataFrame:
    """The people to ask for a location (nobody abroad): what they have now, and why they are not on the map."""
    todo = people[place(people).isna() & ~people["Pays"].map(is_abroad)].copy()
    typed = todo[["Région", "Ville"]].fillna("").astype(str).apply(lambda c: c.str.strip().ne("")).any(axis=1)
    todo["Raison"] = typed.map({True: "texte non reconnu", False: "rien de saisi"})
    return todo
