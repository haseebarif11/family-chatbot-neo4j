#!/usr/bin/env python3
"""Smoke-test PyVis visualization and Neo4j-Prolog bridge (requires Neo4j)."""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))


def main() -> int:
    print("=" * 60)
    print("Family Chatbot - New Features Verification")
    print("=" * 60)

    # 1. Imports
    print("\n[1/6] Checking imports...")
    try:
        from graph_viz import build_full_graph_html, build_subgraph_html, build_highlighted_path_html
        from prolog_bridge import export_neo4j_to_prolog, query_prolog, sync_prolog_bridge
        from neo4j_bridge import create_engine, list_family_members
    except ImportError as e:
        print(f"  FAIL: {e}")
        print("  Run: pip install -r requirements.txt")
        return 1
    print("  OK")

    # 2. Neo4j connection
    print("\n[2/6] Connecting to Neo4j...")
    try:
        engine, label = create_engine()
        members = list_family_members()
        print(f"  OK - engine={label}, members={len(members)}")
    except Exception as e:
        print(f"  FAIL: {e}")
        print("  Start Neo4j and check .env (NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)")
        return 1

    if len(members) == 0:
        print("  Database empty - run: python migrate_pl_to_neo4j.py --clear")
        return 1

    # 3. Graph data
    print("\n[3/6] Graph fetch (full / subgraph / highlight)...")
    nodes, edges = engine.fetch_full_graph()
    sub_nodes, sub_edges = engine.fetch_subgraph("ali")
    _, _, path_nodes, path_edges = engine.fetch_highlight_path("ahmed", "nadia")
    print(f"  Full graph: {len(nodes)} nodes, {len(edges)} edges")
    print(f"  Subgraph (Ali): {len(sub_nodes)} nodes, {len(sub_edges)} edges")
    print(f"  Path Ahmed->Nadia: {len(path_nodes)} nodes, {len(path_edges)} edges")
    assert len(nodes) >= 1 and len(edges) >= 1
    print("  OK")

    # 4. PyVis HTML
    print("\n[4/6] PyVis HTML generation...")
    html_full = build_full_graph_html(nodes, edges)
    html_sub = build_subgraph_html(sub_nodes, sub_edges, "ali")
    html_hi = build_highlighted_path_html(
        nodes, edges, path_nodes, path_edges, "ahmed", "nadia"
    )
    for name, html in [("full", html_full), ("subgraph", html_sub), ("highlight", html_hi)]:
        if "<html" not in html.lower():
            print(f"  FAIL: {name} HTML invalid")
            return 1
    out = BASE / "_test_viz.html"
    out.write_text(html_full, encoding="utf-8")
    print(f"  OK - sample saved to {out.name} (open in browser)")

    # 5. Prolog export + query
    print("\n[5/6] Prolog bridge export + query...")
    pl_path = export_neo4j_to_prolog()
    print(f"  Exported: {pl_path.name}")
    cousins, eng = query_prolog("cousin", "laiba")
    print(f"  cousin(X, laiba) via {eng}: {', '.join(cousins[:5])}{'...' if len(cousins) > 5 else ''}")
    assert "ahmed" in cousins
    print("  OK")

    # 6. Full sync
    print("\n[6/6] Prolog bridge sync -> Neo4j INFERRED edges...")
    msg = sync_prolog_bridge()
    assert "Bridge Sync Complete" in msg
    inferred_edges = [e for e in engine.fetch_full_graph()[1] if e.get("category") == "INFERRED"]
    print(f"  Inferred edges in graph: {len(inferred_edges)}")
    print("  OK")

    print("\n" + "=" * 60)
    print("All checks passed.")
    print("Run the app: streamlit run app.py")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
