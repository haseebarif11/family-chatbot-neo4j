"""
Family Tree Chatbot — Streamlit UI with AIML + Neo4j graph reasoning.
Assignment 3: Prolog backend replaced with Neo4j; AIML interface unchanged.
"""

from __future__ import annotations
import re
import difflib
from pathlib import Path

import streamlit as st

try:
    import aiml
except ImportError:
    aiml = None

from neo4j_bridge import (
    FamilyGraphEngine,
    clear_data_entry_predicates,
    create_engine,
    list_family_members,
    normalize_relation,
    process_data_entry,
    reset_engine,
)

# ── Inference feature tokens (returned by AIML, dispatched below) ─────────
_INFERENCE_TOKENS = (
    "MUTUAL_CONNECTIONS",
    "HIDDEN_RELATIONSHIP",
    "AGE_SIMILARITY",
    "GRAPH_REPORT",
)

# ── Paths ──────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
AIML_PATH = BASE_DIR / "family_chatbot.aiml"


# ── Formatting helpers ────────────────────────────────────────────────
def title(name: str) -> str:
    return name.capitalize()


def join_names(names: list[str]) -> str:
    t = [title(n) for n in names]
    if len(t) <= 1:
        return t[0] if t else ""
    if len(t) == 2:
        return f"{t[0]} and {t[1]}"
    return ", ".join(t[:-1]) + f", and {t[-1]}"


PLURAL = {
    "parent": "parents", "child": "children", "children": "children",
    "grandparent": "grandparents", "grandfather": "grandfathers",
    "grandmother": "grandmothers", "grandchild": "grandchildren",
    "sibling": "siblings", "brother": "brothers", "sister": "sisters",
    "son": "sons", "daughter": "daughters", "uncle": "uncles",
    "aunt": "aunts", "cousin": "cousins", "nephew": "nephews",
    "niece": "nieces", "husband": "husbands", "wife": "wives",
    "spouse": "spouses", "ancestor": "ancestors", "descendant": "descendants",
    "father_in_law": "fathers-in-law", "mother_in_law": "mothers-in-law",
    "brother_in_law": "brothers-in-law", "sister_in_law": "sisters-in-law",
    "elder_sibling": "elder siblings", "younger_sibling": "younger siblings",
    "paternal_grandfather": "paternal grandfathers",
    "same_generation": "same-generation family members",
}


def rel_display(r: str) -> str:
    return r.replace("_", " ")


def format_answer(rel: str, person: str, answers: list[str]) -> str:
    p = title(person)
    r = normalize_relation(rel)
    if not answers:
        return f"I don't know the {rel_display(r)} of {p}."
    if r == "age":
        return f"{p} is {answers[0]} years old."
    if r == "dob":
        return f"{p} was born on {answers[0]}."
    names = join_names(answers)
    label = rel_display(PLURAL.get(r, r + "s") if len(answers) > 1 else r)
    verb = "are" if len(answers) > 1 else "is"
    return f"The {label} of {p} {verb} {names}."


LIST_DISPLAY = {
    "list_male": ("male member", "male members"),
    "list_female": ("female member", "female members"),
    "list_parent": ("parent", "parents"),
    "list_child": ("child", "children"),
    "list_sibling": ("person with siblings", "people with siblings"),
    "list_married": ("married couple", "married couples"),
    "list_age": ("age record", "age records"),
    "list_son": ("son", "sons"), "list_daughter": ("daughter", "daughters"),
}


def format_list(list_type: str, items: list[str]) -> str:
    if list_type in LIST_DISPLAY:
        _, plural = LIST_DISPLAY[list_type]
    else:
        base = list_type.replace("list_", "")
        plural = PLURAL.get(base, base + "s").replace("_", " ")

    if not items:
        return f"No {plural} found."
    if list_type == "list_age":
        lines = [f"- {title(n)}: {a} years" for n, a in (i.split(":", 1) for i in items)]
        return "Ages in the family:\n" + "\n".join(lines)
    if list_type == "list_married":
        seen = set()
        unique = []
        for item in items:
            h, w = item.split(":", 1)
            key = tuple(sorted([h, w]))
            if key not in seen:
                seen.add(key)
                unique.append(item)
        couples = [f"{title(h)} & {title(w)}" for h, w in (i.split(":", 1) for i in unique)]
        return "Married couples: " + ", ".join(couples) + "."
    names = ", ".join(title(n) for n in items)
    return f"All {plural} ({len(items)}): {names}."


