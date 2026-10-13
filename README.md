# GLPal

**An AI companion for people on GLP-1 medicines** (Wegovy, Ozempic, Mounjaro, Zepbound).
GLPal tracks doses, side effects, protein, fluids and weight. It spots patterns in your own data,
and it answers questions **only from trusted sources, with citations**.

> GLPal is an educational tracking tool, not medical advice. It never tells anyone to change a dose.

## What's in the MVP

| Feature | What it does |
|---|---|
| **Dose tracker** | Logs doses and shows the next due date. Suggests the next injection site so you rotate. If a dose is overdue, it shows the label's missed-dose rule. |
| **Side-effect log** | One-tap symptoms with a 1-5 severity scale. |
| **AI meal logging** | Describe a meal (or add a photo with a vision-capable AI) to get estimated protein, calories and a high-fat flag. You can edit the numbers before saving. |
| **Protein and fluid rings** | Progress against your daily targets. Settings shows the 2025 nutrition advisory's ranges for your weight. |
| **Pattern spotting** | Plain statistics you can check, for example: "nausea averages 3.2/5 in the 2 days after a dose vs 2.2/5 later", "nausea followed 100% of high-fat meals", "protein below target 6 of 7 days". |
| **Smart nudges** | Dose due, low fluids by mid-afternoon, protein gap in the evening, and a prompt to contact the prescriber after severe symptoms. |
| **Cited coach** | Q&A answered by RAG over a curated library, with `[n]` citations, the quoted passage and a source link. It checks for red flags first (pancreatitis, allergy, crisis, dehydration, thyroid, gallbladder) and points to urgent care. Dose-change questions are referred to the prescriber. If the sources don't cover a question, it says so instead of guessing. |
| **Doctor visit summary** | A printable one-page report of the last 30 days: doses, symptoms, weight, protein and patterns. |

### Trusted sources
- FDA prescribing information for Wegovy, Ozempic, Mounjaro and Zepbound (via DailyMed / openFDA)
- *Nutritional priorities to support GLP-1 therapy for obesity*, a 2025 joint advisory from ACLM, ASN, OMA and TOS ([PMC12304835](https://pmc.ncbi.nlm.nih.gov/articles/PMC12304835/))

`knowledge/curated_sources.json` has 26 hand-curated passages. To add the **full official label
text**, run `python scripts/ingest_fda_labels.py`, which builds `knowledge/fda_labels.json` from openFDA.

## How to run it

**You need** Python 3.10 or newer ([python.org](https://www.python.org/downloads/)).

### Windows (easiest)
Double-click **`run.bat`**. The first time, it creates a virtual environment, installs packages and
copies `.env.example` to `.env`. Then it opens **http://127.0.0.1:8000** in your browser.
Close the window to stop the app.

### macOS / Linux
```bash
./run.sh
```

### Manually (any OS)
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # Windows: copy .env.example .env
python -m uvicorn app.main:app --reload
```
Then open http://127.0.0.1:8000.

### Try it with demo data
```bash
python scripts/seed_demo.py --reset    # 4 weeks of realistic doses, meals, symptoms and weights
```
This lets the dashboard show patterns right away.

### Turn on the AI
GLPal works with **no API key**. In that offline mode the coach quotes the most relevant cited
passages, and meal estimates come from a built-in food table. To use a real model, put **one** key
in `.env`:

| Provider | `.env` setting | Meal photos? |
|---|---|---|
| DeepSeek | `DEEPSEEK_API_KEY=...` | No (text only) |
| Anthropic Claude | `ANTHROPIC_API_KEY=...` | Yes |
| OpenAI | `OPENAI_API_KEY=...` | Yes |

**Live trusted-site search (Anthropic).** With the Anthropic provider, the coach uses Claude's web search
restricted to an allowlist of trusted medical sites (`app/websearch.py`: FDA, NIH incl. DailyMed and
MedlinePlus, CDC, Health Canada, WHO, NHS, Mayo Clinic, Cleveland Clinic, medical societies), and answers
with citations to those pages. Red-flag triage and the dose-change guard still run first; an uncited reply
is never shown as medical text; if search is unavailable the coach falls back to the built-in library.
Set `WEB_SEARCH=off` to disable. Cost: about $10 per 1,000 searches plus tokens (max 3 searches per question).

`LLM_PROVIDER=auto` (the default) uses whichever key is set. The badge in the top-right corner
shows which AI is active.

### Privacy
With **no API key**, nothing leaves your computer: the coach quotes its own cited library and meal
estimates come from a built-in food table. With a key set, your coach question (and, only if you tick
"Let the coach see my recent logs", a short summary of your logs) and your meal description/photo are
sent to that provider. The coach and meal tabs say so on screen, and log-sharing is off by default
when a real provider is active. GLPal has no ads, no analytics and never sells data. Full details:
[PRIVACY.md](PRIVACY.md), also served at `/privacy`.

### Run the tests
```bash
python -m pytest -q
```

## How it's built

```
app/
  main.py        FastAPI routes (JSON API + serves the web page)
  db.py          SQLite storage in glpal.db (local; never committed)
  coach.py       red flags -> dose-change guard -> retrieval -> cited answer -> citation check
  knowledge.py   BM25 search over the trusted library (offline, no extra packages)
  llm.py         one interface for DeepSeek / OpenAI / Anthropic / offline
  meals.py       AI meal estimates + offline food table
  insights.py    dashboard, pattern spotting, nudges
  report.py      printable doctor-visit summary
static/          single-page front end (HTML/CSS/JS, no build step)
knowledge/       curated, cited source passages
scripts/         ingest_fda_labels.py, seed_demo.py
tests/           pytest suite (offline)
```

**Safety design.** The coach can only use retrieved passages. It must cite every claim, and citation
numbers are checked after generation: invented ones are dropped. If an answer ends up with no
real citations, it is replaced by a quoted, cited passage. Emergency symptoms are caught before any
AI call, and the red-flag patterns are order-independent (a severity word, a body part and a pain
word can appear in any order). A passage is only returned if it shares a real content word with the
question, so a weak match can't drag in an unrelated citation.

### API
Interactive docs are at http://127.0.0.1:8000/docs. Main endpoints: `GET /api/dashboard`,
`POST /api/{doses|symptoms|meals|weights|water}`, `POST /api/meals/estimate`, `POST /api/coach`,
`GET /api/sources`, `GET /report` and `GET /privacy`.

## Roadmap ideas
Mobile app (Expo), reminders through push notifications, Apple Health / Google Fit sync, an
off-ramp plan for stopping the medicine, and a clinician share link.
