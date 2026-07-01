# Family Tree Chatbot 

Dynamic family data entry, deletion, and relationship querying using **AIML + Neo4j + Streamlit**.

stage 2's Prolog/Python reasoning layer has been replaced with a Neo4j graph database. The AIML chat interface is unchanged.

## Architecture

```
User → Streamlit (app.py) → AIML (family_chatbot.aiml) → predicates (rel, p1, p2)
                                      ↓
                              neo4j_bridge.py (FamilyGraphEngine)
                                      ↓
                              Neo4j (Person nodes, PARENT_OF / MARRIED_TO edges)
```

- **Base facts** stored as graph data: `Person` nodes with `gender`, `age`, `dob` properties; `PARENT_OF` and `MARRIED_TO` relationships.
- **Derived relations** (father, cousin, ancestor, etc.) computed via Cypher traversals mirroring every rule in `family_kb.pl`.
- **Recursive rules** (ancestor/descendant) use variable-length path matching `[:PARENT_OF*1..]`.
- **Fallback reasoning**: BFS graph exploration when a relationship isn't covered by a named Cypher pattern.

See `CYPHER_QUERIES.md` for the full query reference and design rationale.

## Prerequisites

1. [Neo4j Desktop](https://neo4j.com/download/) or Neo4j Community running locally
2. Python 3.10+

## Setup

```bash
cd family_chatbot
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your Neo4j password
```

## Migrate / seed family data (one-time)

Load the full 14-person family tree into Neo4j:

```bash
python migrate_pl_to_neo4j.py --clear
```

`family_kb.pl` holds the canonical seed facts (restored from Assignment 1). Runtime chat data entry writes directly to Neo4j via `neo4j_bridge.py`.

## Run

```bash
streamlit run app.py
```

## Data entry examples

- `ADD MALE PERSON Ali`
- `ADD FEMALE PERSON Sara`
- `ADD PARENT Haider OF Ali`
- `SET AGE OF Ali TO 28`
- `Haider is the father of Ali`
- `Haider and Nadia are married`
- `DELETE PERSON Ali`

## Query examples

- `Who is the father of Ali?`
- `What is the relationship between Ali and Sara?`
- `Who is older, Ali or Sara?`
- `How old is Ali?`
- `Is Ali male?`
- `All family members`
- `What do Ahmed and Laiba have in common?`
- `How is Ahmed related to Nadia?`
- `Who is close in age to Laiba?`
- `Tell me about the family graph`

## Tests (requires Neo4j)

```bash
pip install -r requirements.txt
cp .env.example .env   # set NEO4J_PASSWORD
python migrate_pl_to_neo4j.py --clear
pytest tests/ -v
python verify_live_queries.py
```

Tests skip automatically if Neo4j is not running on `bolt://localhost:7687`.

## Files

| File | Purpose |
|------|---------|
| `app.py` | Streamlit UI + AIML orchestration (minimal changes from A2) |
| `neo4j_bridge.py` | `FamilyGraphEngine` — Cypher queries, BFS fallback, connection config, and data-entry helpers |
| `migrate_pl_to_neo4j.py` | One-time Prolog → Neo4j migration |
| `verify_live_queries.py` | Smoke-test queries against live Neo4j |
| `tests/test_family_graph.py` | Pytest suite (intermarried-branch cases) |
| `family_chatbot.aiml` | AIML patterns (with new inference query patterns) |
| `family_kb.pl` | Original Prolog rules/facts (reference + migration source) |
| `CYPHER_QUERIES.md` | Schema design and Cypher query documentation |
