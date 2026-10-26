from urllib.parse import parse_qs, unquote, urlparse

import pytest

from app.trajets import coords_from_link, make_stop, route_links


def no_network(url):
    raise AssertionError("no link should be followed here")


@pytest.mark.parametrize("adresse, expected", [
    ("36.8065,10.1815", "36.8065,10.1815"),
    ("36.8065, 10.1815", "36.8065,10.1815"),
    ("36.8065;10.1815", "36.8065,10.1815"),
    ("-33.9, 151.2", "-33.9,151.2"),
    ("https://www.google.com/maps/place/Example/@36.8065,10.1815,17z/data=x", "36.8065,10.1815"),
    ("https://www.google.com/maps/place/X/data=!3d36.8065!4d10.1815", "36.8065,10.1815"),
    ("https://www.google.com/maps?q=36.8065,10.1815", "36.8065,10.1815"),
])
def test_coordinates_and_full_links_become_lat_lng(adresse, expected):
    assert make_stop(adresse, resolve=no_network) == (expected, None)


def test_out_of_range_coordinates_are_refused():
    assert make_stop("136.8, 10.2", resolve=no_network)[0] is None


def test_short_link_is_followed_then_read():
    followed = []

    def resolve(url):
        followed.append(url)
        return "https://www.google.com/maps/place/Example/@36.8065,10.1815,17z"

    assert make_stop("https://maps.app.goo.gl/abc123", resolve=resolve) == ("36.8065,10.1815", None)
    assert followed == ["https://maps.app.goo.gl/abc123"]


def test_unresolvable_or_positionless_links_say_why():
    stop, problem = make_stop("https://maps.app.goo.gl/abc123", resolve=lambda url: "")
    assert stop is None and "lien" in problem
    stop, problem = make_stop("https://example.test/page", resolve=no_network)
    assert stop is None and "lien" in problem


def test_text_address_gets_its_town_and_country():
    assert make_stop("12 rue Exemple", "Quartier Test", "Ville Demo", "Région X") == \
        ("12 rue Exemple, Quartier Test, Ville Demo, Région X, Tunisie", None)


def test_town_already_in_the_address_is_not_repeated():
    assert make_stop("12 rue Exemple, Ville Demo", "", "Ville Demo")[0] == "12 rue Exemple, Ville Demo, Tunisie"


def test_country_given_replaces_the_default():
    assert make_stop("12 rue Exemple", "", "Ville Demo", "", "France")[0] == "12 rue Exemple, Ville Demo, France"


def test_neighbourhood_alone_is_enough_but_a_town_alone_is_not():
    assert make_stop("", "Quartier Test", "Ville Demo")[0] == "Quartier Test, Ville Demo, Tunisie"
    assert make_stop("", "", "Ville Demo") == (None, "pas d'adresse")
    assert make_stop(None, float("nan"), "") == (None, "pas d'adresse")


def test_coords_from_link_ignores_text_without_position():
    assert coords_from_link("https://www.google.com/maps/dir/") is None


def _query(link):
    return {k: v[0] for k, v in parse_qs(urlparse(link).query).items()}


def test_single_stop_has_a_destination_and_no_origin():
    (link,) = route_links(["36.8,10.1"])
    q = _query(link)
    assert q["destination"] == "36.8,10.1" and q["travelmode"] == "driving" and q["api"] == "1"
    assert "origin" not in q and "waypoints" not in q


def test_stops_between_are_waypoints_in_order_and_the_last_is_the_destination():
    (link,) = route_links(["1,1", "2,2", "Rue Exemple, Ville Demo, Tunisie", "4,4"])
    q = _query(link)
    assert q["waypoints"].split("|") == ["1,1", "2,2", "Rue Exemple, Ville Demo, Tunisie"]
    assert q["destination"] == "4,4"
    assert "%7C" in link and " " not in link and unquote(link).count("|") == 2


def test_long_lists_are_cut_and_each_link_starts_where_the_last_ended():
    stops = [f"{i},{i}" for i in range(1, 21)]
    links = route_links(stops)
    assert len(links) == 3
    queries = [_query(link) for link in links]
    assert "origin" not in queries[0]
    assert queries[1]["origin"] == queries[0]["destination"] == "9,9"
    assert queries[2]["origin"] == queries[1]["destination"] == "18,18"
    covered = [s for q in queries for s in q.get("waypoints", "").split("|") if s] + [q["destination"] for q in queries]
    assert sorted(covered, key=lambda s: int(s.split(",")[0])) == stops


def test_no_stops_no_links():
    assert route_links([]) == []
