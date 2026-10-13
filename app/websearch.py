"""Live, cited answers: Claude searches ONLY a fixed list of trusted medical websites.

Uses Anthropic's server-side web search tool with `allowed_domains`, so results can only come from
these sites (subdomains included: nih.gov covers DailyMed, PubMed Central, NIDDK...). Claude's answer
comes back with citations (URL, title, quoted text) that GLPal turns into its usual [n] sources.

Returns None whenever search can't be used (no Anthropic key, search disabled, API error), so the
coach falls back to the local cited library. Red flags and the dose-change guard always run first.
"""
import os

import httpx

from . import config

TRUSTED_DOMAINS = [
    "fda.gov",              # prescribing information, safety communications
    "nih.gov",              # DailyMed, MedlinePlus pages on nlm.nih.gov, PubMed Central, NIDDK
    "medlineplus.gov",      # plain-language drug and health information (NIH)
    "cdc.gov",
    "canada.ca",            # Health Canada drug and safety information
    "who.int",
    "nhs.uk",
    "mayoclinic.org",
    "clevelandclinic.org",
    "diabetes.org",         # American Diabetes Association
    "obesitymedicine.org",  # Obesity Medicine Association
]

SYSTEM = """You are GLPal's coach for people taking GLP-1 medicines (Wegovy, Ozempic, Mounjaro, Zepbound and
related pills). You can search a small set of trusted medical websites (FDA, NIH/DailyMed/MedlinePlus, CDC,
Health Canada, WHO, NHS, Mayo Clinic, Cleveland Clinic and medical societies).
Rules:
- For any medical or factual question, search first and answer ONLY from what the search results say.
  Never answer medical questions from memory, and don't add anecdotes or extra facts that the results
  don't support: every factual sentence must be backed by a search result. If the results don't answer it, say so plainly and suggest
  the prescriber or pharmacist.
- Never tell the user to change, skip, split or stop a dose; never diagnose. Refer those to the prescriber.
- Prefer official prescribing information (FDA labels) over general articles when they disagree.
- Be warm, plain-spoken and brief: 2-5 short sentences, or a short list if steps help. No headings.
- If the message is casual (a greeting, thanks, a feeling) and needs no facts, do not search: reply with
  [CHAT] followed by a short, friendly reply.
- Answer only the current message; use the earlier conversation just to understand follow-ups."""

MAX_SEARCHES = 3
TIMEOUT = httpx.Timeout(90.0, connect=10.0)


def enabled() -> bool:
    mode = os.getenv("WEB_SEARCH", "auto").strip().lower()
    if mode in ("off", "false", "0", "no"):
        return False
    return bool(config.ANTHROPIC_API_KEY) and config.resolved_provider() == "anthropic"


def _request(messages: list[dict]) -> dict:
    r = httpx.post("https://api.anthropic.com/v1/messages", timeout=TIMEOUT,
                   headers={"x-api-key": config.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"},
                   json={"model": config.ANTHROPIC_MODEL, "max_tokens": 1200, "system": SYSTEM,
                         "messages": messages,
                         "tools": [{"type": "web_search_20250305", "name": "web_search",
                                    "max_uses": MAX_SEARCHES, "allowed_domains": TRUSTED_DOMAINS}]})
    if r.status_code >= 400:
        raise RuntimeError(f"web search request failed: HTTP {r.status_code}")
    return r.json()


def _domain(url: str) -> str:
    host = url.split("//", 1)[-1].split("/", 1)[0].lower()
    return host[4:] if host.startswith("www.") else host


def _assemble(content: list[dict]) -> tuple[str, list[dict], int]:
    """Join Claude's answer text, add [n] markers for its citations, and build GLPal's citation list."""
    # Only the text after the last search result is the answer ("Let me search..." preambles are dropped).
    last = max((i for i, b in enumerate(content) if b.get("type") == "web_search_tool_result"), default=-1)
    searches = sum(1 for b in content if b.get("type") == "server_tool_use")
    numbers: dict[str, int] = {}
    cites: list[dict] = []
    parts: list[str] = []
    for b in content[last + 1:]:
        if b.get("type") != "text":
            continue
        piece = b.get("text", "")
        marks = []
        for c in b.get("citations") or []:
            url = c.get("url")
            if not url:
                continue
            if url not in numbers:
                numbers[url] = len(numbers) + 1
                cites.append({"n": numbers[url], "title": c.get("title") or _domain(url), "source": _domain(url),
                              "section": "Live search", "url": url, "quote": c.get("cited_text") or ""})
            if f"[{numbers[url]}]" not in marks:
                marks.append(f"[{numbers[url]}]")
        if marks:
            piece = piece.rstrip() + " " + "".join(marks) + (" " if piece.endswith(" ") else "")
        parts.append(piece)
    return "".join(parts).strip(), cites, searches


def answer(question: str, medication: str | None, user_context: str, history: list[dict]) -> dict | None:
    """A cited answer from live search of trusted sites, or None if search can't be used."""
    if not enabled():
        return None
    prompt = ""
    if history:
        prompt += "Earlier conversation (context only):\n" + "\n".join(
            f"{'User' if t['role'] == 'user' else 'Coach'}: {t['text']}" for t in history) + "\n\n"
    if medication:
        prompt += f"The user takes: {medication}. Focus on that medicine unless they ask about another.\n\n"
    if user_context:
        prompt += f"The user's own recent log (not a source):\n{user_context}\n\n"
    prompt += f"User: {question}"
    messages = [{"role": "user", "content": prompt}]
    try:
        content: list[dict] = []
        for _ in range(3):                                # continue if the API pauses a long turn
            data = _request(messages)
            content += data.get("content", [])
            if data.get("stop_reason") != "pause_turn":
                break
            messages = [messages[0], {"role": "assistant", "content": content}]
    except (httpx.HTTPError, RuntimeError, ValueError):
        return None
    text, cites, searches = _assemble(content)
    return {"text": text, "citations": cites, "searches": searches}