# ── Regex query parser ────────────────────────────────────────────────
_RELS = (
    r'father[\s-]?in[\s-]?law|mother[\s-]?in[\s-]?law|'
    r'brother[\s-]?in[\s-]?law|sister[\s-]?in[\s-]?law|'
    r'date\s+of\s+birth|dob|age|'
    r'elder\s+sibling|elder\s+siblings|older\s+sibling|older\s+siblings|'
    r'younger\s+sibling|younger\s+siblings|paternal\s+grandfather|'
    r'same\s+generation|'
    r'father|mother|brother|sister|son|daughter|'
    r'parent|parents|children|child|kids|'
    r'grandfather|grandmother|grandparent|grandparents|'
    r'grandchild|grandchildren|'
    r'uncle|aunt|cousin|cousins|nephew|niece|'
    r'husband|wife|spouse|sibling|siblings|ancestor|ancestors|descendant|descendants'
)

LIST_KEYWORDS = {
    "MALE": "list_male", "MALES": "list_male",
    "FEMALE": "list_female", "FEMALES": "list_female",
    "PARENT": "list_parent", "PARENTS": "list_parent",
    "CHILD": "list_child", "CHILDREN": "list_child",
    "SIBLING": "list_sibling", "SIBLINGS": "list_sibling",
    "AGE": "list_age", "AGES": "list_age",
    "MARRIED": "list_married", "COUPLES": "list_married",
    "SON": "list_son", "SONS": "list_son",
    "DAUGHTER": "list_daughter", "DAUGHTERS": "list_daughter",
    "MEMBER": "members", "MEMBERS": "members",
    "FAMILY": "members", "FAMILY MEMBERS": "members",
    "FATHER": "list_father", "FATHERS": "list_father",
    "MOTHER": "list_mother", "MOTHERS": "list_mother",
    "BROTHER": "list_brother", "BROTHERS": "list_brother",
    "SISTER": "list_sister", "SISTERS": "list_sister",
    "UNCLE": "list_uncle", "UNCLES": "list_uncle",
    "AUNT": "list_aunt", "AUNTS": "list_aunt",
    "GRANDFATHER": "list_grandfather", "GRANDFATHERS": "list_grandfather",
    "GRANDMOTHER": "list_grandmother", "GRANDMOTHERS": "list_grandmother",
    "GRANDPARENT": "list_grandparent", "GRANDPARENTS": "list_grandparent",
    "GRANDCHILD": "list_grandchild", "GRANDCHILDREN": "list_grandchild",
    "COUSIN": "list_cousin", "COUSINS": "list_cousin",
    "NEPHEW": "list_nephew", "NEPHEWS": "list_nephew",
    "NIECE": "list_niece", "NIECES": "list_niece",
    "HUSBAND": "list_husband", "HUSBANDS": "list_husband",
    "WIFE": "list_wife", "WIVES": "list_wife",
    "SPOUSE": "list_spouse", "SPOUSES": "list_spouse",
    "ANCESTOR": "list_ancestor", "ANCESTORS": "list_ancestor",
    "DESCENDANT": "list_descendant", "DESCENDANTS": "list_descendant",
    "FATHER IN LAW": "list_father_in_law", "FATHERS IN LAW": "list_father_in_law",
    "FATHER-IN-LAW": "list_father_in_law", "FATHERS-IN-LAW": "list_father_in_law",
    "MOTHER IN LAW": "list_mother_in_law", "MOTHERS IN LAW": "list_mother_in_law",
    "MOTHER-IN-LAW": "list_mother_in_law", "MOTHERS-IN-LAW": "list_mother_in_law",
    "BROTHER IN LAW": "list_brother_in_law", "BROTHERS IN LAW": "list_brother_in_law",
    "BROTHER-IN-LAW": "list_brother_in_law", "BROTHERS-IN-LAW": "list_brother_in_law",
    "SISTER IN LAW": "list_sister_in_law", "SISTERS IN LAW": "list_sister_in_law",
    "SISTER-IN-LAW": "list_sister_in_law", "SISTERS-IN-LAW": "list_sister_in_law",
}

