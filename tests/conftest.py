"""Pytest fixtures for live Neo4j integration tests."""
from __future__ import annotations

from pathlib import Path

import pytest
from neo4j.exceptions import ServiceUnavailable

ROOT = Path(__file__).resolve().parent.parent
KB = ROOT / "family_kb.pl"


def _neo4j_reachable() -> bool:
    try:
        from neo4j_bridge import close_driver, get_driver

        driver = get_driver()
        driver.verify_connectivity()
        return True
    except (ServiceUnavailable, OSError):
        return False
    finally:
        try:
            from neo4j_bridge import close_driver

            close_driver()
        except Exception:
            pass


@pytest.fixture(scope="session")
def neo4j_engine():
    """
    Seed family_kb.pl into Neo4j and return a fresh FamilyGraphEngine.

    Skips when Neo4j is not running. Requires:
      - bolt://localhost:7687
      - credentials in family_chatbot/.env (copy from .env.example)
    """
    if not _neo4j_reachable():
        pytest.skip(
            "Neo4j not reachable at bolt://localhost:7687 — "
            "start Neo4j Desktop or Docker, configure .env, then re-run pytest."
        )

    from migrate_pl_to_neo4j import migrate
    from neo4j_bridge import close_driver, reset_engine

    migrate(KB, clear=True)
    engine = reset_engine()
    yield engine
    close_driver()
