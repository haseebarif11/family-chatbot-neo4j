"""Integration tests for FamilyGraphEngine (requires live Neo4j)."""
from __future__ import annotations


class TestBasicRelations:
    def test_father_mother_laiba(self, neo4j_engine):
        e = neo4j_engine
        assert e.query_relation("father", "laiba") == ["ali"]
        assert e.query_relation("mother", "laiba") == ["zara"]

    def test_sibling_laiba(self, neo4j_engine):
        assert neo4j_engine.query_relation("sibling", "laiba") == ["usman"]


class TestIntermarriedBranch:
    """Ali married cousin Zara; Laiba/Usman have both as parents."""

    def test_uncle_laiba(self, neo4j_engine):
        assert neo4j_engine.query_relation("uncle", "laiba") == ["haider", "sohail"]

    def test_aunt_laiba_not_grandmothers(self, neo4j_engine):
        aunts = neo4j_engine.query_relation("aunt", "laiba")
        assert "nadia" not in aunts
        assert "rukhsana" not in aunts
        assert "hina" in aunts

    def test_cousin_laiba_excludes_parents_and_aunts(self, neo4j_engine):
        cousins = neo4j_engine.query_relation("cousin", "laiba")
        assert "ali" not in cousins
        assert "zara" not in cousins
        assert "sara" not in cousins
        assert "ahmed" in cousins
        assert "lina" in cousins

    def test_cousin_ali_excludes_spouse_zara(self, neo4j_engine):
        cousins = neo4j_engine.query_relation("cousin", "ali")
        assert "zara" not in cousins

    def test_nephew_niece_sara_and_ali(self, neo4j_engine):
        e = neo4j_engine
        assert e.query_relation("nephew", "ali") == []
        assert e.query_relation("niece", "sara") == ["laiba"]

    def test_nephew_haider_includes_usman(self, neo4j_engine):
        nephews = neo4j_engine.query_relation("nephew", "haider")
        assert "usman" in nephews
        assert "ahmed" in nephews


class TestInference:
    def test_mutual_connections_ahmed_laiba(self, neo4j_engine):
        msg = neo4j_engine.mutual_connections("ahmed", "laiba")
        assert "Ahmed" in msg and "Laiba" in msg
        assert "ancestor" in msg.lower() or "connected" in msg.lower()

    def test_hidden_relationship_ahmed_nadia(self, neo4j_engine):
        msg = neo4j_engine.hidden_relationship("ahmed", "nadia")
        assert "Ahmed" in msg and "Nadia" in msg
        assert len(msg) > 30

    def test_age_similarity_laiba(self, neo4j_engine):
        msg = neo4j_engine.age_similarity("laiba")
        assert "Laiba" in msg
        assert "years old" in msg.lower()
        assert "Usman" in msg

    def test_graph_report_nonempty(self, neo4j_engine):
        report = neo4j_engine.graph_report()
        assert "14" in report
        assert "PARENT_OF" in report
        assert "MARRIED_TO" in report
