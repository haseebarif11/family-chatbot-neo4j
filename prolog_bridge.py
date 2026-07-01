"""
Hybrid Neo4j–Prolog bridge.

1. Export live Neo4j facts to a Prolog file.
2. Run derived-relationship inference (SWI-Prolog via PySwip, or Python fallback).
3. Import inferred pairs back into Neo4j as INFERRED relationships.
"""

from __future__ import annotations

import re
from pathlib import Path

from neo4j_bridge import get_driver, list_family_members

BASE_DIR = Path(__file__).resolve().parent
RULES_PATH = BASE_DIR / "family_kb.pl"
EXPORT_PATH = BASE_DIR / "neo4j_export.pl"

INFERRED_RELATIONS = [
    "father", "mother", "brother", "sister", "sibling",
    "grandfather", "grandmother", "grandparent", "grandchild",
    "uncle", "aunt", "cousin", "nephew", "niece",
    "ancestor", "descendant",
    "father_in_law", "mother_in_law", "brother_in_law", "sister_in_law",
    "elder_sibling", "younger_sibling", "paternal_grandfather",
    "same_generation",
]

_RULES_START = "% --- Derived rules"


def _load_rules_section() -> str:
    text = RULES_PATH.read_text(encoding="utf-8")
    if _RULES_START in text:
        return text.split(_RULES_START, 1)[1]
    return ""


def export_neo4j_to_prolog(output_path: Path | None = None) -> Path:
    """Export current Neo4j base facts to a Prolog file (facts + family_kb rules)."""
    output_path = output_path or EXPORT_PATH
    lines = ["% Auto-exported from Neo4j", ""]

    with get_driver().session() as session:
        for row in session.run(
            "MATCH (p:Person)-[:PARENT_OF]->(c:Person) "
            "RETURN p.name AS parent, c.name AS child ORDER BY parent, child"
        ):
            lines.append(f"parent({row['parent']}, {row['child']}).")

        lines.append("")
        for row in session.run(
            "MATCH (p:Person {gender: 'male'}) RETURN p.name AS name ORDER BY name"
        ):
            lines.append(f"male({row['name']}).")

        lines.append("")
        for row in session.run(
            "MATCH (p:Person {gender: 'female'}) RETURN p.name AS name ORDER BY name"
        ):
            lines.append(f"female({row['name']}).")

        lines.append("")
        for row in session.run(
            "MATCH (a:Person)-[:MARRIED_TO]-(b:Person) "
            "WHERE a.name < b.name "
            "RETURN a.name AS a, b.name AS b ORDER BY a"
        ):
            lines.append(f"married({row['a']}, {row['b']}).")

        lines.append("")
        for row in session.run(
            "MATCH (p:Person) WHERE p.age IS NOT NULL "
            "RETURN p.name AS name, p.age AS age ORDER BY name"
        ):
            lines.append(f"age({row['name']}, {row['age']}).")

        lines.append("")
        for row in session.run(
            "MATCH (p:Person) WHERE p.dob IS NOT NULL "
            "RETURN p.name AS name, p.dob AS dob ORDER BY name"
        ):
            lines.append(f"dob({row['name']}, '{row['dob']}').")

    rules = _load_rules_section()
    output_path.write_text("\n".join(lines) + "\n" + _RULES_START + rules, encoding="utf-8")
    return output_path


def _parse_export_facts(pl_path: Path) -> dict:
    facts: dict = {
        "parent": set(),
        "male": set(),
        "female": set(),
        "married": set(),
        "age": {},
        "dob": {},
    }
    for line in pl_path.read_text(encoding="utf-8").splitlines():
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


