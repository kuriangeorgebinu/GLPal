"""Conversational coach: casual chat goes to the AI, medical answers still need sources, safety first.

A fake AI provider is patched in, so these tests run offline and check exactly what is sent and returned.
"""
import pytest

from app import coach, llm


class FakeAI:
    def __init__(self, reply="Hey! Nice to hear from you. How are you feeling today?"):
        self.reply, self.calls = reply, []

    def __call__(self, system, user, **kw):
        self.calls.append({"system": system, "user": user})
        return self.reply


@pytest.fixture
def ai(monkeypatch):
    fake = FakeAI()
    monkeypatch.setattr(llm, "provider", lambda: "anthropic")
    monkeypatch.setattr(llm, "chat", fake)
    return fake


def test_hi_gets_a_casual_ai_reply(ai):
    r = coach.answer("hi")
    assert r["kind"] == "chat" and r["answer"] == ai.reply and not r["citations"]
    assert ai.calls and ai.calls[0]["system"] == coach.CHAT_SYSTEM


def test_casual_feelings_are_chat_not_a_refusal(ai):
    r = coach.answer("I'm having a rough day honestly")
    assert r["kind"] == "chat" and "couldn't find" not in r["answer"]


def test_history_is_passed_to_the_ai(ai):
    coach.answer("how's it going?", history=[{"role": "user", "text": "hi"},
                                             {"role": "assistant", "text": "Hi there!"}])
    assert "Conversation so far" in ai.calls[0]["user"] and "Hi there!" in ai.calls[0]["user"]


def test_chat_reply_with_dosing_is_blocked(monkeypatch):
    monkeypatch.setattr(llm, "provider", lambda: "anthropic")
    monkeypatch.setattr(llm, "chat", FakeAI("Sure, just take 2 mg instead this week!"))
    r = coach.answer("hey, how are you?")
    assert "2 mg" not in r["answer"] and r["kind"] == "chat"


def test_medical_question_still_uses_sources(ai):
    ai.reply = "Eat small meals every 3-4 hours [1]."
    r = coach.answer("How do I deal with nausea?")
    assert r["kind"] == "answer" and r["citations"]
    assert ai.calls[0]["system"] == coach.SYSTEM


def test_red_flag_beats_chat(ai):
    r = coach.answer("hey, my lips are swelling")
    assert r["kind"] == "urgent" and not ai.calls


def test_dose_change_beats_chat(ai):
    assert coach.answer("hi, should I double my dose?")["kind"] == "refer"


def test_follow_up_uses_previous_question(ai):
    ai.reply = "The pen can stay unrefrigerated for a limited time [1]."
    r = coach.answer("and what about Mounjaro?",
                     history=[{"role": "user", "text": "How do I store my Wegovy pen?"},
                              {"role": "assistant", "text": "In the fridge [1]."}])
    assert r["kind"] == "answer"


def test_dosing_in_non_greeting_chat_gets_friendly_guard(monkeypatch):
    monkeypatch.setattr(llm, "provider", lambda: "anthropic")
    monkeypatch.setattr(llm, "chat", FakeAI("You should double your dose, honestly."))
    r = coach.answer("I'm having a rough day honestly")
    assert r["answer"] == coach.GUARDED and r["kind"] == "chat"


@pytest.mark.parametrize("q", ["how's it going?", "what's up", "is it normal?"])
def test_filler_only_messages_never_pull_in_a_source(q):
    from app import knowledge
    assert knowledge.search(q) == []


def test_casual_message_that_hits_a_source_still_gets_chat(monkeypatch):
    # The AI marks a casual message with [CHAT]; it must not be replaced by a quoted passage.
    monkeypatch.setattr(llm, "provider", lambda: "anthropic")
    monkeypatch.setattr(llm, "chat", FakeAI("[CHAT] Aw, thank you! I'm glad I could help."))
    r = coach.answer("you're doing a great job with the pregnancy storage stuff")
    assert r["kind"] == "chat" and r["answer"].startswith("Aw, thank you") and not r["citations"]


def test_chat_marker_cannot_smuggle_dosing(monkeypatch):
    monkeypatch.setattr(llm, "provider", lambda: "anthropic")
    monkeypatch.setattr(llm, "chat", FakeAI("[CHAT] Just take 1 mg more, you'll be fine."))
    r = coach.answer("how do I store my pen?")
    assert r["answer"] == coach.GUARDED


@pytest.mark.parametrize("q", ["thanks, you're great", "thank you so much!", "thx coach"])
def test_short_thanks_variants_are_small_talk(q):
    assert coach.answer(q)["kind"] == "chat"


def test_uncited_ai_reply_becomes_chat_not_a_random_quote(monkeypatch):
    replies = iter(["How about something light like a veggie omelette?",       # source mode, no citations
                    "Something light sounds good, maybe an omelette or a soup!"])  # chat mode
    monkeypatch.setattr(llm, "provider", lambda: "anthropic")
    monkeypatch.setattr(llm, "chat", lambda *a, **k: next(replies))
    r = coach.answer("what should I eat for dinner with eggs and protein")
    assert r["kind"] == "chat" and "omelette" in r["answer"] and not r["citations"]


def test_dinner_small_talk_does_not_match_contraception():
    from app import knowledge
    assert all(p["id"] != "contraception-tirzepatide" for p in knowledge.search("lol ok what should I make for dinner"))
