"""
Interactive family-graph visualization using PyVis.

Uses a fixed generation-based layout (no physics clutter).
Only structural edges (parent + marriage) are drawn by default.
"""

from __future__ import annotations

from collections import defaultdict, deque

from pyvis.network import Network

_GENDER_COLOR = {
    "male": "#3B82F6",
    "female": "#EC4899",
    None: "#94A3B8",
}

_EDGE_STYLE = {
    "PARENT_OF": {"color": "#64748B", "width": 2},
    "MARRIED_TO": {"color": "#10B981", "width": 2},
}

_HIGHLIGHT_NODE = "#F59E0B"
_HIGHLIGHT_EDGE = "#DC2626"


def _structural_edges(edges: list[dict]) -> list[dict]:
    """Keep only parent and marriage links for a readable tree view."""
    return [e for e in edges if e.get("type") in ("PARENT_OF", "MARRIED_TO")]


def _node_label(name: str) -> str:
    return name.capitalize()


def _compute_levels(names: set[str], edges: list[dict]) -> dict[str, int]:
    parents_of: dict[str, set[str]] = defaultdict(set)
    children_of: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        if e["type"] == "PARENT_OF":
            parents_of[e["dst"]].add(e["src"])
            children_of[e["src"]].add(e["dst"])

    level = {n: 0 for n in names}
    roots = [n for n in names if not parents_of.get(n)]
    if not roots:
        roots = [sorted(names)[0]]

    queue: deque[tuple[str, int]] = deque((r, 0) for r in roots)
    seen: set[str] = set()
    while queue:
        node, lv = queue.popleft()
        if node in seen:
            continue
        seen.add(node)
        level[node] = max(level.get(node, 0), lv)
        for child in children_of.get(node, ()):
            queue.append((child, lv + 1))

    for _ in range(len(names)):
        changed = False
        for e in edges:
            if e["type"] == "MARRIED_TO":
                a, b = e["src"], e["dst"]
                shared = min(level.get(a, 0), level.get(b, 0))
                if level.get(a, 0) != shared:
                    level[a] = shared
                    changed = True
                if level.get(b, 0) != shared:
                    level[b] = shared
                    changed = True
        if not changed:
            break

    for n in names:
        level.setdefault(n, 0)
    return level


def _compute_positions(nodes: list[dict], edges: list[dict]) -> dict[str, tuple[float, float]]:
    names = {n["name"] for n in nodes}
    levels = _compute_levels(names, edges)
    by_level: dict[int, list[str]] = defaultdict(list)
    for n in nodes:
        by_level[levels[n["name"]]].append(n["name"])

    x_gap, y_gap = 140, 110
    positions: dict[str, tuple[float, float]] = {}
    for lv in sorted(by_level):
        row = sorted(by_level[lv])
        row_w = (len(row) - 1) * x_gap
        for i, name in enumerate(row):
            positions[name] = (i * x_gap - row_w / 2, lv * y_gap)
    return positions


def render_graph_html(
    nodes: list[dict],
    edges: list[dict],
    *,
    title: str = "Family Graph",
    highlight_nodes: set[str] | None = None,
    highlight_edges: set[tuple[str, str, str]] | None = None,
    height: str = "580px",
    width: str = "100%",
    structural_only: bool = True,
) -> str:
    highlight_nodes = highlight_nodes or set()
    highlight_edges = highlight_edges or set()

    if structural_only:
        edges = _structural_edges(edges)

    positions = _compute_positions(nodes, edges)

    net = Network(
        height=height,
        width=width,
        directed=True,
        bgcolor="#FAFAFA",
        font_color="#1E293B",
        heading=title,
    )
    net.toggle_physics(False)
    net.set_options(
        """
        {
          "nodes": {
            "font": {"size": 15, "face": "Segoe UI", "color": "#1E293B"},
            "shape": "box",
            "margin": 10,
            "borderWidth": 2,
            "shadow": true
          },
          "edges": {
            "font": {"size": 0},
            "smooth": {"type": "cubicBezier", "forceDirection": "vertical"},
            "arrows": {"to": {"enabled": true, "scaleFactor": 0.45}}
          },
          "interaction": {
            "hover": true,
            "navigationButtons": true,
            "keyboard": true,
            "tooltipDelay": 80
          }
        }
        """
    )

    for node in nodes:
        name = node["name"]
        gender = node.get("gender")
        age = node.get("age")
        is_hi = name in highlight_nodes
        x, y = positions.get(name, (0.0, 0.0))
        tooltip = f"{name.capitalize()}"
        if gender:
            tooltip += f" ({gender})"
        if age is not None:
            tooltip += f", age {age}"
        color = _HIGHLIGHT_NODE if is_hi else _GENDER_COLOR.get(gender, _GENDER_COLOR[None])
        net.add_node(
            name,
            label=_node_label(name),
            color=color,
            x=x,
            y=y,
            fixed={"x": True, "y": True},
            borderWidth=3 if is_hi else 2,
            size=28 if is_hi else 22,
            title=tooltip,
        )

    drawn_marriage: set[tuple[str, str]] = set()
    for edge in edges:
        src, dst = edge["src"], edge["dst"]
        rel = edge.get("type", "REL")
        if rel == "MARRIED_TO":
            key = tuple(sorted([src, dst]))
            if key in drawn_marriage:
                continue
            drawn_marriage.add(key)

        style = _EDGE_STYLE.get(rel, {"color": "#CBD5E1", "width": 1})
        key = (src, dst, rel)
        is_hi = key in highlight_edges or (rel == "MARRIED_TO" and tuple(sorted([src, dst])) in {
            tuple(sorted([a, b])) for a, b, t in highlight_edges if t == "MARRIED_TO"
        })
        dashes = rel == "MARRIED_TO"
        net.add_edge(
            src,
            dst,
            color=_HIGHLIGHT_EDGE if is_hi else style["color"],
            width=4 if is_hi else style["width"],
            dashes=dashes,
            title=rel.replace("_", " ").title(),
            arrows="" if dashes else "to",
        )

    return net.generate_html(notebook=False)


def build_full_graph_html(nodes: list[dict], edges: list[dict]) -> str:
    return render_graph_html(nodes, edges, title="Family Tree (full graph)")


def build_subgraph_html(
    nodes: list[dict],
    edges: list[dict],
    center: str,
) -> str:
    center = center.lower()
    return render_graph_html(
        nodes,
        edges,
        title=f"Family Tree — {center.capitalize()} (nearby relatives)",
        highlight_nodes={center},
    )


def build_highlighted_path_html(
    nodes: list[dict],
    edges: list[dict],
    path_nodes: set[str],
    path_edges: set[tuple[str, str, str]],
    p1: str,
    p2: str,
) -> str:
    path_nodes = {n.lower() for n in path_nodes}
    viz_nodes = [n for n in nodes if n["name"] in path_nodes]
    viz_edges = [
        e for e in _structural_edges(edges)
        if e["src"] in path_nodes and e["dst"] in path_nodes
    ]
    return render_graph_html(
        viz_nodes,
        viz_edges,
        title=f"Path — {p1.capitalize()} to {p2.capitalize()}",
        highlight_nodes=path_nodes,
        highlight_edges=path_edges,
        structural_only=False,
    )