LIST_PREFIXES = (
    "TELL ME ", "SHOW ME ", "SHOW ", "LIST ALL ", "LIST OF ALL ", "LIST OF ", "LIST ",
    "WHAT ARE ALL THE ", "WHAT ARE ALL ", "WHAT ARE THE ", "WHAT ARE ",
    "WHO ARE ALL THE ", "WHO ARE ALL ", "WHO ARE THE ", "WHO ARE ",
    "GIVE ME ", "GIVE ALL ", "GIVE ", "NAMES OF ALL ", "NAMES OF ",
    "ALL THE ", "ALL ", "THE ",
)

_QUERY_PREFIXES = (
    "WHO ", "WHAT ", "HOW ", "WHEN ", "TELL ", "LIST ", "SHOW ",
    "FIND ", "CAN YOU ", "DO YOU ", "GIVE ", "ARE ", "ALL ",
)

_VERIFY_REL_RE = re.compile(
    r"^IS\s+\w+\s+(?:THE\s+|A\s+)?(?:"
    r"FATHER|MOTHER|BROTHER|SISTER|SON|DAUGHTER|SPOUSE|HUSBAND|WIFE|"
    r"PARENT|CHILD|UNCLE|AUNT|COUSIN|NEPHEW|NIECE|GRANDFATHER|GRANDMOTHER|"
    r"GRANDPARENT|GRANDCHILD|ANCESTOR|DESCENDANT"
    r")\s+OF\s+\w+",
    re.I,
)


def is_query_not_data_entry(text: str) -> bool:
    """Avoid treating verification or query phrasing as data-entry."""
    t = text.strip().upper()
    if _VERIFY_REL_RE.match(t):
        return True
    if re.match(r"^IS\s+\w+\s+MARRIED\s+TO\s+\w+", t):
        return True
    if re.match(r"^ARE\s+\w+\s+AND\s+\w+\s+(MARRIED|SIBLINGS|BROTHERS|SISTERS|COUSINS)", t):
        return True
    if t.startswith("IS ") and (" MALE" in t or " FEMALE" in t):
        return True
    return any(t.startswith(prefix) for prefix in _QUERY_PREFIXES)


def detect_list_intent(text: str) -> str | None:
    core = text.upper().strip()
    changed = True
    while changed:
        changed = False
        for prefix in LIST_PREFIXES:
            if core.startswith(prefix):
                core = core[len(prefix):].strip()
                changed = True
                break
    if re.search(r"\bOF\b", core):
        return None
    core = re.sub(r"\b(IN|OF)\s+(THE\s+)?FAMILY\b", "", core).strip()
    return LIST_KEYWORDS.get(core)


_AGE_PREFIX = re.compile(
    r"^(?:HOW\s+OLD\s+(?:IS|ARE)|WHAT\s+(?:IS\s+THE\s+AGE\s+OF|ARE\s+THE\s+AGES\s+OF)|"
    r"TELL\s+ME\s+(?:THE\s+)?AGES?\s+OF|AGES?\s+OF)\s+(.+)$",
    re.I,
)


def split_names(name_blob: str) -> list[str]:
    blob = re.sub(r",\s*and\s+", ", ", name_blob.strip(), flags=re.I)
    parts = re.split(r",\s*|\s+and\s+", blob, flags=re.I)
    return [p.strip().lower() for p in parts if p.strip()]


def extract_age_names(text: str) -> list[str] | None:
    t = text.strip()
    m = _AGE_PREFIX.match(t)
    if not m:
        m = re.match(r"^HOW\s+OLD\s+(.+)\s+ARE$", t, re.I)
    if not m:
        return None
    names = split_names(m.group(1))
    return names if names else None


def format_ages(names: list[str], engine: FamilyGraphEngine) -> str:
    parts = []
    for name in names:
        ages = engine.query_relation("age", name)
        if ages:
            parts.append(f"{title(name)} is {ages[0]} years old")
        else:
            parts.append(f"I don't have age info for {title(name)}")
    if len(parts) == 1:
        return parts[0] + "."
    if len(parts) == 2:
        return f"{parts[0]}, and {parts[1]}."
    return ", ".join(parts[:-1]) + f", and {parts[-1]}."


