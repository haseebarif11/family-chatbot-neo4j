#!/usr/bin/env python3
"""
Smoke-test Cypher queries against a live Neo4j instance.

Usage (Neo4j must be running, .env configured):
    python migrate_pl_to_neo4j.py --clear
    python verify_live_queries.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from migrate_pl_to_neo4j import migrate
from neo4j_bridge import close_driver, reset_engine

KB = Path(__file__).resolve().parent / "family_kb.pl"

CHECKS = [
    ("father", "ali", lambda r: r == ["haider"]),
    ("mother", "ali", lambda r: r == ["nadia"]),
    ("cousin", "laiba", lambda r: "ali" not in r and "ahmed" in r),
    ("uncle", "laiba", lambda r: r == ["haider", "sohail"]),
]


def main() -> int:
    print("Migrating seed data...")
    migrate(KB, clear=True)
    engine = reset_engine()
    failed = 0

    print("\n--- query_relation ---")
    for rel, person, pred in CHECKS:
        result = engine.query_relation(rel, person)
        ok = pred(result)
        status = "OK" if ok else "FAIL"
        print(f"  [{status}] {rel}({person}) -> {result}")
        if not ok:
            failed += 1

    print("\n--- inference ---")
    for label, fn, check in [
        ("mutual_connections(ahmed, laiba)", lambda: engine.mutual_connections("ahmed", "laiba"), lambda s: "Ahmed" in s),
        ("hidden_relationship(ahmed, nadia)", lambda: engine.hidden_relationship("ahmed", "nadia"), lambda s: len(s) > 20),
        ("age_similarity(laiba)", lambda: engine.age_similarity("laiba"), lambda s: "Laiba" in s),
        ("graph_report()", lambda: engine.graph_report(), lambda s: "14" in s),
    ]:
        try:
            out = fn()
            ok = check(out)
            print(f"  [{'OK' if ok else 'FAIL'}] {label}")
            if not ok:
                print(f"       output: {out[:120]}...")
                failed += 1
        except Exception as exc:
            print(f"  [ERROR] {label}: {exc}")
            failed += 1

    close_driver()
    if failed:
        print(f"\n{failed} check(s) failed.")
        return 1
    print("\nAll live checks passed.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"Could not connect or run checks: {exc}", file=sys.stderr)
        sys.exit(2)
