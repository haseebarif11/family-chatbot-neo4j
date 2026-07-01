"""
Neo4j graph engine for the Family Tree Chatbot.

Replaces the Prolog/Python fact engine with Cypher graph traversals that
mirror every rule in family_kb.pl. Exposes the same public interface as
the original FamilyEngine so app.py needs minimal changes.

Includes: connection config (formerly neo4j_config.py) and AIML data-entry
helpers (formerly data_entry.py).
"""

from __future__ import annotations

import os
import re
from collections import deque
from pathlib import Path
from typing import Any, Callable

from neo4j import GraphDatabase, Driver, Session

# ── Connection config (was neo4j_config.py) ────────────────────────────────
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

RELATION_ALIASES = {
    "parents": "parent", "parent": "parent",
    "siblings": "sibling", "children": "children",
    "child": "children", "kids": "children",
    "sons": "son", "daughters": "daughter",
    "wives": "wife", "husbands": "husband",
    "spouses": "spouse", "fathers": "father",
    "mother": "mother", "mothers": "mother",
    "grandfathers": "grandfather", "grandmothers": "grandmother",
    "grandparents": "grandparent", "grandchildren": "grandchild",
    "brothers": "brother", "sisters": "sister",
    "uncles": "uncle", "aunts": "aunt",
    "cousins": "cousin", "nephews": "nephew",
    "nieces": "niece", "married": "spouse", "married_to": "spouse",
    "ancestors": "ancestor", "descendants": "descendant",
    "date_of_birth": "dob",
    "elder_siblings": "elder_sibling", "older_sibling": "elder_sibling",
    "older_siblings": "elder_sibling", "younger_siblings": "younger_sibling",
    "paternal_grandfathers": "paternal_grandfather",
    "same_generation": "same_generation",
}


def normalize_relation(rel: str) -> str:
    rel = re.sub(r"^(all\s+the\s+|all\s+|the\s+)", "", rel.strip(), flags=re.I)
    key = re.sub(r"[\s-]+", "_", rel.strip().lower())
    return RELATION_ALIASES.get(key, key)


_driver: Driver | None = None


def get_driver() -> Driver:
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    return _driver


def close_driver() -> None:
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


def ensure_schema(session: Session) -> None:
    session.run(
        "CREATE CONSTRAINT person_name IF NOT EXISTS "
        "FOR (p:Person) REQUIRE p.name IS UNIQUE"
    )


def _names(result) -> list[str]:
    return sorted({r["name"] for r in result if r.get("name")})


def _path_step_phrase(src: str, rel: str, dst: str) -> str:
    s, d = src.capitalize(), dst.capitalize()
    if rel == "parent_of":
        return f"{s} is the parent of {d}"
    if rel == "child_of":
        return f"{s} is the child of {d}"
    return f"{s} is married to {d}"


def _path_to_numbered_list(path: list[tuple[str, str, str]]) -> str:
    return "\n".join(
        f"{i}. {_path_step_phrase(src, rel, dst)}."
        for i, (src, rel, dst) in enumerate(path, 1)
    )


def _path_to_prose(path: list[tuple[str, str, str]]) -> str:
    phrases = [_path_step_phrase(src, rel, dst) for src, rel, dst in path]
    if not phrases:
        return ""
    if len(phrases) == 1:
        return phrases[0] + "."
    return ", ".join(phrases[:-1]) + f", and {phrases[-1]}."


