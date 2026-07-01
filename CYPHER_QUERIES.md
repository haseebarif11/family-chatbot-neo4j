# Cypher Query Reference — Family Tree Chatbot

This document maps every graph query in `neo4j_bridge.py` to the Prolog rules in
`family_kb.pl` and explains design choices (especially the intermarried Ali/Zara branch).

## Graph schema

| Element | Model | Why |
|---------|--------|-----|
| `(:Person {name, gender?, age?, dob?})` | Node | People are entities; scalar attributes stay on the node |
| `(:Person)-[:PARENT_OF]->(:Person)` | Directed edge | Matches `parent(Parent, Child)` |
| `(:Person)-[:MARRIED_TO]-(:Person)` | Undirected edge | Symmetric; one edge per couple |

**Constraint** (`ensure_schema`):

```cypher
CREATE CONSTRAINT person_name IF NOT EXISTS
FOR (p:Person) REQUIRE p.name IS UNIQUE
```

---

## `_query_cypher` — relationship queries

Each derived Prolog rule is a graph traversal. Direction: query “X of **person**” means
find all X where the Prolog relation holds with Y = person.

### Parents / children / siblings

| Relation | Prolog | Cypher idea |
|----------|--------|-------------|
| `parent` | `parent(X,Y)` | `(parent)-[:PARENT_OF]->(child {name: $person})` |
| `children` | inverse parent | `(person)-[:PARENT_OF]->(child)` |
| `sibling` | shared parent | `person<-[:PARENT_OF]-(gp)-[:PARENT_OF]->(sib)` where `sib <> person` |
| `brother` / `sister` | sibling + gender | same + `{gender: 'male'/'female'}` |

### Gendered parent/child

| Relation | Prolog | Cypher |
|----------|--------|--------|
| `father` | `parent(X,Y), male(X)` | child<-[:PARENT_OF]-(f {gender:'male'}) |
| `mother` | `parent(X,Y), female(X)` | child<-[:PARENT_OF]-(m {gender:'female'}) |
| `son` / `daughter` | `parent(Y,X), male/female(X)` | person-[:PARENT_OF]->(c {gender:...}) |

### Marriage

| Relation | Prolog | Cypher |
|----------|--------|--------|
| `spouse` | `married(X,Y)` bidirectional | `(p)-[:MARRIED_TO]-(sp)` |
| `husband` / `wife` | spouse + gender | spouse pattern + gender filter |

### Grandparents (2-hop parent chain)

| Relation | Prolog | Cypher |
|----------|--------|--------|
| `grandfather` / `grandmother` | father/mother of parent | 2-hop up with gender on outer node |
| `grandparent` | `parent(X,Z), parent(Z,Y)` | `(p)<-[:PARENT_OF*2]-(gp)` |
| `grandchild` | inverse | `(p)-[:PARENT_OF*2]->(gc)` |
| `paternal_grandfather` | `father(Z,Y), father(X,Z)` | male parent, then male parent again |

### Uncle / Aunt — parent's sibling (NOT grandparent)

Prolog: `uncle(X,Y) :- brother(X,Z), parent(Z,Y)` — Z is **parent of Y**; X is Z's brother.

```cypher
MATCH (p:Person {name: $person})<-[:PARENT_OF]-(par:Person)
MATCH (par)<-[:PARENT_OF]-(gp:Person)-[:PARENT_OF]->(u:Person {gender: 'male'})
WHERE u <> par
RETURN DISTINCT u.name AS name
```

**Why the extra hop:** An older buggy pattern `(p)<-[:PARENT_OF]-(par)<-[:PARENT_OF]-(u)`
matched **grandfathers** (parent of parent). The correct pattern goes up to `par`, then
sideways to `par`'s siblings via shared `gp`.

Same structure for `aunt` with `{gender: 'female'}`.

