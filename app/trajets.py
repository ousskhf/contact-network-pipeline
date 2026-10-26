"""Turn addresses into a Google Maps directions link.

A directions link takes each stop as text or as "lat,lng", not as a pasted Maps link, so a full Maps link is
reduced to its coordinates and a short one (maps.app.goo.gl) is followed first. With no origin Maps starts from
the phone's position, and a long list is cut into several links, each one starting where the last ended.
"""
import re
import urllib.request
from urllib.parse import quote, urlparse

STOPS_PER_LINK = 9            # a link carries a limited number of waypoints; stay under it
SHORT_HOSTS = {"maps.app.goo.gl", "goo.gl"}
DEFAULT_COUNTRY = "Tunisie"

_NUM = r"-?\d{1,3}(?:\.\d+)?"
_COORDS = re.compile(rf"^\s*({_NUM})\s*[,;]\s*({_NUM})\s*$")
_IN_LINK = [re.compile(p) for p in (rf"@({_NUM}),({_NUM})", rf"!3d({_NUM})!4d({_NUM})",
                                    rf"[?&](?:q|query|ll|destination|daddr)=({_NUM}),({_NUM})")]


def _coords(lat: str, lng: str):
    return f"{float(lat):g},{float(lng):g}" if -90 <= float(lat) <= 90 and -180 <= float(lng) <= 180 else None


def coords_from_link(url: str):
    for pattern in _IN_LINK:
        m = pattern.search(url)
        if m and _coords(*m.groups()):
            return _coords(*m.groups())
    return None


def resolve_short_link(url: str, timeout: float = 5.0) -> str:
    """Follow a short Maps link and return the address it lands on ("" when it cannot be followed)."""
    if urlparse(url).hostname not in SHORT_HOSTS:
        return ""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:      # follows the redirects
            return response.geturl()
    except (OSError, ValueError):
        return ""


def _clean(value) -> str:
    return "" if value is None or value != value else str(value).strip()      # NaN is not equal to itself


def make_stop(adresse, localite="", ville="", region="", pays="", resolve=resolve_short_link):
    """(stop, problem): the stop to give Maps, or why this person cannot be one."""
    adresse = _clean(adresse)
    if adresse.lower().startswith(("http://", "https://")):
        url = adresse
        if urlparse(url).hostname in SHORT_HOSTS:
            url = resolve(url)
        found = coords_from_link(url) if url else None
        return (found, None) if found else (None, "lien Maps sans position (colle le lien long ou lat,lng)")
    m = _COORDS.match(adresse)
    if m:
        found = _coords(*m.groups())
        return (found, None) if found else (None, "coordonnées hors limites")
    localite = _clean(localite)
    if not adresse and not localite:
        return None, "pas d'adresse"
    parts = []
    for part in (adresse, localite, _clean(ville), _clean(region), _clean(pays) or DEFAULT_COUNTRY):
        if part and part.lower() not in " ".join(parts).lower():          # "Tunis" is not repeated after "..., Tunis"
            parts.append(part)
    return ", ".join(parts), None


def route_links(stops: list[str], per_link: int = STOPS_PER_LINK) -> list[str]:
    """Directions links in driving mode. The first starts from the phone's position, the next ones from the
    last stop of the previous link."""
    links, previous = [], None
    for i in range(0, len(stops), per_link):
        chunk = stops[i:i + per_link]
        query = ["api=1", "travelmode=driving", "destination=" + quote(chunk[-1], safe=",")]
        if previous:
            query.append("origin=" + quote(previous, safe=","))
        if len(chunk) > 1:
            query.append("waypoints=" + "%7C".join(quote(s, safe=",") for s in chunk[:-1]))
        links.append("https://www.google.com/maps/dir/?" + "&".join(query))
        previous = chunk[-1]
    return links