class FamilyGraphEngine:
    """Neo4j-backed family relationship engine."""

    def __init__(self) -> None:
        self._driver = get_driver()
        with self._driver.session() as session:
            ensure_schema(session)

    def _run(self, cypher: str, **params: Any) -> list[str]:
        with self._driver.session() as session:
            return _names(session.run(cypher, **params))

    def check_gender(self, person: str, gender: str) -> bool:
        person, gender = person.strip().lower(), gender.strip().lower()
        with self._driver.session() as session:
            rec = session.run(
                "MATCH (p:Person {name: $person, gender: $gender}) RETURN p.name LIMIT 1",
                person=person,
                gender=gender,
            ).single()
            return rec is not None

    def query_relation(self, relation: str, person: str, inverse: bool = False) -> list[str]:
        person = person.strip().lower()
        relation = normalize_relation(relation)
        results = self._query_cypher(relation, person, inverse)
        if relation in ("cousin", "nephew", "niece"):
            filtered = []
            for candidate in results:
                # Exclude if candidate is a parent of the query person
                if candidate in self._query_cypher("father", person, False):
                    continue
                if candidate in self._query_cypher("mother", person, False):
                    continue
                # Exclude if candidate is already an uncle/aunt of the query person
                if candidate in self._query_cypher("uncle", person, False):
                    continue
                if candidate in self._query_cypher("aunt", person, False):
                    continue
                # Exclude if candidate is a sibling of the query person's spouse —
                # i.e. a sister-in-law/brother-in-law (sara ↔ zara via ali)
                if candidate in self._query_cypher("sister_in_law", person, False):
                    continue
                if candidate in self._query_cypher("brother_in_law", person, False):
                    continue
                # For cousin queries only: also exclude candidates who are
                # already siblings, nephews or nieces of the query person.
                # (nephew/niece queries must NOT apply these — they would
                # recursively self-exclude their own valid results.)
                if relation == "cousin":
                    if candidate in self._query_cypher("sibling", person, False):
                        continue
                    if candidate in self._query_cypher("nephew", person, False):
                        continue
                    if candidate in self._query_cypher("niece", person, False):
                        continue
                # Exclude if candidate is an uncle/aunt of ANY other candidate
                # in the same result set — catches intermarried-family cases
                # e.g. sara is laiba's aunt even though laiba ≠ zara (query subject)
                is_aunt_or_uncle_of_peer = any(
                    candidate in (
                        set(self._query_cypher("uncle", other, False))
                        | set(self._query_cypher("aunt",  other, False))
                    )
                    for other in results if other != candidate
                )
                if is_aunt_or_uncle_of_peer:
                    continue
                filtered.append(candidate)
            results = filtered
        return results

    def get_oldest(self, gender_filter: str | None = None) -> str:
        cypher = "MATCH (p:Person) WHERE p.age IS NOT NULL"
        if gender_filter == "male":
            cypher += " AND p.gender = 'male'"
        elif gender_filter == "female":
            cypher += " AND p.gender = 'female'"
        cypher += " RETURN p.name AS name ORDER BY p.age DESC LIMIT 1"
        with self._driver.session() as session:
            rec = session.run(cypher).single()
            return rec["name"] if rec else ""

    def query_list(self, list_type: str) -> list[str]:
        if list_type == "list_male":
            return self._run("MATCH (p:Person {gender: 'male'}) RETURN p.name AS name")
        if list_type == "list_female":
            return self._run("MATCH (p:Person {gender: 'female'}) RETURN p.name AS name")
        if list_type == "list_parent":
            return self._run(
                "MATCH (p:Person)-[:PARENT_OF]->(:Person) RETURN DISTINCT p.name AS name"
            )
        if list_type == "list_child":
            return self._run(
                "MATCH (:Person)-[:PARENT_OF]->(c:Person) RETURN DISTINCT c.name AS name"
            )
        if list_type == "list_age":
            with self._driver.session() as session:
                rows = session.run(
                    "MATCH (p:Person) WHERE p.age IS NOT NULL "
                    "RETURN p.name AS name, p.age AS age ORDER BY age DESC"
                )
                return [f"{r['name']}:{r['age']}" for r in rows]
        if list_type == "list_married":
            with self._driver.session() as session:
                rows = session.run(
                    "MATCH (a:Person)-[:MARRIED_TO]-(b:Person) "
                    "WHERE a.name < b.name "
                    "RETURN a.name AS a, b.name AS b ORDER BY a"
                )
                return [f"{r['a']}:{r['b']}" for r in rows]
        if list_type == "list_sibling":
            return self._run(
                "MATCH (p:Person)<-[:PARENT_OF]-(:Person)-[:PARENT_OF]->(sib:Person) "
                "WHERE sib <> p RETURN DISTINCT sib.name AS name"
            )
        base = list_type.replace("list_", "")
        results: set[str] = set()
        for member in list_family_members():
            results.update(self.query_relation(base, member))
        return sorted(results)

    def _query_cypher(self, relation: str, person: str, inverse: bool) -> list[str]:
        p = person

        if relation == "age":
            with self._driver.session() as session:
                rec = session.run(
                    "MATCH (p:Person {name: $person}) WHERE p.age IS NOT NULL "
                    "RETURN toString(p.age) AS val",
                    person=p,
                ).single()
                return [rec["val"]] if rec else []

        if relation == "dob":
            with self._driver.session() as session:
                rec = session.run(
                    "MATCH (p:Person {name: $person}) WHERE p.dob IS NOT NULL "
                    "RETURN p.dob AS val",
                    person=p,
                ).single()
                return [rec["val"]] if rec else []

        if relation == "male":
            return [p] if self.check_gender(p, "male") else []
        if relation == "female":
            return [p] if self.check_gender(p, "female") else []

        queries: dict[str, str | Callable[[str], list[str]]] = {
            "parent": (
                "MATCH (parent:Person)-[:PARENT_OF]->(child:Person {name: $person}) "
                "RETURN DISTINCT parent.name AS name"
                if not inverse
                else
                "MATCH (parent:Person {name: $person})-[:PARENT_OF]->(child:Person) "
                "RETURN DISTINCT child.name AS name"
            ),
            "children": (
                "MATCH (parent:Person {name: $person})-[:PARENT_OF]->(child:Person) "
                "RETURN DISTINCT child.name AS name"
            ),
            "sibling": (
                "MATCH (p:Person {name: $person})<-[:PARENT_OF]-(par:Person)"
                "-[:PARENT_OF]->(sib:Person) WHERE sib.name <> $person "
                "RETURN DISTINCT sib.name AS name"
            ),
            "brother": (
                "MATCH (p:Person {name: $person})<-[:PARENT_OF]-(par:Person)"
                "-[:PARENT_OF]->(sib:Person {gender: 'male'}) WHERE sib.name <> $person "
                "RETURN DISTINCT sib.name AS name"
            ),
            "sister": (
                "MATCH (p:Person {name: $person})<-[:PARENT_OF]-(par:Person)"
                "-[:PARENT_OF]->(sib:Person {gender: 'female'}) WHERE sib.name <> $person "
                "RETURN DISTINCT sib.name AS name"
            ),
            "spouse": (
                "MATCH (p:Person {name: $person})-[:MARRIED_TO]-(sp:Person) "
                "RETURN DISTINCT sp.name AS name"
            ),
            "father": (
                "MATCH (child:Person {name: $person})<-[:PARENT_OF]-(f:Person {gender: 'male'}) "
                "RETURN DISTINCT f.name AS name"
            ),
            "mother": (
                "MATCH (child:Person {name: $person})<-[:PARENT_OF]-(m:Person {gender: 'female'}) "
                "RETURN DISTINCT m.name AS name"
            ),
            "son": (
                "MATCH (p:Person {name: $person})-[:PARENT_OF]->(c:Person {gender: 'male'}) "
                "RETURN DISTINCT c.name AS name"
            ),
            "daughter": (
                "MATCH (p:Person {name: $person})-[:PARENT_OF]->(c:Person {gender: 'female'}) "
                "RETURN DISTINCT c.name AS name"
            ),
            "husband": (
                "MATCH (p:Person {name: $person})-[:MARRIED_TO]-(h:Person {gender: 'male'}) "
                "RETURN DISTINCT h.name AS name"
            ),
            "wife": (
                "MATCH (p:Person {name: $person})-[:MARRIED_TO]-(w:Person {gender: 'female'}) "
                "RETURN DISTINCT w.name AS name"
            ),
            "grandfather": (
                "MATCH (p:Person {name: $person})<-[:PARENT_OF]-(mid:Person)"
                "<-[:PARENT_OF]-(gf:Person {gender: 'male'}) "
                "RETURN DISTINCT gf.name AS name"
            ),
            "grandmother": (
                "MATCH (p:Person {name: $person})<-[:PARENT_OF]-(mid:Person)"
                "<-[:PARENT_OF]-(gm:Person {gender: 'female'}) "
                "RETURN DISTINCT gm.name AS name"
            ),
            "grandparent": (
                "MATCH (p:Person {name: $person})<-[:PARENT_OF*2]-(gp:Person) "
                "RETURN DISTINCT gp.name AS name"
            ),
            "grandchild": (
                "MATCH (p:Person {name: $person})-[:PARENT_OF*2]->(gc:Person) "
                "RETURN DISTINCT gc.name AS name"
            ),
            "paternal_grandfather": (
                "MATCH (p:Person {name: $person})<-[:PARENT_OF]-(fa:Person {gender: 'male'})"
                "<-[:PARENT_OF]-(pgf:Person {gender: 'male'}) "
                "RETURN DISTINCT pgf.name AS name"
            ),
            "uncle": (
                "MATCH (p:Person {name: $person})<-[:PARENT_OF]-(par:Person) "
                "MATCH (par)<-[:PARENT_OF]-(gp:Person)-[:PARENT_OF]->(u:Person {gender: 'male'}) "
                "WHERE u <> par "
                "RETURN DISTINCT u.name AS name"
            ),
            "aunt": (
                "MATCH (p:Person {name: $person})<-[:PARENT_OF]-(par:Person) "
                "MATCH (par)<-[:PARENT_OF]-(gp:Person)-[:PARENT_OF]->(a:Person {gender: 'female'}) "
                "WHERE a <> par "
                "RETURN DISTINCT a.name AS name"
            ),
            "cousin": (
                "MATCH (p:Person {name: $person})<-[:PARENT_OF]-(myPar:Person)"
                "<-[:PARENT_OF]-(gp:Person)-[:PARENT_OF]->(parSib:Person) "
                "WHERE parSib <> myPar "
                "MATCH (parSib)-[:PARENT_OF]->(cousin:Person) "
                "WHERE cousin.name <> $person "
                "AND NOT (cousin)-[:PARENT_OF]->(p) "
                "RETURN DISTINCT cousin.name AS name"
            ),
            "nephew": (
                "MATCH (p:Person {name: $person})<-[:PARENT_OF]-(gp:Person)"
                "-[:PARENT_OF]->(sib:Person) WHERE sib <> p "
                "MATCH (sib)-[:PARENT_OF]->(n:Person {gender: 'male'}) "
                "WHERE NOT (p)-[:MARRIED_TO]-(n) "
                "RETURN DISTINCT n.name AS name"
            ),
            "niece": (
                "MATCH (p:Person {name: $person})<-[:PARENT_OF]-(gp:Person)"
                "-[:PARENT_OF]->(sib:Person) WHERE sib <> p "
                "MATCH (sib)-[:PARENT_OF]->(n:Person {gender: 'female'}) "
                "WHERE NOT (p)-[:MARRIED_TO]-(n) "
                "RETURN DISTINCT n.name AS name"
            ),
            "father_in_law": (
                "MATCH (p:Person {name: $person})-[:MARRIED_TO]-(sp:Person)"
                "<-[:PARENT_OF]-(fil:Person {gender: 'male'}) "
                "RETURN DISTINCT fil.name AS name"
            ),
            "mother_in_law": (
                "MATCH (p:Person {name: $person})-[:MARRIED_TO]-(sp:Person)"
                "<-[:PARENT_OF]-(mil:Person {gender: 'female'}) "
                "RETURN DISTINCT mil.name AS name"
            ),
            "brother_in_law": (
                "MATCH (p:Person {name: $person})-[:MARRIED_TO]-(sp:Person)"
                "<-[:PARENT_OF]-(gp:Person)-[:PARENT_OF]->(bil:Person {gender: 'male'}) "
                "WHERE bil <> sp "
                "RETURN DISTINCT bil.name AS name"
            ),
            "sister_in_law": (
                "MATCH (p:Person {name: $person})-[:MARRIED_TO]-(sp:Person)"
                "<-[:PARENT_OF]-(gp:Person)-[:PARENT_OF]->(sil:Person {gender: 'female'}) "
                "WHERE sil <> sp "
                "RETURN DISTINCT sil.name AS name"
            ),
            "elder_sibling": (
                "MATCH (p:Person {name: $person})<-[:PARENT_OF]-(par:Person)"
                "-[:PARENT_OF]->(sib:Person) "
                "WHERE sib.name <> $person AND p.age IS NOT NULL AND sib.age IS NOT NULL "
                "AND sib.age > p.age "
                "RETURN DISTINCT sib.name AS name"
            ),
            "younger_sibling": (
                "MATCH (p:Person {name: $person})<-[:PARENT_OF]-(par:Person)"
                "-[:PARENT_OF]->(sib:Person) "
                "WHERE sib.name <> $person AND p.age IS NOT NULL AND sib.age IS NOT NULL "
                "AND sib.age < p.age "
                "RETURN DISTINCT sib.name AS name"
            ),
            "ancestor": (
                "MATCH (anc:Person)-[:PARENT_OF*1..]->(p:Person {name: $person}) "
                "RETURN DISTINCT anc.name AS name"
            ),
            "descendant": (
                "MATCH (p:Person {name: $person})-[:PARENT_OF*1..]->(desc:Person) "
                "RETURN DISTINCT desc.name AS name"
            ),
            "same_generation": self._same_generation,
        }

        handler = queries.get(relation)
        if handler is None:
            return []
        if callable(handler):
            return handler(p)
        return self._run(handler, person=p)

    def _same_generation(self, person: str) -> list[str]:
        all_people = list_family_members()

        def get_parents(p: str) -> set[str]:
            return set(self.query_relation("parent", p))

        def get_siblings(p: str) -> set[str]:
            return set(self.query_relation("sibling", p))

        def get_spouses(p: str) -> set[str]:
            return set(self.query_relation("spouse", p))

        def same_gen(a: str, b: str, seen: set[tuple[str, str]]) -> bool:
            if a == b:
                return False
            key = (a, b)
            if key in seen:
                return False
            seen.add(key)
            if b in get_siblings(a) or b in get_spouses(a):
                return True
            return any(
                same_gen(pa, pb, seen)
                for pa in get_parents(a)
                for pb in get_parents(b)
            )

        return sorted(other for other in all_people if same_gen(person, other, set()))

    def discover_relationship(self, p1: str, p2: str) -> str | None:
        p1, p2 = p1.strip().lower(), p2.strip().lower()
        rels_to_test = [
            "father", "mother", "parent", "son", "daughter", "children", "brother", "sister", "sibling",
            "husband", "wife", "spouse", "grandfather", "grandmother",
            "grandparent", "grandchild", "uncle", "aunt", "cousin", "nephew", "niece",
            "ancestor", "descendant", "elder_sibling", "younger_sibling",
            "paternal_grandfather", "same_generation",
            "father_in_law", "mother_in_law", "brother_in_law", "sister_in_law",
        ]
        for r in rels_to_test:
            if p2 in [a.lower() for a in self.query_relation(r, p1)]:
                return r
        for r in rels_to_test:
            if p1 in [a.lower() for a in self.query_relation(r, p2)]:
                return r
        return self._reason_over_path(p1, p2)

    def _reason_over_path(self, p1: str, p2: str) -> str | None:
        path = self._bfs_shortest_path(p1, p2)
        if not path:
            return None
        return self._describe_path(path)

    def _bfs_shortest_path(self, start: str, goal: str) -> list[tuple[str, str, str]] | None:
        if start == goal:
            return []

        queue: deque[tuple[str, list[tuple[str, str, str]]]] = deque([(start, [])])
        visited: set[str] = {start}

        with self._driver.session() as session:
            while queue:
                node, path = queue.popleft()

                # Walk child: node is parent_of child (forward step)
                for rec in session.run(
                    "MATCH (n:Person {name: $name})-[:PARENT_OF]->(c:Person) "
                    "RETURN c.name AS name",
                    name=node,
                ):
                    child = rec["name"]
                    step = (node, "parent_of", child)  # node is parent of child
                    if child == goal:
                        return path + [step]
                    if child not in visited:
                        visited.add(child)
                        queue.append((child, path + [step]))

                # Walk parent: parent is parent_of node (backward step)
                for rec in session.run(
                    "MATCH (n:Person {name: $name})<-[:PARENT_OF]-(par:Person) "
                    "RETURN par.name AS name",
                    name=node,
                ):
                    parent = rec["name"]
                    step = (parent, "child_of", node)  # parent is child_of node? No, let's name it clearly: step has (parent, "parent_of", node)
                    # To be completely clear, let's store direction explicitly: (from_node, edge_type, to_node)
                    # Let's use: (node, "child_of", parent) to mean walking from node to its parent.
                    step = (node, "child_of", parent)
                    if parent == goal:
                        return path + [step]
                    if parent not in visited:
                        visited.add(parent)
                        queue.append((parent, path + [step]))

                # Walk spouse: node married_to spouse (bi-directional step)
                for rec in session.run(
                    "MATCH (n:Person {name: $name})-[:MARRIED_TO]-(sp:Person) "
                    "RETURN sp.name AS name",
                    name=node,
                ):
                    spouse = rec["name"]
                    step = (node, "married_to", spouse)
                    if spouse == goal:
                        return path + [step]
                    if spouse not in visited:
                        visited.add(spouse)
                        queue.append((spouse, path + [step]))

        return None

    def _describe_path(self, path: list[tuple[str, str, str]]) -> str:
        if not path:
            return "same person"

        hops = len(path)
        if hops == 1:
            _, rel, _ = path[0]
            if rel == "parent_of":
                return "child"  # walking down from start to goal (start is parent of goal, so goal is child)
            if rel == "child_of":
                return "parent" # walking up from start to goal (start is child of goal, so goal is parent)
            if rel == "married_to":
                return "spouse"

        if hops == 2:
            rel1 = path[0][1]
            rel2 = path[1][1]
            # 1. start -> parent_of -> mid -> parent_of -> goal (start -> child -> grandchild)
            if rel1 == "parent_of" and rel2 == "parent_of":
                return "grandchild"
            # 2. start -> child_of -> mid -> child_of -> goal (start -> parent -> grandparent)
            if rel1 == "child_of" and rel2 == "child_of":
                return "grandparent"
            # 3. start -> child_of -> mid -> parent_of -> goal (start -> parent -> sibling)
            if rel1 == "child_of" and rel2 == "parent_of":
                return "sibling"
            # 4. start -> married_to -> spouse -> ...
            if "married_to" in (rel1, rel2):
                return "in_law"

        return f"connected_by_{hops}_hops"

    # ── Inference & Knowledge-Discovery Module ─────────────────────────────

    def mutual_connections(self, p1: str, p2: str) -> str:
        """
        Feature 1 — Mutual Connections.
        Find the nearest common ancestor of p1 and p2.  If none exists,
        fall back to describing the shortest BFS path between them.
        """
        p1, p2 = p1.strip().lower(), p2.strip().lower()

        # Common ancestors via Cypher (all ancestors of both people)
        with self._driver.session() as session:
            rows = session.run(
                "MATCH (a:Person)-[:PARENT_OF*1..]->(p1:Person {name: $p1}) "
                "MATCH (a)-[:PARENT_OF*1..]->(p2:Person {name: $p2}) "
                "WHERE p1 <> p2 "
                "OPTIONAL MATCH (a)-[:PARENT_OF*1..]->(d:Person) "
                "RETURN DISTINCT a.name AS name, count(DISTINCT d) AS desc_count "
                "ORDER BY desc_count ASC",  # The nearest common ancestor is closest to them, so they have the FEWEST total descendants in the graph (deepest in tree)
                p1=p1, p2=p2,
            )
            ancestors = [r["name"] for r in rows]

        p1t, p2t = p1.capitalize(), p2.capitalize()

        if ancestors:
            nearest = ancestors[-1]
            all_anc = ", ".join(a.capitalize() for a in ancestors)
            return (
                f"**Mutual Connection: {p1t} and {p2t}**\n\n"
                f"Nearest shared ancestor: {nearest.capitalize()}\n"
                f"All shared ancestors: {all_anc}."
            )

        path = self._bfs_shortest_path(p1, p2)
        if not path:
            return f"No mutual connection found between {p1t} and {p2t}."

        n = len(path)
        return (
            f"**Connection Path: {p1t} and {p2t}**\n\n"
            f"Length: {n} step{'s' if n != 1 else ''}\n\n"
            f"{_path_to_numbered_list(path)}\n\n"
            f"{p1t} and {p2t} are linked through the family graph."
        )

    def hidden_relationship(self, p1: str, p2: str) -> str:
        """
        Feature 2 — Hidden / Indirect Relationships.
        Walk the BFS path between p1 and p2 and produce a natural-language
        description even when no single named relation (uncle, cousin, …) exists.
        """
        p1, p2 = p1.strip().lower(), p2.strip().lower()
        p1t, p2t = p1.capitalize(), p2.capitalize()

        # First try the named-relation catalogue
        rels_to_test = [
            "father", "mother", "parent", "son", "daughter", "children", "brother", "sister", "sibling",
            "husband", "wife", "grandfather", "grandmother", "grandchild",
            "uncle", "aunt", "cousin", "nephew", "niece",
            "father_in_law", "mother_in_law", "brother_in_law", "sister_in_law",
            "ancestor", "descendant",
        ]
        for r in rels_to_test:
            if p2 in [x.lower() for x in self._query_cypher(r, p1, False)]:
                return (
                    f"{p2t} is the {r.replace('_', ' ')} of {p1t} "
                    f"(direct named relationship)."
                )
        for r in rels_to_test:
            if p1 in [x.lower() for x in self._query_cypher(r, p2, False)]:
                return (
                    f"{p1t} is the {r.replace('_', ' ')} of {p2t} "
                    f"(direct named relationship)."
                )

        # BFS path walk
        path = self._bfs_shortest_path(p1, p2)
        if not path:
            return f"No known relationship path found between {p1t} and {p2t}."

        n = len(path)
        return (
            f"**Indirect Relationship: {p1t} and {p2t}**\n\n"
            f"Connection length: {n} step{'s' if n != 1 else ''}\n\n"
            f"{_path_to_numbered_list(path)}\n\n"
            f"Summary: {_path_to_prose(path)}\n\n"
            f"{p1t} and {p2t} are connected through the family graph but do not "
            f"share a single named relationship label."
        )

    def age_similarity(self, person: str, max_gap: int = 5) -> str:
        """
        Feature 3 — Recommendation / Similarity.
        Find all family members within `max_gap` years of `person`'s age,
        sorted by closeness.  Also flags same-generation cousins within the gap.
        """
        person = person.strip().lower()
        pt = person.capitalize()

        with self._driver.session() as session:
            rec = session.run(
                "MATCH (p:Person {name: $person}) WHERE p.age IS NOT NULL "
                "RETURN p.age AS age",
                person=person,
            ).single()

        if not rec:
            return f"I don't have age information for {pt}."

        target_age = rec["age"]

        with self._driver.session() as session:
            rows = session.run(
                "MATCH (other:Person) "
                "WHERE other.name <> $person AND other.age IS NOT NULL "
                "  AND abs(other.age - $age) <= $gap "
                "RETURN other.name AS name, other.age AS age, "
                "       abs(other.age - $age) AS diff "
                "ORDER BY diff, name",
                person=person, age=target_age, gap=max_gap,
            )
            close = [(r["name"], r["age"], r["diff"]) for r in rows]

        if not close:
            return (
                f"{pt} (age {target_age}) has no family members within "
                f"{max_gap} years of their age."
            )

        # Mark cousins specially as "playdate/companion" candidates
        cousins = set(self._query_cypher("cousin", person, False))
        same_gen = set(self._query_cypher("same_generation", person, False))

        lines = []
        for name, age, diff in close:
            tags = []
            if name in cousins:
                tags.append("cousin, companion candidate")
            elif name in same_gen:
                tags.append("same generation")
            gap_str = f"{diff} year{'s' if diff != 1 else ''} apart"
            tag_str = f" ({', '.join(tags)})" if tags else ""
            lines.append(f"- {name.capitalize()}, age {age}, {gap_str}{tag_str}")

        return (
            f"**Age Similarity: {pt}** (age {target_age})\n\n"
            f"Family members within {max_gap} years:\n"
            + "\n".join(lines)
        )

    # ── Graph visualization data ───────────────────────────────────────────

    def _fetch_all_nodes(self) -> list[dict]:
        with self._driver.session() as session:
            return [
                {"name": r["name"], "gender": r["gender"], "age": r["age"]}
                for r in session.run(
                    "MATCH (p:Person) RETURN p.name AS name, p.gender AS gender, p.age AS age "
                    "ORDER BY name"
                )
            ]

    def _fetch_all_edges(self, include_inferred: bool = True) -> list[dict]:
        edges: list[dict] = []
        with self._driver.session() as session:
            for r in session.run(
                "MATCH (a:Person)-[:PARENT_OF]->(b:Person) "
                "RETURN a.name AS src, b.name AS dst"
            ):
                edges.append({"src": r["src"], "dst": r["dst"], "type": "PARENT_OF"})

            for r in session.run(
                "MATCH (a:Person)-[:MARRIED_TO]-(b:Person) "
                "WHERE a.name < b.name "
                "RETURN a.name AS src, b.name AS dst"
            ):
                edges.append({"src": r["src"], "dst": r["dst"], "type": "MARRIED_TO"})
                edges.append({"src": r["dst"], "dst": r["src"], "type": "MARRIED_TO"})

            if include_inferred:
                for r in session.run(
                    "MATCH (a:Person)-[rel]->(b:Person) WHERE type(rel) = 'INFERRED' "
                    "RETURN a.name AS src, b.name AS dst, rel.relation AS relation"
                ):
                    edges.append({
                        "src": r["src"],
                        "dst": r["dst"],
                        "type": r["relation"],
                        "category": "INFERRED",
                        "relation": r["relation"],
                    })
        return edges

    def _neighborhood(self, center: str, depth: int = 2) -> set[str]:
        center = center.strip().lower()
        seen = {center}
        frontier = {center}
        with self._driver.session() as session:
            for _ in range(depth):
                nxt: set[str] = set()
                for name in frontier:
                    rows = session.run(
                        "MATCH (p:Person {name: $name})-[:PARENT_OF|MARRIED_TO]-(n:Person) "
                        "RETURN DISTINCT n.name AS name",
                        name=name,
                    )
                    for row in rows:
                        if row["name"] not in seen:
                            nxt.add(row["name"])
                seen |= nxt
                frontier = nxt
        return seen

    def fetch_full_graph(self, include_inferred: bool = False) -> tuple[list[dict], list[dict]]:
        return self._fetch_all_nodes(), self._fetch_all_edges(include_inferred=include_inferred)

    def fetch_subgraph(
        self, center: str, depth: int = 2, include_inferred: bool = False
    ) -> tuple[list[dict], list[dict]]:
        names = self._neighborhood(center, depth)
        nodes = [n for n in self._fetch_all_nodes() if n["name"] in names]
        edges = [
            e for e in self._fetch_all_edges(include_inferred=include_inferred)
            if e["src"] in names and e["dst"] in names
        ]
        return nodes, edges

    def fetch_highlight_path(
        self, p1: str, p2: str, include_inferred: bool = False
    ) -> tuple[list[dict], list[dict], set[str], set[tuple[str, str, str]]]:
        """Structural graph plus highlighted shortest-path nodes and edges."""
        nodes, edges = self.fetch_full_graph(include_inferred=include_inferred)
        path = self._bfs_shortest_path(p1.strip().lower(), p2.strip().lower())
        path_nodes: set[str] = set()
        path_edges: set[tuple[str, str, str]] = set()
        for src, rel, dst in path:
            path_nodes.update([src, dst])
            if rel == "parent_of":
                path_edges.add((src, dst, "PARENT_OF"))
            elif rel == "child_of":
                path_edges.add((dst, src, "PARENT_OF"))
            else:
                path_edges.add((src, dst, "MARRIED_TO"))
                path_edges.add((dst, src, "MARRIED_TO"))
        return nodes, edges, path_nodes, path_edges

    def graph_report(self) -> str:
        """
        Feature 4 — Graph Analysis Report.
        Returns a structured report on: node counts, relationship type counts,
        most-connected person (highest total degree), and longest ancestor chain.
        """
        with self._driver.session() as session:
            # Node count
            n_people = session.run(
                "MATCH (p:Person) RETURN count(p) AS n"
            ).single()["n"]

            # Relationship type counts
            parent_count = session.run(
                "OPTIONAL MATCH ()-[r:PARENT_OF]->() RETURN count(r) AS n"
            ).single()["n"] or 0
            marriage_count = session.run(
                "OPTIONAL MATCH ()-[r:MARRIED_TO]-() RETURN toInteger(count(r)/2) AS n"
            ).single()["n"] or 0
            inferred_count = session.run(
                "MATCH ()-[r]->() WHERE type(r) = 'INFERRED' RETURN count(r) AS n"
            ).single()["n"] or 0

            # Most-connected person (degree = PARENT_OF in+out + MARRIED_TO)
            mc = session.run(
                "MATCH (p:Person) "
                "OPTIONAL MATCH (p)-[r1:PARENT_OF]-() "
                "OPTIONAL MATCH (p)-[r2:MARRIED_TO]-() "
                "WITH p, count(DISTINCT r1) + count(DISTINCT r2) AS deg "
                "ORDER BY deg DESC LIMIT 1 "
                "RETURN p.name AS name, deg"
            ).single()

        most_connected_name = mc["name"].capitalize() if mc else "Unknown"
        most_connected_deg  = mc["deg"] if mc else 0

        # Longest ancestor chain — walk all people and find deepest ancestor depth
        all_people = list_family_members()
        max_depth = 0
        deepest_person = ""
        for person in all_people:
            ancestors = self._query_cypher("ancestor", person, False)
            if len(ancestors) > max_depth:
                max_depth = len(ancestors)
                deepest_person = person

        total_rels = parent_count + marriage_count + inferred_count
        deepest = deepest_person.capitalize() if deepest_person else "N/A"

        return (
            "**Family Graph Analysis Report**\n\n"
            "| Metric | Value |\n"
            "| --- | --- |\n"
            f"| Node label | Person |\n"
            f"| Total members | {n_people} |\n"
            f"| Parent-child links | {parent_count} |\n"
            f"| Marriages | {marriage_count} |\n"
            f"| Inferred (Prolog) links | {inferred_count} |\n"
            f"| Total relationships | {total_rels} |\n"
            f"| Most connected member | {most_connected_name} ({most_connected_deg} links) |\n"
            f"| Deepest lineage | {deepest} ({max_depth} ancestor"
            f"{'s' if max_depth != 1 else ''}) |"
        )

