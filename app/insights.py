"""Dashboard numbers, pattern spotting and smart nudges, computed from the user's own logs.

Pattern spotting is deliberately simple, transparent statistics (no AI), so every insight can
show the numbers behind it. Insights describe the user's data; they never give medical advice.
"""
from datetime import date, datetime, timedelta
from statistics import mean

from . import db

SITES = ["Abdomen - left", "Abdomen - right", "Thigh - left", "Thigh - right",
         "Upper arm - left", "Upper arm - right"]

# Missed-dose windows from the official labels (card ids in knowledge/curated_sources.json)
MISSED_DOSE = {
    "wegovy": ("Take it if your next dose is more than 2 days away; otherwise skip it.", "wegovy-missed"),
    "ozempic": ("Take it within 5 days of the missed day; after that, skip it.", "ozempic-missed"),
    "mounjaro": ("Take it within 4 days of the missed day; after that, skip it.", "tirzepatide-missed"),
    "zepbound": ("Take it within 4 days of the missed day; after that, skip it.", "tirzepatide-missed"),
}


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _day(s: str) -> date:
    return _dt(s).date()


def dose_status(profile: dict, doses: list[dict], now: datetime | None = None) -> dict:
    now = now or datetime.now()
    if not doses:
        return {"state": "none", "message": "Log your first dose to start tracking your weekly schedule."}
    # Sort internally: callers may pass rows in any order, and the whole calculation depends on
    # "most recent dose first".
    doses = sorted(doses, key=lambda d: d["taken_at"], reverse=True)
    last = doses[0]
    due = _dt(last["taken_at"]) + timedelta(days=7)
    days_left = (due.date() - now.date()).days
    recent_sites = [d["site"] for d in doses[:3] if d.get("site")]
    next_site = next((s for s in SITES if s not in recent_sites), SITES[0])
    if recent_sites and recent_sites[0] in SITES:
        i = SITES.index(recent_sites[0])
        rotated = [SITES[(i + j) % len(SITES)] for j in range(1, len(SITES))]
        next_site = next((s for s in rotated if s not in recent_sites), rotated[0])
    state = "ok" if days_left > 0 else ("due" if days_left == 0 else "overdue")
    out = {"state": state, "last_dose": last, "next_due": due.date().isoformat(), "days_left": days_left,
           "suggested_site": next_site}
    # Count consecutive doses at the current strength, walking back from the latest dose until the
    # medicine or the dose changes. Counting every dose ever logged at that strength would inflate
    # the number a prescriber reads on the visit summary.
    weeks = 0
    for d in doses:
        if d["dose_mg"] == last["dose_mg"] and d["medication"] == last["medication"]:
            weeks += 1
        else:
            break
    out["weeks_on_current_dose"] = weeks
    if state == "overdue":
        rule = MISSED_DOSE.get((last["medication"] or "").lower())
        if rule:
            out["missed_rule"] = {"text": rule[0], "card": rule[1]}
    return out


def _sum_today(rows, time_col, field, today):
    return round(sum(r[field] or 0 for r in rows if _day(r[time_col]) == today), 1)


def symptom_dose_pattern(doses, symptoms) -> dict | None:
    """Is a symptom worse in the first 2 days after an injection than later in the week?"""
    if len(doses) < 2 or len(symptoms) < 4:
        return None
    dose_times = sorted(_dt(d["taken_at"]) for d in doses)
    by_symptom: dict[str, dict[str, list[int]]] = {}
    for s in symptoms:
        t = _dt(s["logged_at"])
        before = [d for d in dose_times if d <= t]
        if not before:
            continue
        days_after = (t - before[-1]).days
        bucket = "early" if days_after <= 2 else "late"
        by_symptom.setdefault(s["symptom"].lower(), {"early": [], "late": []})[bucket].append(s["severity"])
    best = None
    for name, b in by_symptom.items():
        if len(b["early"]) >= 2 and len(b["late"]) >= 2:
            diff = mean(b["early"]) - mean(b["late"])
            if diff >= 1 and (best is None or diff > best["diff"]):
                best = {"symptom": name, "early_avg": round(mean(b["early"]), 1),
                        "late_avg": round(mean(b["late"]), 1), "diff": round(diff, 1)}
    if not best:
        return None
    return {"id": "symptom-after-dose", "title": f"Your {best['symptom']} peaks right after injection",
            "detail": f"Average {best['symptom']} severity is {best['early_avg']}/5 in the 2 days after a dose, "
                      f"versus {best['late_avg']}/5 later in the week.",
            "suggestion": "Plan smaller, lighter meals for the 2 days after your injection.",
            "related_card": "nausea-eating"}


