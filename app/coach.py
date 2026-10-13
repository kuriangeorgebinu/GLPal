"""The cited Q&A coach.

Order of checks for every question:
1. Red flags (emergency symptoms)  -> urgent-care message first, with the relevant cited warning.
2. Dose-change requests            -> never advise; point to the prescriber (still cite the schedule).
3. Retrieve trusted passages       -> if nothing relevant, say so instead of guessing.
4. Answer ONLY from those passages, with [n] citations; citations are validated after generation.
"""
import re

from . import knowledge, llm

DISCLAIMER = "GLPal gives general education from trusted sources, not medical advice. Your prescriber knows your situation."

# The six red-flag categories, in the order they are checked. Each one is also a card id in
# knowledge/curated_sources.json, so the urgent message can quote the official warning.
RED_FLAG_CATEGORIES = ("pancreatitis", "allergy", "mood", "kidney-dehydration", "thyroid-boxed", "gallbladder")

# Order-independent building blocks. A pattern fires when the words appear anywhere in the question,
# in any order, so "my stomach pain is really bad" and "I have severe abdominal pain" both match.
_SEVERE = r"(severe|severely|really bad|very bad|so bad|bad|intense|unbearable|extreme|terrible|awful|" \
          r"won.?t go away|wont go away|not going away|doesn.?t go away|does not go away|constant|constantly|" \
          r"getting worse|getting bad|really hurts|really hurting|really sore)"
_STOMACH = r"(stomach|abdominal|abdomen|belly|tummy|gut)"
_PAIN = r"(pain|pains|painful|hurt|hurts|hurting|ache|aching|sore|soreness|cramp|cramping|cramps)"
_BREATHE = r"(can.?t breathe|cannot breathe|hard to breathe|hard time breathing|difficult to breathe|" \
           r"difficulty breathing|trouble breathing|short of breath|shortness of breath|breathless|" \
           r"struggling to breathe|gasping|wheez|anaphyla)"
_SWELL = r"(swell|swollen|swelling|puffy|puffiness|puffing up|blowing up|hives|welts|rash|itch)"
_FACE = r"(face|facial|lips?|tongue|throat|mouth|cheeks?|eyes?|eyelids?|neck)"
_VOMIT = r"(throw(ing)? up|threw up|vomit(ing|ed)?|puk(e|ing|ed)|sick to my stomach|can.?t stop being sick)"
_URINE = r"(pee|peeing|peed|urinate|urinating|urine|wee|weeing|bathroom|toilet)"
_MOOD = r"(suicid\w*|kill myself|killing myself|end my life|ending my life|take my own life|" \
        r"self.?harm\w*|hurt myself|harm myself|don.?t want to (live|be alive|be here)|" \
        r"do not want to (live|be alive|be here)|wish i (wasn.?t|was not|weren.?t|were not) here|" \
        r"wish i (was|were) dead|better off dead|no reason to live|want to die|want to be dead)"