_engine: FamilyGraphEngine | None = None


def get_engine() -> FamilyGraphEngine:
    global _engine
    if _engine is None:
        _engine = FamilyGraphEngine()
    return _engine


def reset_engine() -> FamilyGraphEngine:
    global _engine
    _engine = FamilyGraphEngine()
    return _engine


def create_engine() -> tuple[FamilyGraphEngine, str]:
    return get_engine(), "Neo4j"


def list_family_members() -> list[str]:
    with get_driver().session() as session:
        rows = session.run("MATCH (p:Person) RETURN p.name AS name ORDER BY name")
        return [r["name"] for r in rows]


def merge_person(session: Session, name: str, gender: str | None = None) -> None:
    session.run(
        "MERGE (p:Person {name: $name}) "
        "ON CREATE SET p.gender = $gender "
        "ON MATCH SET p.gender = COALESCE($gender, p.gender)",
        name=name,
        gender=gender,
    )


def set_gender(session: Session, name: str, gender: str) -> None:
    merge_person(session, name, gender)
    session.run(
        "MATCH (p:Person {name: $name}) SET p.gender = $gender",
        name=name,
        gender=gender,
    )


def add_parent(session: Session, parent: str, child: str) -> None:
    merge_person(session, parent)
    merge_person(session, child)
    session.run(
        "MATCH (par:Person {name: $parent}), (ch:Person {name: $child}) "
        "MERGE (par)-[:PARENT_OF]->(ch)",
        parent=parent,
        child=child,
    )


