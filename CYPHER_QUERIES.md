# Neo4j Schema & Cypher Query Reference

## Graph Model Design

### Nodes: `(:Person {name, gender?, age?, dob?})`

- **Person** is the only node label. Every family member is a node keyed by lowercase `name`.
- **gender**, **age**, and **dob** are scalar properties on the person — not separate nodes.
  - Age and date-of-birth describe a person directly; they have no independent graph relationships.
  - Keeping them as properties matches how Prolog stores `male/1`, `age/2`, and `dob/2` as facts about individuals.

### Relationships

| Type | Pattern | Prolog equivalent | Rationale |
|------|---------|-------------------|-----------|
| `PARENT_OF` | `(parent)-[:PARENT_OF]->(child)` | `parent(Parent, Child)` | Directed edge captures parent→child semantics used by all derivation rules |
| `MARRIED_TO` | `(a)-[:MARRIED_TO]-(b)` | `married(A, B)` | Undirected in practice; stored once, queried with `-` for both directions. Marriage is a symmetric social link between two people — no need for a separate Marriage node unless we need wedding dates/status (not in current KB) |

### Constraints

```cypher
CREATE CONSTRAINT person_name IF NOT EXISTS
FOR (p:Person) REQUIRE p.name IS UNIQUE
```

---

## Base Fact Queries

### Parents of a person
```cypher
MATCH (child:Person {name: $person})<-[:PARENT_OF]-(parent:Person)
RETURN DISTINCT parent.name AS name ORDER BY name
```
**Reasoning:** Reverse `PARENT_OF` from child to parent — equivalent to `parent(X, Y)` with Y fixed.

### Children of a person (inverse parent)
```cypher
MATCH (parent:Person {name: $person})-[:PARENT_OF]->(child:Person)
RETURN DISTINCT child.name AS name ORDER BY name
```

### Siblings (shared parent rule)
```cypher
MATCH (p:Person {name: $person})<-[:PARENT_OF]-(par:Person)-[:PARENT_OF]->(sib:Person)
WHERE sib.name <> $person
RETURN DISTINCT sib.name AS name ORDER BY name
```
**Reasoning:** `sibling(X,Y) :- parent(Z,X), parent(Z,Y), X \= Y` — two people sharing at least one parent.

### Spouses
```cypher
MATCH (p:Person {name: $person})-[:MARRIED_TO]-(spouse:Person)
RETURN DISTINCT spouse.name AS name ORDER BY name
```
**Reasoning:** `spouse(X,Y) :- married(X,Y); married(Y,X)` — symmetric traversal.

---

## Derived Relationship Queries

### Father — `father(X,Y) :- parent(X,Y), male(X)`
```cypher
MATCH (child:Person {name: $person})<-[:PARENT_OF]-(father:Person {gender: 'male'})
RETURN DISTINCT father.name AS name ORDER BY name
```

### Mother — `mother(X,Y) :- parent(X,Y), female(X)`
```cypher
MATCH (child:Person {name: $person})<-[:PARENT_OF]-(mother:Person {gender: 'female'})
RETURN DISTINCT mother.name AS name ORDER BY name
```

### Son / Daughter — `son(X,Y) :- parent(Y,X), male(X)`
```cypher
MATCH (p:Person {name: $person})-[:PARENT_OF]->(son:Person {gender: 'male'})
RETURN DISTINCT son.name AS name ORDER BY name
```

### Husband / Wife
```cypher
-- husbands OF person (male spouses)
MATCH (p:Person {name: $person})-[:MARRIED_TO]-(h:Person {gender: 'male'})
RETURN DISTINCT h.name AS name ORDER BY name

-- wives OF person (female spouses)
MATCH (p:Person {name: $person})-[:MARRIED_TO]-(w:Person {gender: 'female'})
RETURN DISTINCT w.name AS name ORDER BY name
```

