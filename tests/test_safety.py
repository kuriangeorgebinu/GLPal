"""Safety-critical tests: red-flag triage, citation validation and retrieval relevance.

Run with:  python -m pytest -q   (offline mode and a temporary database come from tests/conftest.py)
"""
import pytest

from app import coach, knowledge

# Real-world phrasings of each emergency, with the card the urgent answer must cite.
URGENT_CASES = [
    # pancreatitis
    ("my stomach pain is really bad and won't go away", "pancreatitis"),
    ("I have severe abdominal pain", "pancreatitis"),
    ("my belly hurts so bad and it goes to my back", "pancreatitis"),
    ("my stomach pain is severe", "pancreatitis"),
    ("my tummy is really sore and it won't stop", "pancreatitis"),
    # allergy
    ("my lips are swelling", "allergy"),
    ("my throat feels like it's closing", "allergy"),
    ("my face is puffy and swollen", "allergy"),
    ("it's hard to breathe", "allergy"),
    ("I'm short of breath", "allergy"),
    ("my tongue is swollen", "allergy"),
    ("I think I'm having an allergic reaction", "allergy"),
    # mood
    ("I don't want to be here anymore", "mood"),
    ("I wish I wasn't here", "mood"),
    ("I want to kill myself", "mood"),
    ("I feel suicidal", "mood"),
    # kidney / dehydration
    ("I keep throwing up", "kidney-dehydration"),
    ("I've been vomiting since last night", "kidney-dehydration"),
    ("I haven't peed all day", "kidney-dehydration"),
    ("I can't keep water down", "kidney-dehydration"),
    ("I can't keep anything down", "kidney-dehydration"),
    # thyroid boxed warning
    ("there is a lump in my neck", "thyroid-boxed"),
    ("I have trouble swallowing", "thyroid-boxed"),
    ("my voice is hoarse all the time", "thyroid-boxed"),
    # gallbladder
    ("my eyes look yellow", "gallbladder"),
    ("yellowish skin", "gallbladder"),
    ("my skin is turning yellow", "gallbladder"),
]

# Ordinary questions that must NOT be triaged as an emergency.
BENIGN_CASES = [
    "how do I deal with nausea?",
    "where should I inject?",
    "how much protein should I eat?",
    "my stomach is a bit upset after lunch",
    "what does yellow pen cap mean",
]

# Questions ABOUT a symptom are not reports OF a symptom. A red flag is the user telling us about
# their own body, so these must stay ordinary answers (round 2: fix false alarms).
NEGATIVE_CASES = [
    "Is vomiting a common side effect of Wegovy?",
    "Am I going to throw up when I go up to 1 mg?",
    "Is nausea or vomiting worse in the first week?",
    "I have bad stomach cramps after eating fried food",
    "My stomach hurts a little, not bad, after lunch",
    "is nausea normal",
    "how long does vomiting last",
    "can I take something for stomach cramps",
    "my stomach feels a bit off",
    "does the shot make you throw up",
    "how do I deal with nausea?",
    "what should I eat when my stomach feels bad?",
    "is constipation bad on Mounjaro?",
    "my belly is sore at the injection site",
    "is it bad if I vomit once?",
]

# A first-person report that does not meet the urgent bar: answer normally, but carry a caution line.
CAUTION_CASES = [
    "my stomach hurts",
    "I threw up once this morning",
]

# ACCEPTED over-trigger: "I can't breathe easily when I exercise" matches the allergy pattern and
# returns the urgent message. We accept this on purpose — a false urgent message is far safer than a
# missed anaphylaxis — and this test documents the trade-off so nobody "fixes" it by accident.
ACCEPTED_OVER_TRIGGER = "I can't breathe easily when I exercise"


@pytest.mark.parametrize("question,card", URGENT_CASES)
def test_red_flag_phrasings_are_urgent(question, card):
    r = coach.answer(question)
    assert r["kind"] == "urgent", f"{question!r} should be urgent, got {r['kind']}"
    assert r["citations"], f"{question!r} should cite the {card} card"
    assert r["citations"][0]["n"] == 1
    assert card in r["answer"].lower() or r["citations"][0]["title"], question


