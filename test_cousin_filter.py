"""
Regression tests for cousin/nephew/niece disambiguation in FamilyGraphEngine.

Runs WITHOUT a live Neo4j connection by monkey-patching _query_cypher and
_driver so no database is required.

Seed data topology (from family_kb.pl):
    kamran + rukhsana → haider, sara_aunt=sara, hina, zara, sohail
    haider + nadia   → ali, sara
    ali + zara       → laiba, usman
    hina + ?         → lina
    sohail + sarah   → ahmed
    hina + sohail    → ahmed   (ahmed's parents hina & sohail are siblings → ahmed & lina are siblings)

Bugs being regressed:
  BUG 1: cousin(ahmed) must NOT contain "lina"  (they are siblings, not cousins)
  BUG 2: cousin(sara)  must NOT contain "laiba" (laiba is sara's niece)
  BUG 2: cousin(sara)  must NOT contain "usman" (usman is sara's nephew)
  POSITIVE: cousin(sara) MUST still contain "ahmed" and "lina" (genuine cousins)
"""

from __future__ import annotations
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# We need to import neo4j_bridge without actually connecting to Neo4j.
# Patch get_driver to return a mock, and ensure_schema to be a no-op before
# importing the module.
# ---------------------------------------------------------------------------
neo4j_mock = types.ModuleType("neo4j")
neo4j_mock.GraphDatabase = MagicMock()
neo4j_mock.Driver = object
neo4j_mock.Session = object
sys.modules.setdefault("neo4j", neo4j_mock)

# Stub dotenv so it doesn't error if not installed
dotenv_mock = types.ModuleType("dotenv")
dotenv_mock.load_dotenv = lambda *a, **kw: None
sys.modules.setdefault("dotenv", dotenv_mock)

import importlib
import os

# Point to a fake password so ensure_schema doesn't fail on import
os.environ.setdefault("NEO4J_PASSWORD", "test")

# Now import the module
import neo4j_bridge
from neo4j_bridge import FamilyGraphEngine, normalize_relation


# ---------------------------------------------------------------------------
# Encode the full seed family_kb.pl topology as a Python lookup table.
# This mirrors exactly what _query_cypher would return for each relation+person.
# ---------------------------------------------------------------------------

# Raw parent/child relationships from family_kb.pl
PARENTS = {
    "ali":    ["haider", "nadia"],
    "sara":   ["haider", "nadia"],
    "laiba":  ["ali", "zara"],
    "usman":  ["ali", "zara"],
    "haider": ["kamran", "rukhsana"],
    "hina":   ["kamran", "rukhsana"],
    "zara":   ["kamran", "rukhsana"],
    "sohail": ["kamran", "rukhsana"],
    "lina":   ["hina"],
    "ahmed":  ["hina", "sohail"],
}
CHILDREN = {}
for child, parents in PARENTS.items():
    for p in parents:
        CHILDREN.setdefault(p, []).append(child)

GENDER = {
    "kamran": "male", "haider": "male", "ali": "male",
    "usman": "male", "sohail": "male", "ahmed": "male",
    "nadia": "female", "sara": "female", "laiba": "female",
    "zara": "female", "rukhsana": "female", "hina": "female",
    "lina": "female", "sarah": "female",
}

MARRIED = {
    "haider": "nadia", "nadia": "haider",
    "ali": "zara", "zara": "ali",
    "kamran": "rukhsana", "rukhsana": "kamran",
    "sohail": "sarah", "sarah": "sohail",
}


def _siblings(person):
    parents = PARENTS.get(person, [])
    sibs = set()
    for p in parents:
        for child in CHILDREN.get(p, []):
            if child != person:
                sibs.add(child)
    return sorted(sibs)


def _ancestors(person, seen=None):
    if seen is None:
        seen = set()
    result = []
    for p in PARENTS.get(person, []):
        if p not in seen:
            seen.add(p)
            result.append(p)
            result.extend(_ancestors(p, seen))
    return result