def parse_query(text: str) -> dict | None:
    t = text.strip()

    m = re.match(r'(?:IS\s+|YES\s+)?(\w+)\s+(MALE|FEMALE)(?:\s+TRUE\s+OR\s+FALSE)?$', t, re.I)
    if m:
        return {"rel": "gender_check", "p1": m[1].lower(), "gender": m[2].lower()}

    m = re.match(r'(?:WHAT\s+IS\s+THE\s+)?RELATIONSHIP\s+BETWEEN\s+(\w+)\s+AND\s+(\w+)', t, re.I)
    if m:
        return {"rel": "discover", "p1": m[1].lower(), "p2": m[2].lower()}

    m = re.match(r'WHO\s+IS\s+(OLDER|YOUNGER),?\s+(\w+)\s+OR\s+(\w+)', t, re.I)
    if m:
        return {"rel": "compare_age", "p1": m[2].lower(), "p2": m[3].lower(), "cmp": m[1].lower()}

    m = re.match(r'IS\s+(\w+)\s+(OLDER|YOUNGER)\s+THAN\s+(\w+)', t, re.I)
    if m:
        return {"rel": "compare_age", "p1": m[1].lower(), "p2": m[3].lower(), "cmp": m[2].lower()}

    m = re.match(rf'IS\s+(\w+)\s+(?:THE\s+|A\s+)?({_RELS})\s+OF\s+(\w+)', t, re.I)
    if m:
        return {"rel": m[2].lower(), "p1": m[3].lower(), "verify": m[1].lower()}

    m = re.match(r'IS\s+(\w+)\s+MARRIED\s+TO\s+(\w+)', t, re.I)
    if m:
        return {"rel": "spouse", "p1": m[2].lower(), "verify": m[1].lower()}

    m = re.match(r'ARE\s+(\w+)\s+AND\s+(\w+)\s+(MARRIED|SIBLINGS|BROTHERS|SISTERS|COUSINS)', t, re.I)
    if m:
        vrel = {"MARRIED": "spouse", "SIBLINGS": "sibling", "BROTHERS": "brother",
                "SISTERS": "sister", "COUSINS": "cousin"}.get(m[3].upper(), m[3].lower())
        return {"rel": vrel, "p1": m[2].lower(), "verify": m[1].lower()}

    m = re.search(r'HOW\s+OLD\s+IS\s+(\w+)', t, re.I)
    if m:
        return {"rel": "age", "p1": m[1].lower()}

    m = re.search(r'WHEN\s+WAS\s+(\w+)\s+BORN', t, re.I)
    if m:
        return {"rel": "dob", "p1": m[1].lower()}

    m = re.search(rf'({_RELS})\s+OF\s+(\w+)', t, re.I)
    if m:
        return {"rel": re.sub(r'^(all\s+the\s+|all\s+|the\s+)', '', m[1], flags=re.I).lower(), "p1": m[2].lower()}

    # Make sure we don't match X's relation followed by IS/WAS/= (which is data entry)
    if not re.search(r"'\s*S\s+\w+\s+(?:IS|WAS|=)", t, re.I):
        m = re.search(rf"(\w+)'S\s+({_RELS})", t, re.I)
        if m:
            return {"rel": m[2].lower(), "p1": m[1].lower()}

    return None


RELS_TO_TEST = [
    "father", "mother", "parent", "son", "daughter", "children", "brother", "sister", "sibling",
    "husband", "wife", "spouse", "grandfather", "grandmother",
    "grandparent", "grandchild", "uncle", "aunt", "cousin", "nephew", "niece",
    "ancestor", "descendant", "elder_sibling", "younger_sibling",
    "paternal_grandfather", "same_generation",
    "father_in_law", "mother_in_law", "brother_in_law", "sister_in_law",
]


def discover_relationship(p1: str, p2: str, engine: FamilyGraphEngine) -> str:
    known = [m.lower() for m in list_family_members()]
    if p1 not in known:
        return f"No information found for {title(p1)}."
    if p2 not in known:
        return f"No information found for {title(p2)}."

    for r in RELS_TO_TEST:
        if p2 in [a.lower() for a in engine.query_relation(r, p1)]:
            return f"{title(p2)} is the {rel_display(r)} of {title(p1)}."
    for r in RELS_TO_TEST:
        if p1 in [a.lower() for a in engine.query_relation(r, p2)]:
            return f"{title(p1)} is the {rel_display(r)} of {title(p2)}."

    inferred = engine.discover_relationship(p1, p2)
    if inferred:
        if inferred.startswith("connected_by_"):
            hops = inferred.split("_")[-1]
            return (
                f"{title(p1)} and {title(p2)} are related through the family graph "
                f"({hops} steps apart)."
            )
        if inferred == "in_law":
            return f"{title(p1)} and {title(p2)} are related by marriage (in-law connection)."
        return f"{title(p2)} is the {rel_display(inferred)} of {title(p1)}."

    return f"No direct relationship found between {title(p1)} and {title(p2)}."