def add_marriage(session: Session, a: str, b: str) -> None:
    merge_person(session, a)
    merge_person(session, b)
    session.run(
        "MATCH (a:Person {name: $a}), (b:Person {name: $b}) "
        "MERGE (a)-[:MARRIED_TO]-(b)",
        a=a,
        b=b,
    )


def set_age(session: Session, name: str, age: int) -> None:
    merge_person(session, name)
    session.run(
        "MATCH (p:Person {name: $name}) SET p.age = $age",
        name=name,
        age=age,
    )


def set_dob(session: Session, name: str, dob: str) -> None:
    merge_person(session, name)
    session.run(
        "MATCH (p:Person {name: $name}) SET p.dob = $dob",
        name=name,
        dob=dob,
    )


def delete_person(session: Session, name: str) -> None:
    session.run("MATCH (p:Person {name: $name}) DETACH DELETE p", name=name)


def remove_parent(session: Session, parent: str, child: str) -> None:
    session.run(
        "MATCH (par:Person {name: $parent})-[r:PARENT_OF]->(ch:Person {name: $child}) "
        "DELETE r",
        parent=parent,
        child=child,
    )


def remove_marriage(session: Session, a: str, b: str) -> None:
    session.run(
        "MATCH (a:Person {name: $a})-[r:MARRIED_TO]-(b:Person {name: $b}) DELETE r",
        a=a,
        b=b,
    )