RED_FLAGS = [
    ("pancreatitis", [
        rf"{_SEVERE}.{{0,60}}{_STOMACH}.{{0,40}}{_PAIN}",          # "my stomach pain is really bad"
        rf"{_STOMACH}.{{0,40}}{_PAIN}.{{0,60}}{_SEVERE}",          # "my stomach pain is really bad"
        rf"{_SEVERE}.{{0,60}}{_PAIN}.{{0,40}}{_STOMACH}",          # "constant pain in my abdomen"
        rf"{_STOMACH}.{{0,40}}{_PAIN}.{{0,60}}(back|spine)",       # "belly pain that goes to my back"
        rf"{_PAIN}.{{0,40}}(radiat\w*|spread\w*|go(es|ing)?|shoot\w*|travel\w*).{{0,30}}back",
        rf"{_STOMACH}.{{0,40}}{_PAIN}.{{0,40}}(won.?t|wont|not|never|doesn.?t|does not).{{0,20}}"
        rf"(go away|stop|let up|ease|end)",
    ], "Severe stomach pain that won't go away, especially if it spreads to your back, can be a sign of pancreatitis."),
    ("allergy", [
        rf"{_SWELL}.{{0,40}}{_FACE}",                              # "my lips are swelling"
        rf"{_FACE}.{{0,40}}(swell|swollen|swelling|puffy|puffiness|hives|welts)",
        rf"{_BREATHE}",
        rf"(throat|airway).{{0,30}}(closing|closing up|swelling shut|tight|tightening|swollen shut)",
        rf"(lips?|tongue|face|throat).{{0,30}}(feel|feels|feeling|look|looks|looking).{{0,20}}"
        rf"(big|huge|puffy|swollen|fat|thick)",
        rf"allergic reaction",
    ], "Swelling of the face, lips, tongue or throat, or trouble breathing, can be a serious allergic reaction."),
    ("mood", [
        _MOOD,
    ], "You deserve support right now."),
    ("kidney-dehydration", [
        rf"{_VOMIT}.{{0,40}}(all day|all night|non.?stop|constantly|keep|keeps|kept|since|for (hours|days)|"
        rf"every|again|still|can.?t stop|won.?t stop|over and over)",
        rf"(keep|keeps|kept|been|am|is|are).{{0,20}}{_VOMIT}",     # "I keep throwing up"
        rf"(can.?t|cannot|unable to|hard to|trouble).{{0,30}}keep.{{0,30}}(water|fluids?|anything|food|"
        rf"liquids?|it).{{0,20}}down",
        rf"(haven.?t|have not|not|barely|hardly).{{0,30}}{_URINE}.{{0,30}}(all day|today|since|in \d+|at all|"
        rf"much|yet)",
        rf"(no|not much|very little).{{0,20}}(urine|pee|peeing|output)",
        rf"(dry mouth|no tears|dizzy when i stand|light.?headed when i stand|passing out|fainting|"
        rf"can.?t keep anything down)",
    ], "Not being able to keep fluids down can lead to dehydration and kidney problems."),
    ("thyroid-boxed", [
        rf"(lump|mass|bump|nodule|swelling|swollen).{{0,30}}(neck|throat|thyroid)",
        rf"(neck|throat|thyroid).{{0,30}}(lump|mass|bump|nodule|swelling|swollen)",
        rf"(trouble|difficulty|hard|painful).{{0,20}}swallow",
        rf"(hoarse|hoarseness|voice.{0,20}(change|changed|raspy|gone))",
    ], "A lump or swelling in your neck, trouble swallowing or persistent hoarseness should be checked by a doctor."),
    ("gallbladder", [
        rf"(yellow|yellowish|yellowing).{{0,30}}(skin|eyes?|face|body)",
        rf"(skin|eyes?|face|body).{{0,30}}(yellow|yellowish|yellowing)",
        rf"jaundice",
        rf"clay.?colou?red",
    ], "Yellowing of the skin or eyes, or clay-colored stools, can be a sign of a gallbladder problem."),
]

DOSE_CHANGE = re.compile(
    r"(should|can|could|may)\s+i\s+(increase|decrease|double|raise|lower|up|bump|change|skip|stop|split|"
    r"take (more|less|extra|two|2))|(double|extra|higher|lower|split)\s+(my\s+)?dose|"
    r"micro.?dos|stay on .{0,15}(longer|dose)", re.I)

SYSTEM = """You are GLPal's coach for people taking GLP-1 medicines (semaglutide, tirzepatide).
Answer ONLY using the numbered source passages provided. Rules:
- Cite every factual sentence with the passage number in square brackets, like [1] or [2][3].
- Never use outside knowledge. If the passages do not answer the question, say so plainly and
  suggest asking their prescriber or pharmacist.
- Never tell the user to change, skip, split or stop a dose; never diagnose. Refer those to the prescriber.
- Be warm, plain-spoken and brief: 2-5 short sentences, or a short list if steps help.
- If the user's own log data is given, you may refer to it, but do not cite it as a source."""


def _red_flag(question: str):
    q = question.lower()
    for card_id, patterns, message in RED_FLAGS:
        if any(re.search(p, q) for p in patterns):
            return card_id, message
    return None


def _card(card_id: str) -> dict | None:
    passages, _ = knowledge.load()
    return next((p for p in passages if p["id"] == card_id), None)


def _cite_list(passages: list[dict]) -> list[dict]:
    return [{"n": i + 1, "title": p["title"], "source": p["source_name"], "section": p.get("section", ""),
             "url": p["url"], "quote": p["text"]} for i, p in enumerate(passages)]


def _extractive(passages: list[dict]) -> str:
    """Offline answer: the most relevant passages, each cited. Used in mock mode or if the AI fails.

    Citation numbers follow the position of the passage in the list actually quoted, so filtering
    the list (for example to schedule cards only) can never produce a number that points elsewhere.
    """
    parts = []
    top = passages[0].get("score", 1) if passages else 1
    for i, p in enumerate(passages[:2]):
        if i and p.get("score", top) < top * 0.6:     # only add a 2nd passage if it is clearly relevant
            break
        sentences = re.split(r"(?<=[.!?])\s+", p["text"])
        quote = " ".join(sentences[:3])
        if len(sentences) > 3:
            quote += " …"
        parts.append(f"{quote} [{i + 1}]")
    return "\n\n".join(parts)