def correct_name(text: str, members: list[str]) -> str:
    for w in re.findall(r'\b\w+\b', text.lower()):
        if w not in members:
            matches = difflib.get_close_matches(w, members, n=1, cutoff=0.8)
            if matches:
                text = re.sub(r'\b' + re.escape(w) + r'\b', matches[0], text, flags=re.I)
    return text


@st.cache_resource
def load_engine():
    return create_engine()


@st.cache_resource
def load_aiml_kernel(_aiml_mtime: float):
    if aiml is None:
        raise RuntimeError("python-aiml not installed. Run: pip install python-aiml")
    kernel = aiml.Kernel()
    kernel.verbose(False)
    if AIML_PATH.exists():
        kernel.learn(str(AIML_PATH))
    else:
        raise RuntimeError(f"AIML file not found: {AIML_PATH}")
    return kernel


def preprocess(text: str) -> str:
    text = re.sub(r"[?.!,;:]+$", "", text.strip())
    return re.sub(r"\s+", " ", text).upper()


def _subject_from_entry_clause(text: str) -> str:
    patterns = (
        r"^ADD\s+(.+?)\s+AS\s+(?:A\s+)?(?:MALE|FEMALE)$",
        r"^ADD\s+(?:MALE|FEMALE)\s+PERSON\s+(.+)$",
        r"^(.+?)\s+IS\s+(?:A\s+)?(?:MALE|FEMALE)$",
        r"^(.+?)\s+IS\s+\d+\s+YEARS\s+OLD$",
        r"^SET\s+AGE\s+OF\s+(.+?)\s+TO\s+\d+$",
    )
    for pattern in patterns:
        m = re.match(pattern, text, re.I)
        if m:
            return m[1].strip()
    return ""


def split_compound_data_entry(text: str) -> list[str]:
    text = preprocess(text)
    if " AND " not in text:
        return [text]

    m = re.match(r"^(.+?)\s+AND\s+((?:HIS|HER|THEIR)\s+.+)$", text, re.I)
    if m:
        first, second = m[1].strip(), m[2].strip()
        subject = _subject_from_entry_clause(first)
        if subject:
            second = re.sub(r"^(HIS|HER|THEIR)\s+", f"{subject} ", second, flags=re.I)
            return [first, second]

    first, second = [p.strip() for p in text.split(" AND ", 1)]
    if re.match(r"^(ADD|SET|DELETE|REMOVE)\b", first, re.I) and re.match(
        r"^(ADD|SET|DELETE|REMOVE)\b", second, re.I
    ):
        return [first, second]

    return [text]


def get_reply(user_text: str, kernel, engine) -> tuple[str, bool]:
    parts = split_compound_data_entry(user_text)
    if len(parts) == 1:
        return _get_reply_single(parts[0], kernel, engine)

    replies = []
    reload_needed = False
    current_engine = engine
    for part in parts:
        reply, reload_part = _get_reply_single(part, kernel, current_engine)
        replies.append(reply)
        reload_needed = reload_needed or reload_part
        if reload_part:
            current_engine = reset_engine()
    return "\n".join(replies), reload_needed


def try_possessive_data_entry(text: str, kernel) -> str | None:
    # Match: X's father is Y, X's husband was Y, X's age is 30, etc.
    # Pattern: ^(\w+)'S\s+(FATHER|MOTHER|HUSBAND|WIFE|AGE|DATE\s+OF\s+BIRTH|DOB)\s+(?:IS|WAS|=)\s+(.+)$
    m = re.match(r"^(\w+)'S\s+(FATHER|MOTHER|HUSBAND|WIFE|AGE|DATE\s+OF\s+BIRTH|DOB)\s+(?:IS|WAS|=)\s+(.+)$", text.strip(), re.I)
    if m:
        p1 = m.group(1).lower()
        relation = m.group(2).lower().replace("date of birth", "dob")
        val = m.group(3).strip()

        clear_data_entry_predicates(kernel)
        
        # Map relation to AIML data-entry predicates
        if relation == "father":
            kernel.setPredicate("fact_type", "parent_male")
            kernel.setPredicate("person1", val) # parent
            kernel.setPredicate("person2", p1)  # child
        elif relation == "mother":
            kernel.setPredicate("fact_type", "parent_female")
            kernel.setPredicate("person1", val) # parent
            kernel.setPredicate("person2", p1)  # child
        elif relation == "husband":
            kernel.setPredicate("fact_type", "husband")
            kernel.setPredicate("person1", val)
            kernel.setPredicate("person2", p1)
        elif relation == "wife":
            kernel.setPredicate("fact_type", "wife")
            kernel.setPredicate("person1", val)
            kernel.setPredicate("person2", p1)
        elif relation in ("age", "dob"):
            kernel.setPredicate("fact_type", relation)
            kernel.setPredicate("person1", p1)
            kernel.setPredicate("value", val)

        msg = process_data_entry(kernel)
        clear_data_entry_predicates(kernel)
        return msg
    return None


