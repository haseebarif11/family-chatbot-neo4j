"""Unit tests for list-query phrase detection (no Neo4j required)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import detect_list_intent


class TestDetectListIntent:
    def test_married_couples_variants(self):
        cases = [
            "list married couples",
            "list all married couples",
            "LIST ALL MARRIED COUPLES",
            "show married couples",
            "show all married couples",
            "all married couples",
            "give me all married couples",
            "what are all married couples",
        ]
        for q in cases:
            assert detect_list_intent(q) == "list_married", q

    def test_males_variants(self):
        assert detect_list_intent("all males") == "list_male"
        assert detect_list_intent("list all males") == "list_male"
        assert detect_list_intent("show me all males") == "list_male"

    def test_family_members(self):
        assert detect_list_intent("list all family members") == "members"
        assert detect_list_intent("all family members") == "members"

    def test_relation_query_not_list(self):
        assert detect_list_intent("who is the father of ali") is None
        assert detect_list_intent("fathers of ali") is None
