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
#
# A red flag is a REPORT about the user, not a word in a question. Bare "bad", "sore" and
# "cramp/cramps/cramping" are deliberately NOT severity words: "is constipation bad on Mounjaro?"
# and "my belly is sore at the injection site" are ordinary questions, not emergencies. The urgent
# bar is a strong severity word ("severe", "really bad", "unbearable", "won't go away", ...).
_SEVERE = r"(severe|severely|really bad|very bad|so bad|intense|unbearable|extreme|terrible|awful|" \
          r"won.?t go away|wont go away|not going away|doesn.?t go away|does not go away|constant|constantly|" \
          r"getting worse|getting bad|really hurts|really hurting)"
_STOMACH = r"(stomach|abdominal|abdomen|belly|tummy|gut)"
_PAIN = r"(pain|pains|painful|hurt|hurts|hurting|ache|aching)"
# First-person frame: a red flag is the user reporting their own symptom, not asking about one.
_FIRST_PERSON = r"\b(?:i|i'm|im|i've|ive|me|my)\b"
# Hedges and negations: "my stomach hurts a little, not bad" must not raise the pancreatitis flag.
_HEDGE = r"(not bad|a little|a bit|slight|slightly|mild|mildly|no big deal|not severe|not that bad)"
# Persistence / inability markers for dehydration: one throw-up is not an emergency, "I keep throwing
# up" or "I've been vomiting since last night" is.
_PERSIST = r"(keep|keeps|kept|can.?t keep|cannot keep|since|all day|all night|for hours|for days|" \
           r"non.?stop|won.?t stop|wont stop|over and over|again and again|constantly|still|every)"
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
        # Every pancreatitis pattern needs a first-person frame, so "is vomiting a common side effect
        # of Wegovy?" and "can I take something for stomach cramps" stay ordinary questions.
        rf"{_FIRST_PERSON}.{{0,80}}{_SEVERE}.{{0,60}}{_STOMACH}.{{0,40}}{_PAIN}",   # "my stomach pain is really bad"
        rf"{_FIRST_PERSON}.{{0,80}}{_STOMACH}.{{0,40}}{_PAIN}.{{0,60}}{_SEVERE}",   # "my stomach pain is severe"
        rf"{_FIRST_PERSON}.{{0,80}}{_SEVERE}.{{0,60}}{_PAIN}.{{0,40}}{_STOMACH}",   # "constant pain in my abdomen"
        rf"{_FIRST_PERSON}.{{0,80}}{_STOMACH}.{{0,40}}{_PAIN}.{{0,60}}(back|spine)",  # "belly pain that goes to my back"
        rf"{_FIRST_PERSON}.{{0,80}}{_PAIN}.{{0,40}}(radiat\w*|spread\w*|go(es|ing)?|shoot\w*|travel\w*).{{0,30}}back",
        # Persistent pain, soreness or cramping that won't stop ("my tummy is really sore and it won't stop").
        # "sore"/"cramps" alone are too common to flag; they count only with a won't-stop marker.
        rf"{_FIRST_PERSON}.{{0,80}}{_STOMACH}.{{0,40}}(?:{_PAIN}|sore\w*|cramp\w*).{{0,60}}"
        rf"(won.?t|wont|not|never|doesn.?t|does not|can.?t make it).{{0,20}}(go away|stop|let up|ease|end)",
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
        # First-person report + a persistence/inability marker. "I threw up once this morning" is not
        # an emergency; "I keep throwing up" and "I've been vomiting since last night" are.
        rf"{_FIRST_PERSON}.{{0,60}}{_VOMIT}.{{0,40}}{_PERSIST}",
        rf"{_FIRST_PERSON}.{{0,60}}{_PERSIST}.{{0,40}}{_VOMIT}",   # "I keep throwing up"
        rf"{_FIRST_PERSON}.{{0,60}}(can.?t|cannot|unable to|hard to|trouble).{{0,30}}keep.{{0,30}}"
        rf"(water|fluids?|anything|food|liquids?|it).{{0,20}}down",
        rf"{_FIRST_PERSON}.{{0,60}}(haven.?t|have not|not|barely|hardly).{{0,30}}{_URINE}.{{0,30}}"
        rf"(all day|today|since|in \d+|at all|much|yet)",
        rf"{_FIRST_PERSON}.{{0,60}}(no|not much|very little).{{0,20}}(urine|pee|peeing|output)",
        rf"{_FIRST_PERSON}.{{0,60}}(dry mouth|no tears|dizzy when i stand|light.?headed when i stand|"
        rf"passing out|fainting|can.?t keep anything down)",
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
- This is a conversation: you may greet the user, acknowledge feelings and reply naturally in your own
  words, without citations, as long as those sentences contain no medical facts.
