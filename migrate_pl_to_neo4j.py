#!/usr/bin/env python3
"""
One-time migration: parse family_kb.pl facts and load them into Neo4j.

Usage:
    python migrate_pl_to_neo4j.py [--pl path/to/family_kb.pl] [--clear]

Requires Neo4j running at bolt://localhost:7687 with credentials in .env
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from neo4j_bridge import (
    add_marriage,
    add_parent,
    ensure_schema,
    get_driver,
    set_age,
    set_dob,
    set_gender,
)


def parse_pl_facts(path: Path) -> dict:
    """Parse base facts from a Prolog knowledge-base file (rules are skipped)."""
    facts = {
        "parent": set(),
        "male": set(),
        "female": set(),
        "married": set(),
        "age": {},
        "dob": {},
    }
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("%") or ":-" in line:
            continue
        if m := re.match(r"parent\((\w+),\s*(\w+)\)", line):
            facts["parent"].add((m[1], m[2]))
        elif m := re.match(r"male\((\w+)\)", line):
            facts["male"].add(m[1])
        elif m := re.match(r"female\((\w+)\)", line):
            facts["female"].add(m[1])
        elif m := re.match(r"married\((\w+),\s*(\w+)\)", line):
            facts["married"].add((m[1], m[2]))
        elif m := re.match(r"age\((\w+),\s*(\d+)\)", line):
            facts["age"][m[1]] = int(m[2])
        elif m := re.match(r"dob\((\w+),\s*'([^']+)'\)", line):
            facts["dob"][m[1]] = m[2]
    return facts


def migrate(path: Path, clear: bool = False) -> None:
    if not path.exists():
        print(f"Error: {path} not found", file=sys.stderr)
        sys.exit(1)

    facts = parse_pl_facts(path)
    driver = get_driver()

    with driver.session() as session:
        ensure_schema(session)

        if clear:
            session.run("MATCH (n) DETACH DELETE n")
            print("Cleared existing graph data.")

        for name in facts["male"]:
            set_gender(session, name, "male")
        for name in facts["female"]:
            set_gender(session, name, "female")

        for parent, child in facts["parent"]:
            add_parent(session, parent, child)

        seen_marriages: set[tuple[str, str]] = set()
        for a, b in facts["married"]:
            key = tuple(sorted([a, b]))
            if key not in seen_marriages:
                seen_marriages.add(key)
                add_marriage(session, a, b)

        for name, age in facts["age"].items():
            set_age(session, name, age)

        for name, dob in facts["dob"].items():
            set_dob(session, name, dob)

        counts = session.run(
            "MATCH (p:Person) WITH count(p) AS people "
            "OPTIONAL MATCH ()-[r:PARENT_OF]->() WITH people, count(r) AS parents "
            "OPTIONAL MATCH ()-[m:MARRIED_TO]-() "
            "RETURN people, parents, toInteger(count(m) / 2) AS marriages"
        ).single() or {"people": 0, "parents": 0, "marriages": 0}

    print(f"Migrated from {path}:")
    print(f"  Persons:    {counts['people']}")
    print(f"  PARENT_OF:  {counts['parents']}")
    print(f"  Marriages:  {counts['marriages']}")
    print(f"  Parent facts parsed: {len(facts['parent'])}")
    print(f"  Male:       {len(facts['male'])}")
    print(f"  Female:     {len(facts['female'])}")
    print(f"  Age facts:  {len(facts['age'])}")
    print(f"  DOB facts:  {len(facts['dob'])}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate Prolog facts to Neo4j")
    parser.add_argument(
        "--pl",
        type=Path,
        default=Path(__file__).resolve().parent / "family_kb.pl",
        help="Path to family_kb.pl",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Delete all existing graph data before migrating",
    )
    args = parser.parse_args()
    migrate(args.pl, clear=args.clear)


if __name__ == "__main__":
    main()
