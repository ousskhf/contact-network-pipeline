"""Pure helpers that turn network membership rows into the tree views (no Streamlit, no database).

Input DataFrame columns: user_id, sponsor_id, name, grade, grade_order, is_active, team_sales,
direct_count. A member whose sponsor is not in the data (or is itself) is a top-level member; members
caught in a sponsor cycle are also attached at the top, so every member is shown exactly once.
"""
import html
import json
import os
from pathlib import Path

import pandas as pd

ROOT_ID = "__root__"
INACTIVE = "#b0b5bb"
RAMP = ("#8fc5bb", "#06403b")          # sequential: low grade -> high grade (ordinal data)


def _mix(a: str, b: str, t: float) -> str:
    x = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    y = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(p + (q - p) * t):02x}" for p, q in zip(x, y))


def grade_colors(df: pd.DataFrame) -> dict:
    """grade name -> colour, light for low grades to dark for high ones (by grade_order)."""
    order = (df.dropna(subset=["grade"]).drop_duplicates("grade")
             .sort_values("grade_order", na_position="last")["grade"].tolist())
    n = max(len(order) - 1, 1)
    return {g: _mix(RAMP[0], RAMP[1], i / n) for i, g in enumerate(order)}


def _key(row) -> str:
    return str(int(row.user_id)) if pd.notna(row.user_id) else f"row{row.Index}"


def index_tree(df: pd.DataFrame):
    """Returns (keys, parent, children, order): parent[key] is the parent key or ROOT_ID; `order` is a
    root-first traversal containing every member exactly once."""
    rows = list(df.itertuples())
    keys = {_key(r): r for r in rows}
    parent = {}
    for k, r in keys.items():
        sp = str(int(r.sponsor_id)) if pd.notna(r.sponsor_id) else None
        parent[k] = sp if sp in keys and sp != k else ROOT_ID
    children = {ROOT_ID: []}
    for k in keys:
        children.setdefault(k, [])
    for k, p in parent.items():
        children[p].append(k)
    order, seen, stack = [], set(), [ROOT_ID]
    while stack:
        cur = stack.pop()
        for c in sorted(children[cur], reverse=True):
            if c not in seen:
                seen.add(c)
                order.append(c)
                stack.append(c)
    for k in keys:                                   # sponsor cycles: unreachable from the top, attach there
        if k not in seen:
            children[parent[k]].remove(k)            # detach from the sponsor that closes the cycle
            parent[k] = ROOT_ID
            children[ROOT_ID].append(k)
            stack = [k]
            seen.add(k)
            order.append(k)
            while stack:
                cur = stack.pop()
                for c in sorted(children[cur], reverse=True):
                    if c not in seen:
                        seen.add(c)
                        order.append(c)
                        stack.append(c)
    return keys, parent, children, order


def descendant_counts(children: dict, order: list) -> dict:
    count = {k: 0 for k in children}
    for k in reversed(order):                        # children come after parents in `order`
        for c in children[k]:
            count[k] += 1 + count[c]
    return count


def subtree(df: pd.DataFrame, user_id) -> pd.DataFrame:
    """The member `user_id` and everyone under them."""
    keys, _, children, _ = index_tree(df)
    out, stack = [], [str(int(user_id))]
    seen = set()
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        out.append(cur)
        stack.extend(children.get(cur, []))
    wanted = set(out)
    return df[[(str(int(u)) if pd.notna(u) else None) in wanted for u in df["user_id"]]]


def ancestors(df: pd.DataFrame, user_id) -> list[str]:
    """Names from the top of the network down to (and including) the member."""
    keys, parent, _, _ = index_tree(df)
    k, chain = str(int(user_id)), []
    while k in keys and k not in chain:
        chain.append(k)
        k = parent[k]
    return [keys[c].name for c in reversed(chain)]