- Be warm, plain-spoken and brief: 2-5 short sentences, or a short list if steps help.
- If the user's own log data is given, you may refer to it, but do not cite it as a source.
- Use the earlier conversation only to understand follow-up questions; it is not a source. Answer only
  the current message; never comment on, compare with or "correct" your earlier replies.
- If the current message is casual (a greeting, thanks, a feeling) and needs no medical facts, reply with
  [CHAT] followed by a short, friendly reply, and nothing else."""

CHAT_SYSTEM = """You are GLPal's coach, a warm, friendly companion inside an app for people taking GLP-1
medicines (Wegovy, Ozempic, Mounjaro, Zepbound). Chat naturally and casually, like a supportive friend:
greet people back, make small talk, encourage them, and help them use the app (logging doses, meals, side
effects, weight, the doctor summary).
Strict rules:
- Do NOT state medical facts: no doses, schedules, side-effect lists, drug interactions, diagnoses or
  treatment advice. If they ask a medical question, say kindly that it isn't covered by GLPal's trusted
  sources and suggest their prescriber or pharmacist, or invite them to ask about doses, side effects,
  nausea, protein or storage, which you can answer from the FDA labels.
- Never tell anyone to change, skip, split or stop a dose.
- Keep replies short: 1-3 sentences unless they clearly want more. No citations, no headings."""

# A casual reply must never sneak in dosing facts; if it does, it is replaced.
_CHAT_MEDICAL = re.compile(r"\b\d+(\.\d+)?\s?(mg|milligrams?|mcg|units?)\b|\b(increase|decrease|double|skip|"
                           r"stop|split) (your|the) (dose|shot|injection|medication)\b", re.I)


def _red_flag(question: str):
    q = question.lower()
    for card_id, patterns, message in RED_FLAGS:
        if any(re.search(p, q) for p in patterns):
            return card_id, message
    return None


# Third state: a first-person GI report that does not meet the urgent bar ("my stomach hurts",
# "I threw up once this morning"). The answer is normal, but it carries a caution line so the user
# knows what would make it an emergency.
CAUTION = ("If this becomes severe, won't go away, spreads to your back, or you can't keep fluids down, "
           "contact your healthcare provider or go to urgent care.")
_GI_REPORT = re.compile(rf"{_FIRST_PERSON}.{{0,60}}(?:{_STOMACH}.{{0,40}}{_PAIN}|{_VOMIT})")


def _caution(question: str) -> str | None:
    """A caution line for a first-person stomach/vomiting report that is not (yet) an emergency."""
    q = question.lower()
    if re.search(_HEDGE, q):
        return None
    return CAUTION if _GI_REPORT.search(q) else None


# Small talk: greetings, thanks and "what can you do?" get a friendly reply instead of a
# "not in my sources" refusal. Only whole short messages match, so real questions still go
# through the red-flag check and retrieval.
_GREETING = re.compile(r"^\s*((hi+|hey+|hello+|hiya|yo|good (morning|afternoon|evening)|greetings|howdy)[,!.]?\s*)?"
                       r"((hi+|hey+|hello+|hiya|yo|good (morning|afternoon|evening)|greetings|howdy)"
                       r"|how are you( doing)?( today)?|how.?s it going|what.?s up|sup)"
                       r"( there| glpal| coach)?\s*[!.?]*\s*$", re.I)
_THANKS = re.compile(r"^\s*((thanks?|thank you|thx|ty|cheers)\b[^?]{0,40}|(great|ok(ay)?|cool|perfect|got it)"
                     r"( (so much|a lot|very much))?\s*[!.]*)\s*$", re.I)
_HELP = re.compile(r"^\s*(help|what can you do|what do you do|how does this work|who are you|"
                   r"what (can|should) i ask( you)?)\s*[!.?]*\s*$", re.I)

INTRO = ("Hi! I'm GLPal's coach. I answer questions about Wegovy, Ozempic, Mounjaro and Zepbound using only "
         "trusted sources (the FDA labels and a 2025 nutrition advisory), and I show you where each answer comes "
         "from.\n\nYou could ask me things like:\n- I missed my shot 3 days ago, what now?\n"
         "- How much protein should I eat?\n- How do I deal with nausea?\n- How do I store my pen?\n\n"
         "I can't advise changing your dose; that's for your prescriber.")


def _small_talk(question: str) -> str | None:
    if _GREETING.match(question) or _HELP.match(question):
        return INTRO
    if _THANKS.match(question):
        return "You're welcome! Ask me anything else about your medicine, side effects or eating."
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
            quote += " â€¦"
        parts.append(f"{quote} [{i + 1}]")
    return "\n\n".join(parts)


def _validate_citations(answer: str, n_sources: int) -> tuple[str, bool]:
    """Drop citation numbers that don't exist; report whether any real citation remains."""
    def fix(m):
        n = int(m.group(1))
        return m.group(0) if 1 <= n <= n_sources else ""
    cleaned = re.sub(r"\[(\d+)\]", fix, answer)
    return cleaned.strip(), bool(re.search(r"\[\d+\]", cleaned))