class _PythonPrologEngine:
    """Python mirror of family_kb.pl derived rules (fallback when SWI-Prolog absent)."""

    def __init__(self, facts: dict) -> None:
        self.f = facts

    def _parents(self, p: str) -> set[str]:
        return {a for a, c in self.f["parent"] if c == p}

    def _children(self, p: str) -> set[str]:
        return {c for a, c in self.f["parent"] if a == p}

    def _siblings(self, p: str) -> set[str]:
        s = set()
        for par in self._parents(p):
            s |= self._children(par)
        s.discard(p)
        return s

    def _spouses(self, p: str) -> set[str]:
        sp: set[str] = set()
        for h, w in self.f["married"]:
            if h == p:
                sp.add(w)
            if w == p:
                sp.add(h)
        return sp

    def query(self, relation: str, person: str) -> list[str]:
        person = person.lower()
        relation = relation.lower()
        f = self.f

        def fathers(p):
            return {x for x in self._parents(p) if x in f["male"]}

        def mothers(p):
            return {x for x in self._parents(p) if x in f["female"]}

        def brothers(p):
            return {x for x in self._siblings(p) if x in f["male"]}

        def sisters(p):
            return {x for x in self._siblings(p) if x in f["female"]}

        dispatch = {
            "father": fathers,
            "mother": mothers,
            "brother": brothers,
            "sister": sisters,
            "sibling": self._siblings,
            "son": lambda p: {c for c in self._children(p) if c in f["male"]},
            "daughter": lambda p: {c for c in self._children(p) if c in f["female"]},
            "grandfather": lambda p: {gf for pa in self._parents(p) for gf in fathers(pa)},
            "grandmother": lambda p: {gm for pa in self._parents(p) for gm in mothers(pa)},
            "grandparent": lambda p: {gp for pa in self._parents(p) for gp in self._parents(pa)},
            "grandchild": lambda p: {gc for c in self._children(p) for gc in self._children(c)},
            "uncle": lambda p: {u for pa in self._parents(p) for u in brothers(pa)},
            "aunt": lambda p: {a for pa in self._parents(p) for a in sisters(pa)},
            "cousin": lambda p: {
                c for pa in self._parents(p) for s in self._siblings(pa) for c in self._children(s)
            },
            "nephew": lambda p: {c for s in self._siblings(p) for c in self._children(s) if c in f["male"]},
            "niece": lambda p: {c for s in self._siblings(p) for c in self._children(s) if c in f["female"]},
            "ancestor": self._ancestors,
            "descendant": self._descendants,
            "father_in_law": lambda p: {fa for sp in self._spouses(p) for fa in fathers(sp)},
            "mother_in_law": lambda p: {mo for sp in self._spouses(p) for mo in mothers(sp)},
            "brother_in_law": lambda p: {br for sp in self._spouses(p) for br in brothers(sp)},
            "sister_in_law": lambda p: {si for sp in self._spouses(p) for si in sisters(sp)},
            "elder_sibling": lambda p: {
                s for s in self._siblings(p)
                if s in f["age"] and p in f["age"] and f["age"][s] > f["age"][p]
            },
            "younger_sibling": lambda p: {
                s for s in self._siblings(p)
                if s in f["age"] and p in f["age"] and f["age"][s] < f["age"][p]
            },
            "paternal_grandfather": lambda p: {pgf for fa in fathers(p) for pgf in fathers(fa)},
            "same_generation": self._same_generation,
        }
        fn = dispatch.get(relation)
        if not fn:
            return []
        return sorted(fn(person))

    def _ancestors(self, person: str) -> set[str]:
        found: set[str] = set()
        frontier = list(self._parents(person))
        while frontier:
            cur = frontier.pop()
            if cur not in found:
                found.add(cur)
                frontier.extend(self._parents(cur))
        return found

    def _descendants(self, person: str) -> set[str]:
        found: set[str] = set()
        frontier = list(self._children(person))
        while frontier:
            cur = frontier.pop()
            if cur not in found:
                found.add(cur)
                frontier.extend(self._children(cur))
        return found

    def _same_generation(self, person: str) -> set[str]:
        all_people: set[str] = set()
        for a, c in self.f["parent"]:
            all_people.update([a, c])
        all_people |= self.f["male"] | self.f["female"]
        all_people |= set(self.f["age"].keys())

        def same_gen(a: str, b: str, seen: set[tuple[str, str]]) -> bool:
            if a == b:
                return False
            key = (a, b)
            if key in seen:
                return False
            seen.add(key)
            if b in self._siblings(a) or b in self._spouses(a):
                return True
            return any(
                same_gen(pa, pb, seen)
                for pa in self._parents(a)
                for pb in self._parents(b)
            )

        return {other for other in all_people if same_gen(person, other, set())}


