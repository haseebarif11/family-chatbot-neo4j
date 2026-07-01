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
        assert "age 5" in msg.lower()
        assert "Usman" in msg

    def test_graph_report_nonempty(self, neo4j_engine):
        report = neo4j_engine.graph_report()
        assert "14" in report
        assert "Parent-child" in report
        assert "Marriages" in report


class TestGraphVisualization:
    def test_fetch_full_graph(self, neo4j_engine):
        nodes, edges = neo4j_engine.fetch_full_graph()
        assert len(nodes) == 14
        assert any(e["type"] == "PARENT_OF" for e in edges)
        assert any(e["type"] == "MARRIED_TO" for e in edges)

    def test_fetch_subgraph(self, neo4j_engine):
        nodes, edges = neo4j_engine.fetch_subgraph("ali")
        names = {n["name"] for n in nodes}
        assert "ali" in names
        assert len(names) >= 3

    def test_fetch_highlight_path(self, neo4j_engine):
        nodes, edges, path_nodes, path_edges = neo4j_engine.fetch_highlight_path(
            "ahmed", "nadia"
        )
        assert len(nodes) == 14
        assert "ahmed" in path_nodes
        assert "nadia" in path_nodes
        assert len(path_edges) >= 1

    def test_pyvis_html_generation(self, neo4j_engine):
        from graph_viz import build_full_graph_html

        nodes, edges = neo4j_engine.fetch_full_graph()
        html = build_full_graph_html(nodes, edges)
        assert "<html" in html.lower()
        assert "vis-network" in html.lower() or "network" in html.lower()


class TestPrologBridge:
    def test_export_neo4j_to_prolog(self, neo4j_engine):
        from prolog_bridge import export_neo4j_to_prolog, EXPORT_PATH

        path = export_neo4j_to_prolog()
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert "parent(" in text
        assert "male(" in text
        assert "father(" in text  # derived rules appended

    def test_prolog_query_cousins(self, neo4j_engine):
        from prolog_bridge import export_neo4j_to_prolog, query_prolog

        export_neo4j_to_prolog()
        answers, engine = query_prolog("cousin", "laiba")
        assert engine
        assert "ahmed" in answers

    def test_sync_prolog_bridge(self, neo4j_engine):
        from prolog_bridge import sync_prolog_bridge

        msg = sync_prolog_bridge()
        assert "Bridge Sync Complete" in msg
        report = neo4j_engine.graph_report()
        assert "Inferred (Prolog)" in report