NOT_FOUND = ("I couldn't find this in GLPal's trusted sources, so I won't guess. "
             "Your prescriber or pharmacist is the best person to ask.")
GUARDED = ("I'm here to help! I can't give dosing advice in a chat, but ask me about your medicine, side effects "
           "or eating and I'll answer from GLPal's trusted sources. For dose questions, your prescriber is the best person.")


def _clean_history(history) -> list[dict]:
    """Last few turns of the conversation, trimmed. Only used for context, never as a source."""
    out = []
    for turn in (history or [])[-8:]:
        role = "user" if str(turn.get("role", "")).lower() == "user" else "assistant"
        text = re.sub(r"\s+", " ", str(turn.get("text", ""))).strip()[:600]
        if text:
            out.append({"role": role, "text": text})
    return out


def _transcript(history: list[dict]) -> str:
    return "\n".join(f"{'User' if t['role'] == 'user' else 'Coach'}: {t['text']}" for t in history)


def _chat_reply(question: str, history: list[dict], user_context: str) -> tuple[str, str]:
    """Casual conversation with the AI (no sources needed because no medical facts are allowed)."""
    mode = llm.provider()
    if mode == "mock":
        return (_small_talk(question) or NOT_FOUND), "offline"
    user = ""
    if history:
        user += f"Conversation so far:\n{_transcript(history)}\n\n"
    if user_context:
        user += f"The user's own recent log (you may mention it gently):\n{user_context}\n\n"
    user += f"User: {question}"
    try:
        text = llm.chat(CHAT_SYSTEM, user, max_tokens=600).strip()
    except llm.LLMError:
        return (_small_talk(question) or NOT_FOUND), "offline-fallback"
    if not text:
        return (_small_talk(question) or NOT_FOUND), f"{mode}+empty"
    if _CHAT_MEDICAL.search(text):     # casual replies may never carry dosing; swap in a safe friendly line
        return GUARDED, f"{mode}+guarded"
    return text, mode