### Grandfather — `grandfather(X,Y) :- father(X,Z), parent(Z,Y)`
```cypher
MATCH (p:Person {name: $person})<-[:PARENT_OF]-(mid:Person)<-[:PARENT_OF]-(gf:Person {gender: 'male'})
RETURN DISTINCT gf.name AS name ORDER BY name
```

### Grandmother — `grandmother(X,Y) :- mother(X,Z), parent(Z,Y)`
```cypher
MATCH (p:Person {name: $person})<-[:PARENT_OF]-(mid:Person)<-[:PARENT_OF]-(gm:Person {gender: 'female'})
RETURN DISTINCT gm.name AS name ORDER BY name
```

### Grandparent — `grandparent(X,Y) :- parent(X,Z), parent(Z,Y)`
```cypher
MATCH (p:Person {name: $person})<-[:PARENT_OF*2]-(gp:Person)
RETURN DISTINCT gp.name AS name ORDER BY name
```

### Grandchild — inverse of grandparent (2-hop PARENT_OF forward)
```cypher
MATCH (p:Person {name: $person})-[:PARENT_OF*2]->(gc:Person)
RETURN DISTINCT gc.name AS name ORDER BY name
```

### Paternal grandfather — `paternal_grandfather(X,Y) :- father(Z,Y), father(X,Z)`
```cypher
MATCH (p:Person {name: $person})<-[:PARENT_OF]-(fa:Person {gender: 'male'})<-[:PARENT_OF]-(pgf:Person {gender: 'male'})
RETURN DISTINCT pgf.name AS name ORDER BY name
```

### Uncle — `uncle(X,Y) :- brother(X,Z), parent(Z,Y)`
Z is a parent of Y; X is Z's male sibling (not Z's parent).
```cypher
MATCH (p:Person {name: $person})<-[:PARENT_OF]-(par:Person)
MATCH (par)<-[:PARENT_OF]-(gp:Person)-[:PARENT_OF]->(uncle:Person {gender: 'male'})
WHERE uncle <> par
RETURN DISTINCT uncle.name AS name ORDER BY name
```

### Aunt — `aunt(X,Y) :- sister(X,Z), parent(Z,Y)`
```cypher
MATCH (p:Person {name: $person})<-[:PARENT_OF]-(par:Person)
MATCH (par)<-[:PARENT_OF]-(gp:Person)-[:PARENT_OF]->(aunt:Person {gender: 'female'})
WHERE aunt <> par
RETURN DISTINCT aunt.name AS name ORDER BY name
```

### Cousin — `cousin(X,Y) :- parent(A,X), parent(B,Y), sibling(A,B)`
```cypher
MATCH (p:Person {name: $person})<-[:PARENT_OF]-(myPar:Person)<-[:PARENT_OF]-(gp:Person)-[:PARENT_OF]->(parSib:Person)
WHERE parSib <> myPar
MATCH (parSib)-[:PARENT_OF]->(cousin:Person)
WHERE cousin.name <> $person
RETURN DISTINCT cousin.name AS name ORDER BY name
```

### Nephew — `nephew(X,Y) :- sibling(Y,Z), son(X,Z)`
```cypher
MATCH (p:Person {name: $person})<-[:PARENT_OF]-(gp:Person)-[:PARENT_OF]->(sib:Person)
WHERE sib <> p
MATCH (sib)-[:PARENT_OF]->(nephew:Person {gender: 'male'})
RETURN DISTINCT nephew.name AS name ORDER BY name
```

### Niece — `niece(X,Y) :- sibling(Y,Z), daughter(X,Z)`
```cypher
MATCH (p:Person {name: $person})<-[:PARENT_OF]-(gp:Person)-[:PARENT_OF]->(sib:Person)
WHERE sib <> p
MATCH (sib)-[:PARENT_OF]->(niece:Person {gender: 'female'})
RETURN DISTINCT niece.name AS name ORDER BY name
```