def remove_age(session: Session, name: str) -> None:
    session.run("MATCH (p:Person {name: $name}) REMOVE p.age", name=name)


def remove_dob(session: Session, name: str) -> None:
    session.run("MATCH (p:Person {name: $name}) REMOVE p.dob", name=name)


def clear_gender(session: Session, name: str, gender: str) -> None:
    session.run(
        "MATCH (p:Person {name: $name, gender: $gender}) REMOVE p.gender",
        name=name,
        gender=gender,
    )


# ── Data-entry helpers (was data_entry.py) ─────────────────────────────────

def normalize_name(name: str) -> str:
    """Convert a natural-language name to a valid graph key."""
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9_\s-]", "", name)
    return re.sub(r"[\s-]+", "_", name)


def _confirmation(
    fact_type: str,
    person1: str,
    person2: str,
    value: str,
) -> str:
    p1 = normalize_name(person1)
    p2 = normalize_name(person2) if person2 else ""
    if fact_type == "male":
        return f"Added {p1.title()} as a male family member."
    if fact_type == "female":
        return f"Added {p1.title()} as a female family member."
    if fact_type in ("parent", "parent_male", "parent_female"):
        extra = ""
        if fact_type == "parent_male":
            extra = f" ({p1.title()} recorded as male)"
        elif fact_type == "parent_female":
            extra = f" ({p1.title()} recorded as female)"
        return f"Added parent relationship: {p1.title()} is parent of {p2.title()}.{extra}"
    if fact_type == "age":
        return f"Set age of {p1.title()} to {value.strip()} years."
    if fact_type == "dob":
        return f"Set date of birth of {p1.title()} to {value.strip()}."
    if fact_type == "married":
        return f"Added marriage: {p1.title()} and {p2.title()} are married."
    if fact_type == "husband":
        return f"Added marriage: {p1.title()} is husband of {p2.title()}."
    if fact_type == "wife":
        return f"Added marriage: {p1.title()} is wife of {p2.title()}."
    if fact_type.startswith("delete_"):
        label = fact_type.replace("delete_", "").replace("_", " ")
        if person2:
            return f"Deleted {label} fact for {p1.title()} and {p2.title()}."
        return f"Deleted {label} fact for {p1.title()}."
    return f"Added fact for {p1.title()}."