def answer(question: str, medication: str | None = None, user_context: str = "",
           history: list[dict] | None = None) -> dict:
    question = (question or "").strip()
    if not question:
        return {"answer": "Ask me anything about your GLP-1 medicine, side effects or nutrition.",
                "citations": [], "kind": "empty", "disclaimer": DISCLAIMER}
    history = _clean_history(history)

    # 1. Emergencies first, always, even inside small talk.
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

    # Short follow-ups ("what about Mounjaro?") are searched together with the previous question.
    query = question
    last_user = next((t["text"] for t in reversed(history) if t["role"] == "user"), "")
    if last_user and len(question.split()) <= 8:
        query = f"{last_user} {question}"
    passages = knowledge.search(question, k=4, medication=medication) or \
        (knowledge.search(query, k=4, medication=medication) if query != question else [])
    caution = _caution(question)

    def _out(d: dict) -> dict:
        if caution:
            d["caution"] = caution
        d["disclaimer"] = DISCLAIMER
        return d

    # 2. Never advise on dose changes.
    if DOSE_CHANGE.search(question):
        sched = [p for p in passages if "escalation" in p["id"] or "missed" in p["id"]][:2]
        text = ("I can't advise changing, skipping or splitting a dose. That decision belongs to your "
                "prescriber, who knows your health history. Please message or call them, or ask your pharmacist.")
        if sched:
            text += "\n\nFor reference, here is the official schedule: " + _extractive(sched)
        return _out({"answer": text, "citations": _cite_list(sched), "kind": "refer"})

    # 3. Greetings, thanks and anything the sources don't cover: a casual conversation.
    if _small_talk(question) or not passages:
        text, mode = _chat_reply(question, history, user_context)
        kind = "chat" if text != NOT_FOUND else "not_found"
        return _out({"answer": text, "citations": [], "kind": kind, "mode": mode})

    # 4. A medical question with relevant sources: a cited answer.
    unknown = knowledge.unknown_terms(question)
    numbered = "\n\n".join(f"[{i + 1}] {p['title']} ({p['source_name']}, {p.get('section', '')}):\n{p['text']}"
                           for i, p in enumerate(passages))
    user = ""
    if history:
        user += f"Earlier conversation (context only, not a source):\n{_transcript(history)}\n\n"
    user += f"Source passages:\n{numbered}\n\n"
    if medication:
        user += f"The user takes: {medication}. Focus on that medicine unless they ask about another.\n\n"
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
    if text.lstrip().startswith("[CHAT]"):
        reply = text.lstrip()[len("[CHAT]"):].strip()
        if reply and not _CHAT_MEDICAL.search(reply) and not re.search(r"\[\d+\]", reply):
            return _out({"answer": reply, "citations": [], "kind": "chat", "mode": mode})
        return _out({"answer": GUARDED, "citations": [], "kind": "chat", "mode": f"{mode}+guarded"})
    ok = False
    if text:
        text, ok = _validate_citations(text, len(passages))
    if not ok and unknown and not text:
        # Offline mode can't judge relevance like an AI can: if the question is about something the
        # library never mentions, say so rather than returning a loosely related passage.
        return _out({"answer": f"GLPal's trusted sources don't cover {', '.join(unknown)}, so I won't guess. "
                               "Please ask your prescriber or pharmacist.",
                     "citations": [], "kind": "not_found", "mode": mode})
    if not ok and text and mode not in ("mock", "offline-fallback"):
        # The AI answered without citing anything, so the sources weren't really relevant (e.g. "what
        # should I make for dinner?"). Reply as casual chat rather than quoting an unrelated passage.
        reply, chat_mode = _chat_reply(question, history, user_context)
        kind = "chat" if reply != NOT_FOUND else "not_found"
        return _out({"answer": reply, "citations": [], "kind": kind, "mode": f"{chat_mode}+uncited"})
    if not ok:                         # no AI, or the AI failed: quote the best cited passage
        text = _extractive(passages)
        mode = "extractive" if mode == "mock" else (mode if mode == "offline-fallback" else f"{mode}+extractive")
    used = sorted({int(n) for n in re.findall(r"\[(\d+)\]", text)})
    cites = [c for c in _cite_list(passages) if c["n"] in used]
    return _out({"answer": text, "citations": cites, "kind": "answer", "mode": mode})
