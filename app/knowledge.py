"""The trusted-source library: curated cards plus (optionally) full FDA label sections.

Retrieval is plain BM25 over the passages, so it runs offline with no extra packages.
The coach may only answer from what this returns, which is what makes citations honest.
"""
import json
import math
import re
from collections import Counter
from functools import lru_cache

from . import config

STOP = set("""a an and are as at be but by can do does for from has have how i if in into is it its
me my of on or so that the their them then there these this to was what when where which who why
will with you your should could would am im ive day days ago now get got much many need just also any some
make made lol haha ok okay yeah yes yep nope please want like know think tell thing stuff really pretty
maybe guess anyway btw tonight tomorrow today""".split())

SYNONYMS = {
    "ozempic": "semaglutide", "wegovy": "semaglutide", "rybelsus": "semaglutide",
    "mounjaro": "tirzepatide", "zepbound": "tirzepatide",
    "tired": "fatigue", "hurts": "pain", "hurt": "pain", "ache": "pain", "exhausted": "fatigue", "nauseous": "nausea", "nauseated": "nausea", "sick": "nausea", "throw": "vomiting",
    "puke": "vomiting", "vomit": "vomiting", "constipated": "constipation", "poop": "constipation",
    "forgot": "missed", "forget": "missed", "skip": "missed", "late": "missed",
    "shot": "injection", "inject": "injection", "jab": "injection", "pen": "injection",
    "muscle": "muscle", "workout": "strength", "lifting": "strength", "gym": "strength",
    "water": "fluids", "hydrate": "fluids", "dehydrated": "dehydration",
    "pregnant": "pregnancy", "birth": "contraception", "pill": "contraception",
    "fridge": "refrigerator", "store": "storage", "surgery": "anesthesia",
    "depressed": "depression", "suicidal": "suicidal", "lump": "thyroid", "neck": "thyroid",
}


def _tokens(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text.lower()):
        if w in STOP or len(w) < 2:
            continue
        out.append(w)
        if w in SYNONYMS:
            out.append(SYNONYMS[w])
        if w.endswith("s") and len(w) > 4:
            out.append(w[:-1])
    return out


def _content_tokens(text: str) -> list[str]:
    """Query tokens that carry meaning: no stopwords, no generic filler, no synonym expansions.

    Used to require that a returned passage actually shares a real word with the question, so a
    weak top match can't drag in passages that only share a stopword-ish token.
    """
    out = []
    for w in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text.lower()):
        if w in STOP or w in GENERIC or len(w) < 3:
            continue
        out.append(w)
        if w.endswith("s") and len(w) > 4:
            out.append(w[:-1])
        if w in SYNONYMS:                 # "constipated" -> "constipation" is a real content word
            out.append(SYNONYMS[w])
    return out


@lru_cache(maxsize=1)
def load() -> tuple[list[dict], dict]:
    passages, sources = [], {}
    for path in sorted(config.KNOWLEDGE_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        sources.update(data.get("sources", {}))
        for c in data.get("cards", []):
            src = sources.get(c["source"], {})
            passages.append({**c, "source_name": src.get("name", c["source"]), "url": src.get("url", "")})
    return passages, sources


@lru_cache(maxsize=1)
def _index():
    passages, _ = load()
    docs = [_tokens(f"{p['title']} {p['title']} {p.get('section', '')} {' '.join(p.get('drugs', []))} {p['text']}")
            for p in passages]
    df = Counter(t for d in docs for t in set(d))
    avg = sum(len(d) for d in docs) / max(1, len(docs))
    return docs, df, avg


def search(query: str, k: int = 4, medication: str | None = None) -> list[dict]:
    passages, _ = load()
    docs, df, avg = _index()
    q = _tokens(query)
    if not q:
        return []
    content = set(_content_tokens(query))
    if not content:                       # only filler words ("how's it going?", "what's up"): nothing to look up
        return []
    n, k1, b = len(docs), 1.5, 0.75
    scored = []
    for i, d in enumerate(docs):
        tf = Counter(d)
        s = 0.0
        for t in q:
            if t in tf:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(d) / avg))
        if s <= 0:
            continue
        # A passage must share at least one real content word with the question. Without this, a weak
        # top match admits passages that only share a filler token, and the coach would cite them.
        if content and not (content & set(d)):
            continue
        drugs = passages[i].get("drugs") or []
        if medication and drugs:          # prefer passages about the user's own medicine
            s *= 1.25 if medication.lower() in drugs else 0.8
        scored.append((s, i))
    scored.sort(reverse=True)
    if not scored:
        return []
    top = scored[0][0]
    return [dict(passages[i], score=round(s, 3)) for s, i in scored[:k] if s >= top * 0.35]


GENERIC = set("""about after again almost always another around before being better bother deal doing
during every feel feeling first going happen happens having little normal okay other really since started
start still thing things today until usual usually week weeks worse worried wrong""".split())


def unknown_terms(query: str) -> list[str]:
    """Content words the library never mentions (e.g. 'alcohol'): a sign the question is out of scope."""
    _, df, _ = _index()
    out = set()
    for w in re.findall(r"[a-z]+", query.lower()):
        if len(w) < 5 or w in STOP or w in GENERIC:
            continue
        if not any(t in df for t in _tokens(w)):      # neither the word nor its synonym/stem is known
            out.add(w)
    return sorted(out)


def stats() -> dict:
    passages, sources = load()
    return {"passages": len(passages), "sources": len(sources)}