@pytest.mark.parametrize("question,card", URGENT_CASES)
def test_red_flag_cites_the_right_card(question, card):
    r = coach.answer(question)
    assert r["citations"][0]["quote"] == coach._card(card)["text"]


@pytest.mark.parametrize("question", BENIGN_CASES)
def test_benign_questions_are_not_urgent(question):
    assert coach.answer(question)["kind"] != "urgent", f"{question!r} should not be urgent"


@pytest.mark.parametrize("question", NEGATIVE_CASES)
def test_questions_about_symptoms_are_not_urgent(question):
    assert coach.answer(question)["kind"] != "urgent", f"{question!r} should not be urgent"


@pytest.mark.parametrize("question", CAUTION_CASES)
def test_mild_first_person_report_gets_a_caution(question):
    r = coach.answer(question)
    assert r["kind"] in ("answer", "not_found"), f"{question!r} should be a normal answer, got {r['kind']}"
    assert r.get("caution"), f"{question!r} should carry a caution line"
    assert "urgent care" in r["caution"]


def test_hedged_stomach_pain_is_not_urgent_and_has_no_caution():
    r = coach.answer("My stomach hurts a little, not bad, after lunch")
    assert r["kind"] != "urgent"
    assert not r.get("caution")


def test_accepted_over_trigger_is_documented():
    assert coach.answer(ACCEPTED_OVER_TRIGGER)["kind"] == "urgent"


def test_every_category_has_patterns_and_a_card():
    card_ids = {p["id"] for p in knowledge.load()[0]}
    for category, patterns, message in coach.RED_FLAGS:
        assert category in coach.RED_FLAG_CATEGORIES
        assert patterns, f"{category} has no patterns"
        assert message
        assert category in card_ids, f"{category} is not a card id in the knowledge base"
    assert tuple(c for c, _, _ in coach.RED_FLAGS) == coach.RED_FLAG_CATEGORIES


def test_validate_citations_drops_invented_numbers():
    text, ok = coach._validate_citations("Take the missed dose [7] within 5 days [1].", 2)
    assert ok and "[7]" not in text and "[1]" in text
    text, ok = coach._validate_citations("Only invented [9].", 2)
    assert not ok and "[9]" not in text


def test_extractive_numbering_after_filtering():
    passages = knowledge.search("I missed my wegovy shot", medication="wegovy")
    sched = [p for p in passages if "escalation" in p["id"] or "missed" in p["id"]][:2]
    assert sched, "expected at least one schedule card"
    text = coach._extractive(sched)
    assert "[1]" in text
    # The first quoted passage must be the first passage in the filtered list, not the original list.
    assert sched[0]["text"].split(".")[0][:20] in text


def test_knowledge_search_nonsense_returns_nothing():
    assert knowledge.search("zzzz qqqq flibbertigibbet") == []
    assert knowledge.search("") == []


def test_knowledge_search_requires_a_real_content_word():
    # "the" and "of" are stopwords; a query of only filler must not return passages.
    assert knowledge.search("the of and to") == []


# --- Small talk -------------------------------------------------------------------------------

@pytest.mark.parametrize("msg", ["Hi", "hello!", "Hey there", "good morning", "what can you do?", "help"])
def test_greetings_get_a_friendly_intro(msg):
    r = coach.answer(msg)
    assert r["kind"] == "chat" and "GLPal's coach" in r["answer"] and not r["citations"]


def test_thanks_gets_a_short_reply():
    assert coach.answer("thanks!")["kind"] == "chat"


@pytest.mark.parametrize("msg", ["hi, my lips are swelling", "hello I keep throwing up and can't keep water down"])
def test_greeting_never_hides_a_red_flag(msg):
    assert coach.answer(msg)["kind"] == "urgent"


def test_greeting_with_a_question_still_gets_an_answer():
    assert coach.answer("hi, how much protein should I eat?")["kind"] == "answer"