def _validate_citations(answer: str, n_sources: int) -> tuple[str, bool]:
    """Drop citation numbers that don't exist; report whether any real citation remains."""
    def fix(m):
        n = int(m.group(1))
        return m.group(0) if 1 <= n <= n_sources else ""
    cleaned = re.sub(r"\[(\d+)\]", fix, answer)
    return cleaned.strip(), bool(re.search(r"\[\d+\]", cleaned))


def answer(question: str, medication: str | None = None, user_context: str = "") -> dict:
    question = (question or "").strip()
    if not question:
        return {"answer": "Ask me anything about your GLP-1 medicine, side effects or nutrition.",
                "citations": [], "kind": "empty", "disclaimer": DISCLAIMER}

    flag = _red_flag(question)
    if flag:
        card_id, message = flag
        card = _card(card_id)
        cites = _cite_list([card]) if card else []
        extra = (" If you are in crisis, call or text 988 now (Suicide and Crisis Lifeline, US and Canada), "
                 "or go to the nearest emergency department." if card_id == "mood" else
                 " Please contact your healthcare provider now, or go to urgent care or the emergency "
                 "department if it is severe. If it's an emergency, call 911.")
        body = message + extra
        if card:
            body += f"\n\nWhat the official label says: {card['text']} [1]"
        return {"answer": body, "citations": cites, "kind": "urgent", "disclaimer": DISCLAIMER}

    passages = knowledge.search(question, k=4, medication=medication)

    if DOSE_CHANGE.search(question):
        sched = [p for p in passages if "escalation" in p["id"] or "missed" in p["id"]][:2]
        text = ("I can't advise changing, skipping or splitting a dose. That decision belongs to your "
                "prescriber, who knows your health history. Please message or call them, or ask your pharmacist.")
        if sched:
            text += "\n\nFor reference, here is the official schedule: " + _extractive(sched)
        return {"answer": text, "citations": _cite_list(sched), "kind": "refer", "disclaimer": DISCLAIMER}
    if not passages:
        return {"answer": "I couldn't find this in GLPal's trusted sources, so I won't guess. "
                          "Your prescriber or pharmacist is the best person to ask.",
                "citations": [], "kind": "not_found", "disclaimer": DISCLAIMER}

    unknown = knowledge.unknown_terms(question)
    numbered = "\n\n".join(f"[{i + 1}] {p['title']} ({p['source_name']}, {p.get('section', '')}):\n{p['text']}"
                           for i, p in enumerate(passages))
    user = f"Source passages:\n{numbered}\n\n"
    if user_context:
        user += f"The user's own recent log (not a source):\n{user_context}\n\n"
    user += f"Question: {question}"
    if unknown:
        # Don't refuse the question (uncommon words are often legitimate), but tell the model the
        # library is silent on them so it can say so instead of stretching a passage to fit.
        user += (f"\n\nThe sources do not mention: {', '.join(unknown)}. "
                 "If the question depends on them, say the sources do not cover it.")

    mode = llm.provider()
    text = ""
    try:
        text = llm.chat(SYSTEM, user)
    except llm.LLMError:
        mode = "offline-fallback"
    ok = False
    if text:
        text, ok = _validate_citations(text, len(passages))
    if not ok and unknown and len(unknown) >= 1 and not text:
        # Offline mode can't judge relevance like an AI can: if the question is about something the
        # library never mentions, say so rather than returning a loosely related passage.
        return {"answer": f"GLPal's trusted sources don't cover {', '.join(unknown)}, so I won't guess. "
                          "Please ask your prescriber or pharmacist.",
                "citations": [], "kind": "not_found", "mode": mode, "disclaimer": DISCLAIMER}
    if not ok:                         # no AI, AI failed, or AI ignored the citation rule
        text = _extractive(passages)
        mode = "extractive" if mode == "mock" else (mode if mode == "offline-fallback" else f"{mode}+extractive")
    used = sorted({int(n) for n in re.findall(r"\[(\d+)\]", text)})
    cites = [c for c in _cite_list(passages) if c["n"] in used]
    return {"answer": text, "citations": cites, "kind": "answer", "mode": mode, "disclaimer": DISCLAIMER}