**Laiba example:** parents Ali & Zara → uncles Haider & Sohail (Zara's brothers), not Kamran.

### Cousin

Prolog: `cousin(X,Y) :- parent(A,X), parent(B,Y), sibling(A,B)`.

```cypher
MATCH (p:Person {name: $person})<-[:PARENT_OF]-(myPar:Person)
      <-[:PARENT_OF]-(gp:Person)-[:PARENT_OF]->(parSib:Person)
WHERE parSib <> myPar
MATCH (parSib)-[:PARENT_OF]->(cousin:Person)
WHERE cousin.name <> $person
  AND NOT (cousin)-[:PARENT_OF]->(p)
RETURN DISTINCT cousin.name AS name
```

- `parSib <> myPar` — parent's sibling (not self).
- `NOT (cousin)-[:PARENT_OF]->(p)` — excludes parents from cousin results (important when
  Ali married his cousin Zara and is also Laiba's father).

### Nephew / Niece

Prolog: `nephew(X,Y) :- sibling(Y,Z), son(X,Z)`.

```cypher
MATCH (p:Person {name: $person})<-[:PARENT_OF]-(gp:Person)-[:PARENT_OF]->(sib:Person)
WHERE sib <> p
MATCH (sib)-[:PARENT_OF]->(n:Person {gender: 'male'})   -- or female for niece
WHERE NOT (p)-[:MARRIED_TO]-(n)
RETURN DISTINCT n.name AS name
```

`NOT (p)-[:MARRIED_TO]-(n)` avoids listing a spouse's child as nephew/niece when the
marriage link would otherwise create false positives in blended/intermarried trees.

### In-laws

| Relation | Prolog | Pattern |
|----------|--------|---------|
| `father_in_law` | `spouse(Y,Z), father(X,Z)` | married to spouse, then spouse's father |
| `mother_in_law` | spouse's mother | same with female |
| `brother_in_law` | spouse's brother | spouse<-[:PARENT_OF]-(gp)-[:PARENT_OF]->(bil) |
| `sister_in_law` | spouse's sister | same, female |

### Age-based siblings

`elder_sibling` / `younger_sibling`: sibling match + `sib.age >/< p.age`.

### Recursive: ancestor / descendant

Prolog recursion → variable-length paths:

```cypher
-- ancestor of person
MATCH (anc:Person)-[:PARENT_OF*1..]->(p:Person {name: $person})

-- descendant of person
MATCH (p:Person {name: $person})-[:PARENT_OF*1..]->(desc:Person)
```

`[:PARENT_OF*1..]` is the direct equivalent of the Prolog base case + recursive case.

### `same_generation`

Implemented in Python (mutually recursive Prolog rule); uses Neo4j-fetched
siblings, spouses, and parents — same logic as Assignment 2.

---

## Post-Cypher exclusion filter (`query_relation`)

For `cousin`, `nephew`, and `niece` only, results pass through Python filtering after
Cypher returns. This handles the **intermarried Ali/Zara branch**:

1. Exclude anyone who is already father/mother/uncle/aunt of the query person.
2. Exclude sister-in-law / brother-in-law of the query person (e.g. Sara ↔ Zara via Ali).
3. **Cousin only:** also exclude siblings, nephews, nieces of the query person.
4. Exclude a candidate if they are uncle/aunt of *another* candidate in the same result
   set (e.g. Sara is Laiba's aunt even when querying cousins of Zara's children).

Cypher encodes tree structure; Python encodes social-role disambiguation for cousin
marriages.

---

## BFS fallback (`_bfs_shortest_path`)

When no named relation matches, breadth-first search over:

- `(n)-[:PARENT_OF]->(child)` — walk down
- `(n)<-[:PARENT_OF]-(parent)` — walk up (`child_of` step)
- `(n)-[:MARRIED_TO]-(spouse)` — marriage hop

Used by `discover_relationship`, `mutual_connections` (fallback), and `hidden_relationship`.

---

## Inference module queries

### `mutual_connections(p1, p2)`

**Common ancestors:**

```cypher
MATCH (a:Person)-[:PARENT_OF*1..]->(p1:Person {name: $p1})
MATCH (a)-[:PARENT_OF*1..]->(p2:Person {name: $p2})
WHERE p1 <> p2
OPTIONAL MATCH (a)-[:PARENT_OF*1..]->(d:Person)
RETURN DISTINCT a.name AS name, count(DISTINCT d) AS desc_count
ORDER BY desc_count ASC
```

Returns shared ancestors; the deepest (nearest) is taken from the ordered list. If none,
falls back to BFS path description.

### `hidden_relationship(p1, p2)`

1. Try every named relation via `_query_cypher` (no post-filter).
2. If none match, BFS path → natural-language chain with `→(parent of)→`, `→(child of)→`,
   `→(married to)→` labels.

### `age_similarity(person, max_gap=5)`

```cypher
MATCH (p:Person {name: $person}) WHERE p.age IS NOT NULL RETURN p.age AS age

MATCH (other:Person)
WHERE other.name <> $person AND other.age IS NOT NULL
  AND abs(other.age - $age) <= $gap
RETURN other.name, other.age, abs(other.age - $age) AS diff
ORDER BY diff, name
```

Then tags cousins as “companion candidate” and same-generation relatives.

### `graph_report()`

```cypher
MATCH (p:Person) RETURN count(p) AS n

OPTIONAL MATCH ()-[r:PARENT_OF]->() RETURN count(r) AS n

OPTIONAL MATCH ()-[r:MARRIED_TO]-() RETURN toInteger(count(r)/2) AS n

MATCH (p:Person)
OPTIONAL MATCH (p)-[r1:PARENT_OF]-()
OPTIONAL MATCH (p)-[r2:MARRIED_TO]-()
WITH p, count(DISTINCT r1) + count(DISTINCT r2) AS deg
ORDER BY deg DESC LIMIT 1
RETURN p.name, deg
```

`OPTIONAL MATCH` on empty graphs avoids dropping summary rows.

---

## List queries (`query_list`)

| `list_type` | Cypher summary |
|-------------|----------------|
| `list_male` / `list_female` | `{gender: 'male'/'female'}` |
| `list_parent` / `list_child` | DISTINCT ends of `PARENT_OF` |
| `list_age` | `WHERE age IS NOT NULL ORDER BY age DESC` |
| `list_married` | couples with `a.name < b.name` dedup |
| `list_sibling` | people appearing as non-self sibling |
| other `list_*` | union of `query_relation` across all members |

---

## Data mutation (migration / chat entry)

| Function | Cypher |
|----------|--------|
| `merge_person` | `MERGE (p:Person {name})` + gender on create/match |
| `add_parent` | `MERGE (par)-[:PARENT_OF]->(ch)` |
| `add_marriage` | `MERGE (a)-[:MARRIED_TO]-(b)` |
| `set_age` / `set_dob` | `SET p.age` / `SET p.dob` |
| `delete_person` | `DETACH DELETE` |
