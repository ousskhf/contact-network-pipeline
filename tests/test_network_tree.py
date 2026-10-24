import json
import re

import pandas as pd

from app.network_tree import (ROOT_ID, ancestors, descendant_counts, echarts_html, echarts_tree, grade_colors,
                              index_tree, subtree, treemap_data)


def members():
    # A(1) is top-level; B,C under A; D under B; E sponsors itself; F<->G sponsor each other (cycle)
    rows = [(1, 99, "A", "Gold", 3, True), (2, 1, "B", "Bronze", 1, True), (3, 1, "C", "Bronze", 1, False),
            (4, 2, "D", "Silver", 2, True), (5, 5, "E", "Bronze", 1, True),
            (6, 7, "F", "Bronze", 1, True), (7, 6, "G", "Bronze", 1, True)]
    return pd.DataFrame(rows, columns=["user_id", "sponsor_id", "name", "grade", "grade_order", "is_active"]
                        ).assign(team_sales=10.0, direct_count=1)


def count_nodes(n):
    return 1 + sum(count_nodes(c) for c in n.get("children", []))


def test_every_member_appears_once_even_with_self_sponsor_and_cycles():
    keys, parent, children, order = index_tree(members())
    assert sorted(order) == sorted(keys) and len(set(order)) == 7
    assert parent["1"] == ROOT_ID and parent["5"] == ROOT_ID           # outside sponsor / self sponsor -> top
    assert parent["2"] == "1" and parent["4"] == "2"
    assert ROOT_ID in {parent["6"], parent["7"]}                        # cycle is broken at the top
    assert descendant_counts(children, order)["1"] == 3                 # B, C, D


def test_subtree_and_ancestors():
    df = members()
    assert sorted(subtree(df, 2)["name"]) == ["B", "D"]
    assert ancestors(df, 4) == ["A", "B", "D"]


def test_echarts_tree_has_all_members_and_marks_inactive():
    tree = echarts_tree(members())
    assert count_nodes(tree) == 7 + 1                                    # + the root label
    flat = {}
    def walk(n):
        flat[n["name"]] = n
        [walk(c) for c in n.get("children", [])]
    walk(tree)
    assert flat["C"]["symbol"] == "emptyCircle" and flat["B"]["symbol"] == "circle"
    assert flat["C"]["itemStyle"]["color"] == "#b0b5bb"                  # inactive is grey, with a different shape


def test_tooltip_shows_the_phone_when_known():
    df = members().assign(phone=["20123456", None, "", "<b>1", None, None, None])
    tips = {n["name"]: n["info"] for n in echarts_tree(df)["children"]}
    assert "<br/>tél : 20123456<br/>" in tips["A"]
    assert "tél" not in echarts_tree(members())["children"][0]["info"]    # no phone column / empty / None: no line
    assert "tél" not in tips["E"]


def test_names_are_escaped_in_tooltips_and_cannot_close_the_script_tag(tmp_path):
    df = members().assign(name=["</script><b>x", "<!--<script>", "C", "D", "E", "F", "G"])
    tree = echarts_tree(df)
    evil = next(n for n in tree["children"] if n["name"] == "</script><b>x")
    assert evil["info"].startswith("<b>&lt;/script&gt;&lt;b&gt;x</b>")   # tooltip HTML is escaped (name itself is drawn as plain text)
    lib = tmp_path / "echarts.js"
    lib.write_text("/* lib */", encoding="utf-8")
    out = echarts_html(tree, echarts_path=str(lib))
    assert "</script><b>x" not in out and out.count("</script>") == 2    # only our own two script tags
    assert "<!--" not in out                                              # comment opener can't switch the parser state
    payload = re.search(r"const tree = (.*);\nconst chart", out, re.S).group(1)
    assert json.loads(payload)["name"] == "Réseau"                       # the embedded data is valid JSON


def test_treemap_is_consistent():
    t = treemap_data(members())
    assert len(set(t["ids"])) == len(t["ids"]) == 8
    assert all(p == "" or p in t["ids"] for p in t["parents"])
    assert sum(t["values"]) == 7 and t["values"][0] == 0
    assert t["labels"][t["ids"].index("3")] == "C (inactif)"


def test_grade_colors_run_from_light_to_dark_by_grade_order():
    c = grade_colors(members())
    assert list(c) == ["Bronze", "Silver", "Gold"]
    lum = [sum(int(col[i:i + 2], 16) for i in (1, 3, 5)) for col in c.values()]
    assert lum == sorted(lum, reverse=True)                              # darker with higher grade