def _get_reply_single(user_text: str, kernel, engine) -> tuple[str, bool]:
    """Return (reply, reload_engine_needed)."""
    text = preprocess(user_text)
    if not text:
        return "Please type a question or data-entry command.", False

    members = [m.lower() for m in list_family_members()]
    text_corrected = correct_name(text, members)

    # Check for possessive data entry first
    possessive_msg = try_possessive_data_entry(text_corrected, kernel)
    if possessive_msg:
        return possessive_msg, True

    age_names = extract_age_names(text_corrected)
    if age_names and len(age_names) > 1:
        return format_ages(age_names, engine), False

    li = detect_list_intent(text_corrected)
    if li == "members":
        return f"All family members ({len(members)}): {', '.join(title(m) for m in members)}.", False
    if li:
        return format_list(li, engine.query_list(li)), False

    clear_data_entry_predicates(kernel)
    for pred in ("rel", "p1", "p2", "cmp", "verify_p1", "inverse", "gender_check"):
        kernel.setPredicate(pred, "")
    aiml_resp = kernel.respond(text_corrected)

    if aiml_resp and "DATA_ENTRY" in aiml_resp and not is_query_not_data_entry(text_corrected):
        entry_msg = process_data_entry(kernel)
        clear_data_entry_predicates(kernel)
        if entry_msg:
            return entry_msg, True

    clear_data_entry_predicates(kernel)

    if aiml_resp and aiml_resp.strip().endswith("LIST"):
        token = aiml_resp.strip()[:-4].strip()
        if token.startswith("list_"):
            return format_list(token, engine.query_list(token)), False

    if aiml_resp and "MEMBERS_LIST" in aiml_resp:
        members = [m.lower() for m in list_family_members()]
        return f"All family members ({len(members)}): {', '.join(title(m) for m in members)}.", False

    if aiml_resp and "DISCOVER_RELATIONSHIP" in aiml_resp:
        p1 = (kernel.getPredicate("p1") or "").strip().lower()
        p2 = (kernel.getPredicate("p2") or "").strip().lower()
        return discover_relationship(p1, p2, engine), False

    if aiml_resp and "COMPARE_AGE" in aiml_resp:
        parsed = {
            "p1": (kernel.getPredicate("p1") or "").strip().lower(),
            "p2": (kernel.getPredicate("p2") or "").strip().lower(),
            "cmp": (kernel.getPredicate("cmp") or "older").strip().lower(),
        }
        return _compare_age(parsed, engine), False

    # ── Inference & Knowledge-Discovery handlers ─────────────────────────
    if aiml_resp and "MUTUAL_CONNECTIONS" in aiml_resp:
        p1 = (kernel.getPredicate("p1") or "").strip().lower()
        p2 = (kernel.getPredicate("p2") or "").strip().lower()
        if not p1 or not p2:
            return "Please name two people, e.g. 'What do Ahmed and Laiba have in common?'", False
        return engine.mutual_connections(p1, p2), False

    if aiml_resp and "HIDDEN_RELATIONSHIP" in aiml_resp:
        p1 = (kernel.getPredicate("p1") or "").strip().lower()
        p2 = (kernel.getPredicate("p2") or "").strip().lower()
        if not p1 or not p2:
            return "Please name two people, e.g. 'How is Ahmed related to Nadia?'", False
        return engine.hidden_relationship(p1, p2), False

    if aiml_resp and "AGE_SIMILARITY" in aiml_resp:
        p1 = (kernel.getPredicate("p1") or "").strip().lower()
        if not p1:
            return "Please name a person, e.g. 'Who is close in age to Laiba?'", False
        return engine.age_similarity(p1), False

    if aiml_resp and "GRAPH_REPORT" in aiml_resp:
        return engine.graph_report(), False

    oldest_token = (aiml_resp or "").strip()
    if oldest_token.endswith(("OLDEST", "OLDEST_MALE", "OLDEST_FEMALE")):
        if oldest_token.endswith("OLDEST_FEMALE"):
            gf = "female"
        elif oldest_token.endswith("OLDEST_MALE"):
            gf = "male"
        else:
            gf = None
        oldest = engine.get_oldest(gf)
        if oldest:
            suffix = f" {gf}" if gf else ""
            return f"{title(oldest)} is the oldest{suffix} family member.", False
        return "I don't have age info to determine the oldest.", False

    gc = kernel.getPredicate("gender_check") or ""
    if gc and aiml_resp and "CHECK_GENDER" in aiml_resp:
        person = kernel.getPredicate("p1") or ""
        person = re.sub(r'\b(YES|NO|TRUE|FALSE|OR)\b', '', person, flags=re.I).strip().lower()
        if person:
            is_g = engine.check_gender(person, gc)
            if is_g:
                return f"Yes, {title(person)} is {gc}.", False
            return f"No, {title(person)} is not {gc}.", False

    rel = kernel.getPredicate("rel") or ""
    p1 = kernel.getPredicate("p1") or ""

    if not rel or not p1:
        parsed = parse_query(text_corrected)
        if parsed:
            r = parsed.get("rel", "")
            if r == "gender_check":
                is_g = engine.check_gender(parsed["p1"], parsed["gender"])
                if is_g:
                    return f"Yes, {title(parsed['p1'])} is {parsed['gender']}.", False
                return f"No, {title(parsed['p1'])} is not {parsed['gender']}.", False
            if r == "discover":
                return discover_relationship(parsed["p1"], parsed["p2"], engine), False
            if r == "compare_age":
                return _compare_age(parsed, engine), False
            rel = r
            p1 = parsed.get("p1", "")
            verify = parsed.get("verify", "")
            if verify:
                return _verify(verify, rel, p1, engine), False

    known = [m.lower() for m in list_family_members()]
    if p1 and p1.lower().strip() not in known:
        return f"No information found for {title(p1)}.", False

    if rel and p1:
        rel_norm = normalize_relation(rel)
        names = split_names(p1)
        if rel_norm == "age" and len(names) > 1:
            return format_ages(names, engine), False
        answers = engine.query_relation(rel_norm, names[0])
        return format_answer(rel_norm, names[0], answers), False

    if aiml_resp:
        return aiml_resp.strip(), False
    return "I didn't understand. Type HELP for examples.", False