def fat_nausea_pattern(meals, symptoms) -> dict | None:
    """Is nausea logged within 12 hours after high-fat meals more often than after other meals?"""
    nausea = [_dt(s["logged_at"]) for s in symptoms if "nausea" in s["symptom"].lower()]
    if len(meals) < 4 or len(nausea) < 2:
        return None

    def followed(m):
        t = _dt(m["eaten_at"])
        return any(timedelta(0) <= n - t <= timedelta(hours=12) for n in nausea)
    fatty = [followed(m) for m in meals if m["high_fat"]]
    other = [followed(m) for m in meals if not m["high_fat"]]
    if len(fatty) < 2 or len(other) < 2:
        return None
    rf, ro = sum(fatty) / len(fatty), sum(other) / len(other)
    if rf - ro < 0.25:
        return None
    return {"id": "fat-nausea", "title": "High-fat meals tend to come before your nausea",
            "detail": f"Nausea followed {round(rf * 100)}% of your high-fat meals within 12 hours, "
                      f"versus {round(ro * 100)}% of your other meals.",
            "suggestion": "Try leaner protein (chicken, fish, Greek yogurt) and see if it helps.",
            "related_card": "nausea-eating"}


def protein_pattern(meals, target, today) -> dict | None:
    days = [today - timedelta(days=i) for i in range(1, 8)]
    totals = {d: 0.0 for d in days}
    for m in meals:
        if _day(m["eaten_at"]) in totals:
            totals[_day(m["eaten_at"])] += m["protein_g"] or 0
    logged = [v for v in totals.values() if v > 0]
    if len(logged) < 3:
        return None
    hit = sum(1 for v in logged if v >= target)
    avg = round(mean(logged))
    if hit / len(logged) >= 0.7:
        return {"id": "protein-good", "title": "You're hitting your protein target",
                "detail": f"{hit} of your last {len(logged)} logged days met {round(target)} g (average {avg} g).",
                "suggestion": "Pair it with strength training to help protect muscle.", "related_card": "muscle-strength"}
    return {"id": "protein-low", "title": "Protein has been running low",
            "detail": f"Only {hit} of your last {len(logged)} logged days met {round(target)} g (average {avg} g/day).",
            "suggestion": "Front-load protein early in the day, when appetite is usually best.",
            "related_card": "protein-targets"}


def weight_summary(weights, profile) -> dict:
    if not weights:
        return {"latest": None}
    ws = sorted(weights, key=lambda w: w["measured_at"])
    latest, first = ws[-1], ws[0]
    start = profile.get("start_weight_kg") or first["weight_kg"]
    out = {"latest": latest["weight_kg"], "start": start, "change": round(latest["weight_kg"] - start, 1),
           "change_pct": round((latest["weight_kg"] - start) / start * 100, 1) if start else None}
    recent = [w for w in ws if _dt(w["measured_at"]) >= _dt(latest["measured_at"]) - timedelta(days=28)]
    if len(recent) >= 2:
        span = (_dt(recent[-1]["measured_at"]) - _dt(recent[0]["measured_at"])).days or 1
        out["per_week"] = round((recent[-1]["weight_kg"] - recent[0]["weight_kg"]) / span * 7, 2)
    if profile.get("goal_weight_kg"):
        out["to_goal"] = round(latest["weight_kg"] - profile["goal_weight_kg"], 1)
    return out