### In-laws
```cypher
-- father_in_law(X,Y) :- spouse(Y,Z), father(X,Z)
MATCH (p:Person {name: $person})-[:MARRIED_TO]-(sp:Person)<-[:PARENT_OF]-(fil:Person {gender: 'male'})
RETURN DISTINCT fil.name AS name ORDER BY name

-- mother_in_law(X,Y) :- spouse(Y,Z), mother(X,Z)
MATCH (p:Person {name: $person})-[:MARRIED_TO]-(sp:Person)<-[:PARENT_OF]-(mil:Person {gender: 'female'})
RETURN DISTINCT mil.name AS name ORDER BY name

-- brother_in_law(X,Y) :- spouse(Y,Z), brother(X,Z)
MATCH (p:Person {name: $person})-[:MARRIED_TO]-(sp:Person)<-[:PARENT_OF]-(gp:Person)-[:PARENT_OF]->(bil:Person {gender: 'male'})
WHERE bil <> sp
RETURN DISTINCT bil.name AS name ORDER BY name

-- sister_in_law(X,Y) :- spouse(Y,Z), sister(X,Z)
MATCH (p:Person {name: $person})-[:MARRIED_TO]-(sp:Person)<-[:PARENT_OF]-(gp:Person)-[:PARENT_OF]->(sil:Person {gender: 'female'})
WHERE sil <> sp
RETURN DISTINCT sil.name AS name ORDER BY name
```

### Elder / Younger sibling — `elder_sibling(X,Y) :- sibling(X,Y), is_elder(X,Y)`
```cypher
MATCH (p:Person {name: $person})<-[:PARENT_OF]-(par:Person)-[:PARENT_OF]->(sib:Person)
WHERE sib.name <> $person AND p.age IS NOT NULL AND sib.age IS NOT NULL AND sib.age > p.age
RETURN DISTINCT sib.name AS name ORDER BY name

-- younger: sib.age < p.age
```

---

## Recursive Rules (Variable-Length Paths)

### Ancestor — `ancestor(X,Y) :- parent(X,Y); ancestor(X,Z), ancestor(Z,Y)`
Prolog recursion walks up the parent chain. In Cypher, variable-length `PARENT_OF` is the direct equivalent:

```cypher
MATCH (anc:Person)-[:PARENT_OF*1..]->(p:Person {name: $person})
RETURN DISTINCT anc.name AS name ORDER BY name
```
**Why this works:** Any node reachable from ancestor to person via one or more `PARENT_OF` hops is an ancestor — same as the recursive Prolog base + inductive case combined.

### Descendant — `descendant(X,Y) :- ancestor(Y,X)`
```cypher
MATCH (p:Person {name: $person})-[:PARENT_OF*1..]->(desc:Person)
RETURN DISTINCT desc.name AS name ORDER BY name
```
**Why this works:** Descendants are all nodes reachable forward along `PARENT_OF` — the inverse direction of ancestor.

---

## List & Utility Queries

```cypher
-- All members
MATCH (p:Person) RETURN p.name ORDER BY p.name

-- Oldest (optional gender filter)
MATCH (p:Person) WHERE p.age IS NOT NULL [AND p.gender = $gender]
RETURN p.name ORDER BY p.age DESC LIMIT 1

-- Married couples (deduplicated)
MATCH (a:Person)-[:MARRIED_TO]-(b:Person)
WHERE a.name < b.name
RETURN a.name, b.name ORDER BY a.name
```

---

## same_generation (Python-assisted)

Prolog rule is mutually recursive across siblings, spouses, and parallel parent branches:
```
same_generation(X,Y) :- sibling(X,Y).
same_generation(X,Y) :- spouse(X,Y).
same_generation(X,Y) :- parent(PX,X), parent(PY,Y), same_generation(PX,PY), X \= Y.
```

This is implemented in Python using Neo4j-fetched siblings/spouses/parents rather than a single Cypher pattern, mirroring the original `_query_python` logic exactly.