def _compare_age(parsed: dict, engine) -> str:
    p1, p2, cmp = parsed["p1"], parsed["p2"], parsed["cmp"]
    a1 = engine.query_relation("age", p1)
    a2 = engine.query_relation("age", p2)
    if not a1:
        return f"I don't have age info for {title(p1)}."
    if not a2:
        return f"I don't have age info for {title(p2)}."
    age1, age2 = int(a1[0]), int(a2[0])
    diff = abs(age1 - age2)
    if age1 == age2:
        return f"Both {title(p1)} and {title(p2)} are the same age ({age1} years)."
    older = title(p1) if age1 > age2 else title(p2)
    younger = title(p2) if age1 > age2 else title(p1)
    if cmp == "older":
        return f"{older} is older than {younger} by {diff} years."
    return f"{younger} is younger than {older} by {diff} years."


def _verify(verify_person: str, rel: str, p1: str, engine) -> str:
    answers = [a.lower() for a in engine.query_relation(rel, p1)]
    r = rel_display(normalize_relation(rel))
    if verify_person.lower() in answers:
        return f"Yes, {title(verify_person)} is the {r} of {title(p1)}."
    if answers:
        return f"No, {title(verify_person)} is not the {r} of {title(p1)}. The {r} is {join_names(answers)}."
    return f"No, {title(verify_person)} is not the {r} of {title(p1)}."


