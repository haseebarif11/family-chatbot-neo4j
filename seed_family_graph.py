#!/usr/bin/env python3
"""
One-time seed: load the full family tree into Neo4j.

Uses family_kb.pl as the source of truth.
Equivalent to: python migrate_pl_to_neo4j.py --clear

Usage:
    python seed_family_graph.py [--clear]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from migrate_pl_to_neo4j import migrate


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed Neo4j with the full family tree from family_kb.pl"
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Delete all existing graph data before seeding",
    )
    args = parser.parse_args()
    pl_path = Path(__file__).resolve().parent / "family_kb.pl"
    migrate(pl_path, clear=args.clear)


if __name__ == "__main__":
    main()