def dashboard(now: datetime | None = None) -> dict:
    now = now or datetime.now()
    today = now.date()
    profile = db.get_profile()
    since = (now - timedelta(days=60)).isoformat()
    doses = db.list_rows("doses", since)
    symptoms = db.list_rows("symptoms", since)
    meals = db.list_rows("meals", since)
    water = db.list_rows("water", since)
    weights = db.list_rows("weights")

    protein_today = _sum_today(meals, "eaten_at", "protein_g", today)
    water_today = _sum_today(water, "logged_at", "ml", today)
    status = dose_status(profile, doses, now)

    patterns = [p for p in (symptom_dose_pattern(doses, symptoms), fat_nausea_pattern(meals, symptoms),
                            protein_pattern(meals, profile["protein_target_g"] or 100, today)) if p]

    nudges = []
    if status["state"] in ("due", "overdue"):
        nudges.append({"kind": "dose", "text": "Your weekly dose is due today." if status["state"] == "due"
                       else f"Your dose was due {-status['days_left']} day(s) ago. Check the missed-dose rule below."})
    elif status["state"] == "ok" and status["days_left"] == 1:
        nudges.append({"kind": "dose", "text": "Your dose is due tomorrow. Make sure your pen is in the fridge."})
    if any(p["id"] == "symptom-after-dose" for p in patterns) and status.get("days_left") in (5, 6, 7):
        nudges.append({"kind": "food", "text": "You're in the 2 days after your injection, when your symptoms usually "
                                               "peak. Keep meals small and sip fluids through the day."})
    water_target = profile["water_target_ml"] or 2000
    if now.hour >= 14 and water_today < water_target * 0.5:
        nudges.append({"kind": "water", "text": f"You've logged {int(water_today)} ml of fluids so far. "
                                                f"Try to sip some water now."})
    protein_target = profile["protein_target_g"] or 100
    if now.hour >= 17 and protein_today < protein_target * 0.6:
        nudges.append({"kind": "protein", "text": f"{int(protein_target - protein_today)} g of protein to go today. "
                                                  "A Greek yogurt or protein shake is an easy add."})
    recent_bad = [s for s in symptoms if _dt(s["logged_at"]) >= now - timedelta(hours=48) and s["severity"] >= 4]
    if recent_bad:
        nudges.append({"kind": "symptom", "text": "You've logged some severe symptoms in the last 2 days. If they "
                                                  "continue or get worse, contact your prescriber."})

    return {"profile": profile, "dose": status,
            "today": {"protein_g": protein_today, "protein_target_g": protein_target,
                      "water_ml": water_today, "water_target_ml": water_target,
                      "meals": [m for m in meals if _day(m["eaten_at"]) == today],
                      "symptoms": [s for s in symptoms if _day(s["logged_at"]) == today]},
            "weight": weight_summary(weights, profile), "patterns": patterns, "nudges": nudges}


def context_for_coach() -> str:
    """A short, plain summary of the user's recent data that the coach may refer to."""
    d = dashboard()
    p = d["profile"]
    lines = [f"Medication: {p['medication']} {p['current_dose_mg']} mg weekly."]
    if d["dose"].get("last_dose"):
        lines.append(f"Last dose {d['dose']['last_dose']['taken_at'][:10]}, next due {d['dose']['next_due']}.")
    lines.append(f"Protein today {d['today']['protein_g']} of {d['today']['protein_target_g']} g; "
                 f"fluids {int(d['today']['water_ml'])} of {int(d['today']['water_target_ml'])} ml.")
    for pat in d["patterns"]:
        lines.append(f"Pattern: {pat['detail']}")
    return "\n".join(lines)