def _info(r, desc: int) -> str:
    team = 0 if pd.isna(r.team_sales) else r.team_sales
    phone = getattr(r, "phone", None)
    tel = f"<br/>tél : {html.escape(phone)}" if isinstance(phone, str) and phone else ""
    return (f"<b>{html.escape(str(r.name))}</b><br/>{html.escape(str(r.grade or '?'))} · "
            f"{'actif' if r.is_active else 'inactif'}{tel}<br/>équipe : {team:,.0f} TTC · "
            f"directs : {int(r.direct_count) if pd.notna(r.direct_count) else 0} · sous lui : {desc}")


def echarts_tree(df: pd.DataFrame, root_label: str = "Réseau") -> dict:
    """Nested dict for an ECharts `tree` series."""
    keys, _, children, order = index_tree(df)
    desc = descendant_counts(children, order)
    colors = grade_colors(df)

    def node(k):
        r = keys[k]
        return {"name": str(r.name), "info": _info(r, desc[k]),
                "itemStyle": {"color": colors.get(r.grade, INACTIVE) if r.is_active else INACTIVE,
                              "borderColor": colors.get(r.grade, INACTIVE)},
                "symbol": "circle" if r.is_active else "emptyCircle",
                "symbolSize": round(7 + 4 * min(desc[k], 60) ** 0.5),
                "children": [node(c) for c in sorted(children[k], key=lambda c: -desc[c])]}

    top = sorted(children[ROOT_ID], key=lambda c: -desc[c])
    return {"name": root_label, "info": f"<b>{html.escape(root_label)}</b><br/>{len(df)} membres",
            "symbolSize": 16, "itemStyle": {"color": "#444"}, "children": [node(c) for c in top]}


def treemap_data(df: pd.DataFrame, root_label: str = "Réseau") -> dict:
    """Arrays for a Plotly treemap: every member has value 1, so an area is proportional to the size of
    that member's branch (branchvalues='remainder')."""
    keys, parent, children, order = index_tree(df)
    desc = descendant_counts(children, order)
    colors = grade_colors(df)
    ids, parents, labels, cols, hover = [ROOT_ID], [""], [root_label], ["#444444"], [f"{len(df)} membres"]
    for k in order:
        r = keys[k]
        ids.append(k)
        parents.append(parent[k])
        labels.append(str(r.name) + ("" if r.is_active else " (inactif)"))
        cols.append(colors.get(r.grade, INACTIVE) if r.is_active else INACTIVE)
        hover.append(_info(r, desc[k]))
    return {"ids": ids, "parents": parents, "labels": labels, "colors": cols, "hover": hover,
            "values": [0] + [1] * len(order)}


def echarts_html(tree: dict, height: int = 780, initial_depth: int = 2, echarts_path: str | None = None) -> str:
    """Self-contained HTML (ECharts inlined, nothing loaded from the internet) for st.components.v1.html."""
    lib = Path(echarts_path or os.environ.get("CNP_ECHARTS", "/opt/echarts.min.js")).read_text(encoding="utf-8")
    payload = (json.dumps(tree, ensure_ascii=False)
               .replace("</", "<\\/").replace("<!--", "\\u003c!--")        # names can't close or confuse the script tag
               .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;height:100%;font-family:sans-serif}} #c{{width:100%;height:{height}px}}</style></head>
<body><div id="c"></div><script>{lib}</script><script>
const tree = {payload};
const chart = echarts.init(document.getElementById('c'));
chart.setOption({{
  tooltip: {{trigger: 'item', triggerOn: 'mousemove', confine: true,
            formatter: p => (p.data && p.data.info) || p.name}},
  series: [{{type: 'tree', data: [tree], top: '2%', bottom: '2%', left: '14%', right: '24%', orient: 'LR',
            initialTreeDepth: {int(initial_depth)}, expandAndCollapse: true, animationDuration: 250,
            label: {{position: 'left', verticalAlign: 'middle', align: 'right', fontSize: 11}},
            leaves: {{label: {{position: 'right', verticalAlign: 'middle', align: 'left'}}}},
            emphasis: {{focus: 'descendant'}}, roam: true}}]
}});
window.addEventListener('resize', () => chart.resize());
</script></body></html>"""