def _apply_fact(fact_type: str, person1: str, person2: str, value: str) -> None:
    p1 = normalize_name(person1)
    p2 = normalize_name(person2) if person2 else ""
    driver = get_driver()

    with driver.session() as session:
        if fact_type == "male":
            set_gender(session, p1, "male")
        elif fact_type == "female":
            set_gender(session, p1, "female")
        elif fact_type == "parent":
            add_parent(session, p1, p2)
        elif fact_type == "parent_male":
            set_gender(session, p1, "male")
            add_parent(session, p1, p2)
        elif fact_type == "parent_female":
            set_gender(session, p1, "female")
            add_parent(session, p1, p2)
        elif fact_type == "age":
            age = int(re.sub(r"\D", "", value))
            set_age(session, p1, age)
        elif fact_type == "dob":
            set_dob(session, p1, value.strip())
        elif fact_type in ("married", "husband", "wife"):
            add_marriage(session, p1, p2)
            if fact_type == "husband":
                set_gender(session, p1, "male")
                set_gender(session, p2, "female")
            elif fact_type == "wife":
                set_gender(session, p1, "female")
                set_gender(session, p2, "male")
        elif fact_type == "delete_person":
            delete_person(session, p1)
        elif fact_type == "delete_male":
            clear_gender(session, p1, "male")
        elif fact_type == "delete_female":
            clear_gender(session, p1, "female")
        elif fact_type == "delete_parent":
            remove_parent(session, p1, p2)
        elif fact_type == "delete_married":
            remove_marriage(session, p1, p2)
        elif fact_type == "delete_age":
            remove_age(session, p1)
        elif fact_type == "delete_dob":
            remove_dob(session, p1)