def _query_pyswip(pl_path: Path, relation: str, person: str) -> list[str] | None:
    try:
        from pyswip import Prolog  # type: ignore
    except Exception:
        # ImportError (no pyswip) or SwiPrologNotFoundError (SWI-Prolog not installed)
        return None

    try:
        prolog = Prolog()
        prolog.consult(str(pl_path))
        goal = f"{relation}(X, {person})"
        return sorted({str(r["X"]) for r in prolog.query(goal)})
    except Exception:
        return None


def query_prolog(relation: str, person: str, pl_path: Path | None = None) -> tuple[list[str], str]:
    pl_path = pl_path or EXPORT_PATH
    if not pl_path.exists():
        export_neo4j_to_prolog(pl_path)

    pyswip_answers = _query_pyswip(pl_path, relation, person)
    if pyswip_answers is not None:
        return pyswip_answers, "SWI-Prolog (PySwip)"

    facts = _parse_export_facts(pl_path)
    engine = _PythonPrologEngine(facts)
    return engine.query(relation, person), "Python rule engine (Prolog rules mirror)"


def clear_inferred_relationships() -> int:
    with get_driver().session() as session:
        result = session.run(
            "MATCH ()-[r]->() WHERE type(r) = 'INFERRED' DELETE r RETURN count(r) AS n"
        )
        rec = result.single()
        return rec["n"] if rec else 0


def import_inferred_to_neo4j(pl_path: Path | None = None) -> tuple[int, str]:
    pl_path = pl_path or export_neo4j_to_prolog()
    clear_inferred_relationships()

    people = list_family_members()
    if not people:
        return 0, "none"

    engine_label = "unknown"
    pairs: list[tuple[str, str, str]] = []

    for person in people:
        for relation in INFERRED_RELATIONS:
            answers, engine_label = query_prolog(relation, person, pl_path)
            for other in answers:
                if other != person:
                    pairs.append((other, person, relation))

    with get_driver().session() as session:
        for src, dst, rel in pairs:
            session.run(
                "MATCH (a:Person {name: $src}), (b:Person {name: $dst}) "
                "MERGE (a)-[r:INFERRED {relation: $rel}]->(b) "
                "SET r.source = 'prolog', r.engine = $engine",
                src=src,
                dst=dst,
                rel=rel,
                engine=engine_label,
            )

    return len(pairs), engine_label


def sync_prolog_bridge() -> str:
    export_path = export_neo4j_to_prolog()
    count, engine = import_inferred_to_neo4j(export_path)
    members = len(list_family_members())
    return (
        "**Neo4j–Prolog Bridge Sync Complete**\n\n"
        f"- Exported facts to `{export_path.name}`\n"
        f"- Inference engine: {engine}\n"
        f"- Family members processed: {members}\n"
        f"- Inferred relationships imported: {count}\n\n"
        "Inferred edges are stored in Neo4j as `INFERRED` relationships "
        "and appear in graph visualizations (orange dashed edges)."
    )


def prolog_query_report(relation: str, person: str) -> str:
    relation = relation.lower().strip()
    person = person.lower().strip()
    export_neo4j_to_prolog()
    answers, engine = query_prolog(relation, person)
    if not answers:
        return f"Prolog found no `{relation}` relationships for {person.capitalize()} (via {engine})."
    names = ", ".join(a.capitalize() for a in answers)
    return (
        f"**Prolog query:** `{relation}(X, {person})`\n\n"
        f"Engine: {engine}\n"
        f"Results: {names}"
    )