def _inject_app_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background: linear-gradient(165deg, #f8fafc 0%, #eef2f7 45%, #e8f0ec 100%);
        }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #1e3a2f 0%, #2d5a47 100%);
        }
        [data-testid="stSidebar"] * {
            color: #f0fdf4 !important;
        }
        [data-testid="stSidebar"] .stButton > button {
            background: #4ade80;
            color: #14532d !important;
            border: none;
            font-weight: 600;
            border-radius: 8px;
        }
        [data-testid="stSidebar"] .stButton > button:hover {
            background: #86efac;
            color: #14532d !important;
        }
        .hero-banner {
            background: linear-gradient(135deg, #1e3a2f 0%, #2d6a4f 55%, #40916c 100%);
            border-radius: 16px;
            padding: 1.6rem 1.8rem;
            margin-bottom: 1.2rem;
            box-shadow: 0 8px 24px rgba(30, 58, 47, 0.18);
        }
        .hero-banner h1 {
            color: #ffffff !important;
            font-size: 2rem !important;
            margin: 0 0 0.35rem 0 !important;
            letter-spacing: -0.02em;
        }
        .hero-banner p {
            color: #d8f3dc !important;
            margin: 0;
            font-size: 1rem;
        }
        .engine-badge {
            display: inline-block;
            background: rgba(255, 255, 255, 0.15);
            border: 1px solid rgba(255, 255, 255, 0.25);
            border-radius: 999px;
            padding: 0.2rem 0.75rem;
            font-size: 0.82rem;
            margin-top: 0.6rem;
            color: #ecfdf5 !important;
        }
        [data-testid="stChatMessage"] {
            border-radius: 12px;
            border: 1px solid rgba(45, 106, 79, 0.12);
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
        }
        [data-testid="stChatInput"] textarea {
            border-radius: 12px !important;
            border: 2px solid #95d5b2 !important;
        }
        [data-testid="stChatInput"] textarea:focus {
            border-color: #2d6a4f !important;
            box-shadow: 0 0 0 2px rgba(45, 106, 79, 0.15) !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    aiml_mtime = AIML_PATH.stat().st_mtime if AIML_PATH.exists() else 0.0

    st.set_page_config(page_title="Family Tree Chatbot", page_icon="🌳", layout="centered")
    _inject_app_styles()

    try:
        engine, label = load_engine()
        kernel = load_aiml_kernel(aiml_mtime)
    except Exception as e:
        st.error(f"Could not start chatbot: {e}")
        st.stop()

    st.markdown(
        f"""
        <div class="hero-banner">
            <h1>🌳 Family Tree Chatbot</h1>
            <p>Ask relationship questions or add family facts — powered by AIML &amp; Neo4j.</p>
            <span class="engine-badge">Engine: {label}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Check for empty database and suggest seeding
    db_empty = False
    try:
        members_list = list_family_members()
        if len(members_list) == 0:
            db_empty = True
    except Exception:
        db_empty = True

    if db_empty:
        st.warning("⚠️ The Neo4j database is empty. Would you like to seed it with the default family tree?")
        if st.button("🌱 Seed Family Tree from family_kb.pl"):
            with st.spinner("Seeding database..."):
                try:
                    from migrate_pl_to_neo4j import migrate
                    migrate(Path(__file__).resolve().parent / "family_kb.pl", clear=True)
                    st.success("Database seeded successfully! Reloading...")
                    load_engine.clear()
                    st.rerun()
                except Exception as ex:
                    st.error(f"Failed to seed database: {ex}")

    with st.sidebar:
        st.markdown("## Quick Guide")
        with st.expander("➕ Add family data", expanded=False):
            st.markdown(
                "- `ADD MALE PERSON Ali`\n"
                "- `ADD FEMALE PERSON Sara`\n"
                "- `ADD PARENT Haider OF Ali`\n"
                "- `SET AGE OF Ali TO 28`\n"
                "- `Haider and Nadia are married`\n"
                "- `DELETE PERSON Ali`"
            )
        with st.expander("🔍 Query examples", expanded=True):
            st.markdown(
                "- Who is the father of Ali?\n"
                "- How old is Ali?\n"
                "- Is Ali male?\n"
                "- All males\n"
                "- Graph report\n"
                "- Hidden relationship between Ahmed and Nadia"
            )
        if st.button("🔄 Reload Data"):
            load_engine.clear()
            load_aiml_kernel.clear()
            st.rerun()

    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": (
                    "Hi! I'm your family chatbot 🌳\n\n"
                    "You can **add** family members (e.g. `ADD MALE PERSON Ali`) "
                    "or **ask** questions (e.g. `Who is the father of Ali?`) in this chat."
                ),
            }
        ]

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Add family data or ask a question..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                reply, reload_needed = get_reply(prompt, kernel, engine)
                if reload_needed:
                    load_engine.clear()
                    engine, label = load_engine()
            st.markdown(reply)
        st.session_state.messages.append({"role": "assistant", "content": reply})


if __name__ == "__main__":
    main()