def mock_query_cypher(self, relation, person, inverse):
    """Simulate _query_cypher using the seed data lookup tables."""
    person = person.strip().lower()
    rel = normalize_relation(relation)

    if rel == "father":
        return [p for p in PARENTS.get(person, []) if GENDER.get(p) == "male"]
    if rel == "mother":
        return [p for p in PARENTS.get(person, []) if GENDER.get(p) == "female"]
    if rel == "parent":
        return list(PARENTS.get(person, []))
    if rel == "children":
        return list(CHILDREN.get(person, []))
    if rel == "son":
        return [c for c in CHILDREN.get(person, []) if GENDER.get(c) == "male"]
    if rel == "daughter":
        return [c for c in CHILDREN.get(person, []) if GENDER.get(c) == "female"]
    if rel == "sibling":
        return _siblings(person)
    if rel == "brother":
        return [s for s in _siblings(person) if GENDER.get(s) == "male"]
    if rel == "sister":
        return [s for s in _siblings(person) if GENDER.get(s) == "female"]
    if rel == "spouse":
        return [MARRIED[person]] if person in MARRIED else []
    if rel == "husband":
        sp = MARRIED.get(person)
        return [sp] if sp and GENDER.get(sp) == "male" else []
    if rel == "wife":
        sp = MARRIED.get(person)
        return [sp] if sp and GENDER.get(sp) == "female" else []
    if rel == "uncle":
        # brothers of parents
        result = set()
        for par in PARENTS.get(person, []):
            for sib in _siblings(par):
                if GENDER.get(sib) == "male":
                    result.add(sib)
        return sorted(result)
    if rel == "aunt":
        # sisters of parents
        result = set()
        for par in PARENTS.get(person, []):
            for sib in _siblings(par):
                if GENDER.get(sib) == "female":
                    result.add(sib)
        return sorted(result)
    if rel == "nephew":
        # sons of siblings
        result = set()
        for sib in _siblings(person):
            for child in CHILDREN.get(sib, []):
                if GENDER.get(child) == "male":
                    result.add(child)
        return sorted(result)
    if rel == "niece":
        # daughters of siblings
        result = set()
        for sib in _siblings(person):
            for child in CHILDREN.get(sib, []):
                if GENDER.get(child) == "female":
                    result.add(child)
        return sorted(result)
    if rel == "cousin":
        # children of parent's siblings
        result = set()
        for par in PARENTS.get(person, []):
            for par_sib in _siblings(par):
                for child in CHILDREN.get(par_sib, []):
                    if child != person:
                        result.add(child)
        return sorted(result)
    if rel == "sister_in_law":
        sp = MARRIED.get(person)
        if not sp:
            return []
        return [s for s in _siblings(sp) if GENDER.get(s) == "female"]
    if rel == "brother_in_law":
        sp = MARRIED.get(person)
        if not sp:
            return []
        return [s for s in _siblings(sp) if GENDER.get(s) == "male"]
    if rel == "ancestor":
        return sorted(set(_ancestors(person)))
    return []


class TestCousinFilter(unittest.TestCase):

    def setUp(self):
        # Create engine without connecting to Neo4j
        with patch.object(neo4j_bridge, "get_driver", return_value=MagicMock()), \
             patch.object(neo4j_bridge, "ensure_schema", return_value=None):
            self.engine = FamilyGraphEngine.__new__(FamilyGraphEngine)
            self.engine._driver = MagicMock()

        # Replace _query_cypher with our seed-data mock
        FamilyGraphEngine._query_cypher = mock_query_cypher

    # ── BUG 1 regression ────────────────────────────────────────────────────

    def test_cousin_ahmed_excludes_lina(self):
        """Ahmed & Lina share parents Hina (mother of both) and Sohail
        (father of Ahmed, Hina is Lina's mother — they are siblings, NOT cousins)."""
        cousins = self.engine.query_relation("cousin", "ahmed")
        self.assertNotIn("lina", cousins,
                         f"BUG 1: 'lina' wrongly appears in cousin(ahmed) = {cousins}")

    def test_sibling_ahmed_contains_lina(self):
        """Sanity-check: ahmed and lina ARE siblings (confirm mock is correct)."""
        siblings = self.engine.query_relation("sibling", "ahmed")
        self.assertIn("lina", siblings,
                      f"Mock error: 'lina' should be a sibling of ahmed, got {siblings}")

    # ── BUG 2 regression ────────────────────────────────────────────────────

    def test_cousin_sara_excludes_laiba(self):
        """Laiba is Sara's niece (Sara's brother Ali's daughter), not a cousin."""
        cousins = self.engine.query_relation("cousin", "sara")
        self.assertNotIn("laiba", cousins,
                         f"BUG 2: 'laiba' wrongly appears in cousin(sara) = {cousins}")

    def test_cousin_sara_excludes_usman(self):
        """Usman is Sara's nephew (Sara's brother Ali's son), not a cousin."""
        cousins = self.engine.query_relation("cousin", "sara")
        self.assertNotIn("usman", cousins,
                         f"BUG 2: 'usman' wrongly appears in cousin(sara) = {cousins}")

    # ── Positive cases (genuine cousins must still appear) ─────────────────

    def test_cousin_sara_contains_ahmed(self):
        """Ahmed is Sara's genuine cousin via aunt Hina."""
        cousins = self.engine.query_relation("cousin", "sara")
        self.assertIn("ahmed", cousins,
                      f"Regression: 'ahmed' missing from cousin(sara) = {cousins}")

    def test_cousin_sara_contains_lina(self):
        """Lina is Sara's genuine cousin via aunt Hina."""
        cousins = self.engine.query_relation("cousin", "sara")
        self.assertIn("lina", cousins,
                      f"Regression: 'lina' missing from cousin(sara) = {cousins}")

    # ── Niece/nephew sanity ──────────────────────────────────────────────────

    def test_niece_sara_contains_laiba(self):
        """Laiba IS Sara's niece — must still be returned by niece(sara)."""
        nieces = self.engine.query_relation("niece", "sara")
        self.assertIn("laiba", nieces,
                      f"Regression: 'laiba' missing from niece(sara) = {nieces}")

    def test_nephew_sara_contains_usman(self):
        """Usman IS Sara's nephew — must still be returned by nephew(sara)."""
        nephews = self.engine.query_relation("nephew", "sara")
        self.assertIn("usman", nephews,
                      f"Regression: 'usman' missing from nephew(sara) = {nephews}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