def process_data_entry(kernel) -> str | None:
    """
    Read data-entry predicates set by AIML and write facts to Neo4j.
    Returns a confirmation message, or None if no data-entry intent was detected.
    """
    fact_type = (kernel.getPredicate("fact_type") or "").strip().lower()
    if not fact_type:
        return None

    person1 = (kernel.getPredicate("person1") or "").strip()
    person2 = (kernel.getPredicate("person2") or "").strip()
    value = (kernel.getPredicate("value") or "").strip()

    if not person1:
        return "Please provide a person name for this fact."

    if fact_type in (
        "parent", "parent_male", "parent_female", "married", "husband", "wife",
        "delete_parent", "delete_married",
    ) and not person2:
        return "Please provide both people for this relationship."

    if fact_type == "age" and not value:
        return "Please provide an age value."

    if fact_type == "dob" and not value:
        return "Please provide a date of birth."

    try:
        _apply_fact(fact_type, person1, person2, value)
    except Exception as exc:
        return f"Could not save to Neo4j: {exc}"

    return _confirmation(fact_type, person1, person2, value)


def clear_data_entry_predicates(kernel) -> None:
    """Reset data-entry predicates before each AIML turn."""
    for pred in ("fact_type", "person1", "person2", "value"):
        kernel.setPredicate(pred, "")
