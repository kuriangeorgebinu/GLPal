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

RED_FLAGS = [
    (r"(severe|really bad|intense|unbearable|won.?t go away|constant).{0,40}(stomach|abdominal|belly|abdomen).{0,20}pain"
     r"|pain.{0,30}(radiat|spread|go(es|ing)?).{0,20}back", "pancreatitis",
     "Severe stomach pain that won't go away, especially if it spreads to your back, can be a sign of pancreatitis."),
    (r"(swell|swollen).{0,30}(face|lips?|tongue|throat)|can.?t breathe|trouble breathing|difficulty breathing|anaphyla",
     "allergy", "Swelling of the face, lips, tongue or throat, or trouble breathing, can be a serious allergic reaction."),
    (r"suicid|kill myself|end my life|self.?harm|don.?t want to (live|be alive)", "mood",
     "You deserve support right now."),
    (r"can.?t keep (any )?(water|fluids|anything) down|vomit(ing)? (all day|for \d+|non.?stop)|no urine|not peeing",
     "kidney-dehydration", "Not being able to keep fluids down can lead to dehydration and kidney problems."),
    (r"lump.{0,20}neck|neck.{0,20}(lump|swelling|mass)|trouble swallowing|hoarse", "thyroid-boxed",
     "A lump or swelling in your neck, trouble swallowing or persistent hoarseness should be checked by a doctor."),
    (r"yellow (skin|eyes)|jaundice|clay.?colou?red", "gallbladder",
     "Yellowing of the skin or eyes, or clay-colored stools, can be a sign of a gallbladder problem."),
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
    for pattern, card_id, message in RED_FLAGS:
        if re.search(pattern, q):
            return card_id, message
    return None


def _card(card_id: str) -> dict | None:
    passages, _ = knowledge.load()
    return next((p for p in passages if p["id"] == card_id), None)


def _cite_list(passages: list[dict]) -> list[dict]:
    return [{"n": i + 1, "title": p["title"], "source": p["source_name"], "section": p.get("section", ""),
             "url": p["url"], "quote": p["text"]} for i, p in enumerate(passages)]


def _extractive(passages: list[dict]) -> str:
    """Offline answer: the most relevant passages, each cited. Used in mock mode or if the AI fails."""
    parts = []
    top = passages[0].get("score", 1) if passages else 1
    for i, p in enumerate(passages[:2]):
        if i and p.get("score", top) < top * 0.6:     # only add a 2nd passage if it is clearly relevant
            break
        sentences = re.split(r"(?<=[.!?])\s+", p["text"])
        parts.append(" ".join(sentences[:3]) + f" [{i + 1}]")
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
