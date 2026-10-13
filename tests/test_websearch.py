"""Live trusted-site search: response assembly, routing and safety. No network: the API is faked."""
import pytest

from app import coach, llm, websearch

SEARCH_RESPONSE = {
    "stop_reason": "end_turn",
    "content": [
        {"type": "text", "text": "Let me look that up."},
        {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {"query": "Wegovy alcohol"}},
        {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1", "content": []},
        {"type": "text", "text": "Alcohol can affect blood sugar", "citations": [
            {"type": "web_search_result_location", "url": "https://www.fda.gov/label-x", "title": "Wegovy label",
             "cited_text": "Alcohol may increase the risk of low blood sugar"}]},
        {"type": "text", "text": ", so ask your prescriber how much is safe for you", "citations": [
            {"type": "web_search_result_location", "url": "https://medlineplus.gov/druginfo/x.html",
             "title": "Semaglutide", "cited_text": "Talk to your doctor about drinking alcohol"}]},
        {"type": "text", "text": "."},
    ],
}


def test_assemble_drops_preamble_and_numbers_citations():
    text, cites, searches = websearch._assemble(SEARCH_RESPONSE["content"])
    assert "Let me look" not in text
    assert text.startswith("Alcohol can affect blood sugar [1]") and "[2]" in text
    assert [c["n"] for c in cites] == [1, 2] and cites[0]["source"] == "fda.gov" and searches == 1
    assert cites[1]["quote"].startswith("Talk to your doctor")


def test_request_is_locked_to_trusted_domains(monkeypatch):
    sent = {}

    class R:
        status_code = 200

        def json(self):
            return SEARCH_RESPONSE

    def fake_post(url, **kw):
        sent.update(kw["json"])
        return R()

    monkeypatch.setattr(websearch.httpx, "post", fake_post)
    monkeypatch.setattr(websearch, "enabled", lambda: True)
    out = websearch.answer("can I drink alcohol?", "wegovy", "", [])
    tool = sent["tools"][0]
    assert tool["type"].startswith("web_search_") and tool["allowed_domains"] == websearch.TRUSTED_DOMAINS
    assert tool["max_uses"] <= 3 and out["citations"]


@pytest.fixture
def live(monkeypatch):
    holder = {"result": {"text": "Alcohol can affect blood sugar [1].", "searches": 1,
                         "citations": [{"n": 1, "title": "Wegovy label", "source": "fda.gov", "section": "Live search",
                                        "url": "https://www.fda.gov/x", "quote": "..."}]}}
    calls = []

    def fake(q, med, ctx, hist):
        calls.append(q)
        return holder["result"]
    monkeypatch.setattr(websearch, "answer", fake)
    monkeypatch.setattr(llm, "provider", lambda: "anthropic")
    monkeypatch.setattr(llm, "chat", lambda *a, **k: "Happy to help!")
    return holder, calls


def test_medical_question_uses_live_search(live):
    holder, calls = live
    r = coach.answer("can I drink alcohol on Wegovy?")
    assert r["kind"] == "answer" and r["mode"] == "anthropic+web" and r["citations"][0]["source"] == "fda.gov"


def test_red_flag_and_dose_guard_run_before_search(live):
    holder, calls = live
    assert coach.answer("my lips are swelling")["kind"] == "urgent"
    assert coach.answer("should I double my dose?")["kind"] == "refer"
    assert calls == []


def test_greeting_never_triggers_a_search(live):
    holder, calls = live
    assert coach.answer("hi")["kind"] == "chat" and calls == []


def test_uncited_search_reply_is_never_shown_as_medical_text(live):
    holder, calls = live
    holder["result"] = {"text": "You can probably have a glass of wine.", "citations": [], "searches": 1}
    r = coach.answer("can I drink alcohol on Wegovy?")
    assert "wine" not in r["answer"] and not r["citations"]


def test_search_unavailable_falls_back_to_local_library(monkeypatch):
    monkeypatch.setattr(websearch, "answer", lambda *a: None)
    r = coach.answer("How do I deal with nausea?")       # mock provider: local cited library
    assert r["kind"] == "answer" and r["citations"]
