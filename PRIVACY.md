# GLPal privacy

GLPal is built to keep your health data on your own computer. This page says exactly what is stored,
what can leave the machine, and how to delete it.

## What is stored, and where

Everything you log — doses, side effects, meals, water, weight and your profile — is stored in a
single SQLite file called `glpal.db` in the GLPal folder on your computer. There is no GLPal account,
no GLPal server and no cloud sync. If you copy the folder, you copy the data; if you delete
`glpal.db`, the data is gone.

## What leaves your computer

Only AI requests, and only when you have set an API key in `.env`:

- **Coach questions.** When you ask the coach a question, the question text is sent to the AI
  provider you configured (DeepSeek, OpenAI or Anthropic). If the "Let the coach see my recent logs"
  box is ticked, a short summary of your recent logs (medicine, dose, last dose date, next due date,
  protein and fluid totals, and any patterns GLPal noticed) is sent with it. That box is unticked by
  default whenever a real AI provider is active, so log-sharing is opt-in.
- **Live search (Anthropic only).** To answer medical questions, Claude may search a fixed list of
  trusted medical websites (FDA, NIH/DailyMed/MedlinePlus, CDC, Health Canada, WHO, NHS, Mayo Clinic,
  Cleveland Clinic, medical societies). The search runs on Anthropic's side; the search terms are based
  on your question. Turn it off with `WEB_SEARCH=off` in `.env`.
- **Meal estimates.** When you press "Estimate with AI", your meal description — and the photo, if
  you attached one and your provider supports vision — is sent to the same provider.

With **no API key** (the default), GLPal runs in offline mode: the coach quotes the most relevant
cited passages from its own library and meal estimates come from a built-in food table. In offline
mode **nothing leaves your computer**.

The provider's own privacy policy governs what they do with a request once it reaches them. If that
matters to you, use offline mode, or use a provider you trust.

## What GLPal never does

- No ads, no ad SDKs, no analytics or tracking scripts.
- No selling or sharing of your data with anyone.
- No account, no email, no telemetry back to the GLPal authors.

## How to delete your data

- Delete individual entries from the History tab.
- To erase everything, stop GLPal and delete the `glpal.db` file in the GLPal folder. A fresh,
  empty database is created the next time you start the app.

## Questions

GLPal is an educational tracking tool, not medical advice. For anything about your own treatment,
talk to your prescriber or pharmacist.
