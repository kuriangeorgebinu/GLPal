"""Run with:  python -m pytest -q   (uses a temporary database and the offline AI mode).

The offline mode and temporary database are set up in tests/conftest.py, before any app import.
"""
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app import coach, insights, knowledge, meals
from app.main import app

client = TestClient(app)


def test_status_and_index():
    s = client.get("/api/status").json()
    assert s["ai_provider"] == "mock" and s["knowledge"]["passages"] >= 20
    assert "GLPal" in client.get("/").text


def test_log_and_dashboard():
    assert client.post("/api/doses", json={"medication": "wegovy", "dose_mg": 0.25, "site": "Abdomen - left"}).status_code == 201
    client.post("/api/meals", json={"description": "chicken", "protein_g": 30})
    client.post("/api/water", json={"ml": 500})
    client.post("/api/weights", json={"weight_kg": 100})
    d = client.get("/api/dashboard").json()
    assert d["today"]["protein_g"] == 30 and d["today"]["water_ml"] == 500
    assert d["dose"]["state"] == "ok" and d["dose"]["suggested_site"] == "Abdomen - right"
    assert d["profile"]["medication"] == "wegovy"


def test_validation_rejects_bad_input():
    assert client.post("/api/symptoms", json={"symptom": "nausea", "severity": 9}).status_code == 422
    assert client.post("/api/doses", json={"medication": "aspirin", "dose_mg": 1}).status_code == 422


def test_retrieval_finds_right_passages():
    assert knowledge.search("I missed my wegovy shot", medication="wegovy")[0]["id"] == "wegovy-missed"
    assert knowledge.search("how much protein should I eat")[0]["id"] == "protein-targets"
    assert knowledge.search("mounjaro birth control pill")[0]["id"] == "contraception-tirzepatide"


def test_coach_answers_with_valid_citations():
    r = coach.answer("How do I deal with nausea?")
    assert r["kind"] == "answer" and r["citations"]
    assert all(f"[{c['n']}]" in r["answer"] for c in r["citations"])
    assert all(c["url"].startswith("https://") for c in r["citations"])


def test_coach_red_flag_and_dose_refusal():
    r = coach.answer("I have severe stomach pain that goes to my back")
    assert r["kind"] == "urgent" and "pancreatitis" in r["answer"].lower()
    r = coach.answer("Should I double my dose this week?")
    assert r["kind"] == "refer" and "prescriber" in r["answer"]
    assert coach.answer("I feel suicidal")["kind"] == "urgent"


def test_coach_does_not_guess():
    assert coach.answer("What's the capital of Peru?")["kind"] == "not_found"


def test_citation_validation_drops_fake_numbers():
    text, ok = coach._validate_citations("Fact [1]. Made up [7].", 2)
    assert ok and "[7]" not in text


def test_offline_meal_estimate():
    r = meals.estimate("2 eggs and a greek yogurt")
    assert r["protein_g"] == 12 + 17 and not r["high_fat"]
    assert meals.estimate("cheeseburger and fries")["high_fat"]


def test_patterns():
    base = datetime(2026, 1, 5, 9)
    doses = [{"taken_at": (base + timedelta(days=7 * i)).isoformat()} for i in range(3)]
    sym = []
    for i in range(3):
        for off, sev in ((1, 4), (4, 1)):
            sym.append({"logged_at": (base + timedelta(days=7 * i + off)).isoformat(), "symptom": "nausea", "severity": sev})
    p = insights.symptom_dose_pattern(doses, sym)
    assert p and p["id"] == "symptom-after-dose"


def test_report_and_estimate_endpoint():
    assert "visit summary" in client.get("/report").text
    r = client.post("/api/meals/estimate", data={"description": "tuna salad"})
    assert r.status_code == 200 and r.json()["protein_g"] > 0
    assert client.post("/api/meals/estimate", data={"description": ""}).status_code == 400


def test_out_of_scope_offline():
    assert coach.answer("Can I drink alcohol on this?")["kind"] == "not_found"
    assert coach.answer("I feel constipated")["kind"] == "answer"


def test_dose_status_counts_consecutive_weeks():
    base = datetime(2026, 1, 5, 9)
    doses = [
        {"taken_at": (base + timedelta(days=7 * i)).isoformat(), "medication": "wegovy", "dose_mg": mg}
        for i, mg in enumerate([0.5, 1.0, 0.5])
    ]
    # Deliberately out of order: dose_status must sort internally.
    shuffled = [doses[1], doses[2], doses[0]]
    st = insights.dose_status({}, shuffled, now=base + timedelta(days=14))
    assert st["weeks_on_current_dose"] == 1
    assert st["last_dose"]["dose_mg"] == 0.5


def test_backdated_dose_does_not_change_profile():
    client.put("/api/profile", json={"medication": "wegovy", "current_dose_mg": 1.0})
    client.post("/api/doses", json={"medication": "wegovy", "dose_mg": 1.0})
    assert client.get("/api/profile").json()["current_dose_mg"] == 1.0
    # A back-dated dose of a different medicine must not rewrite the profile.
    client.post("/api/doses", json={"medication": "mounjaro", "dose_mg": 2.5,
                                    "taken_at": "2020-01-01T09:00:00"})
    p = client.get("/api/profile").json()
    assert p["medication"] == "wegovy" and p["current_dose_mg"] == 1.0


def test_bad_timestamp_is_rejected_and_dashboard_still_works():
    assert client.post("/api/doses", json={"medication": "wegovy", "dose_mg": 0.5,
                                           "taken_at": "not-a-date"}).status_code == 422
    assert client.post("/api/water", json={"ml": 250, "logged_at": "not-a-date"}).status_code == 422
    assert client.get("/api/dashboard").status_code == 200


def test_offline_meal_estimate_unknown_food():
    r = meals.estimate("a bowl of pho")
    assert r["protein_g"] is None and r["calories"] is None and r["confidence"] == "none"
    assert r["note"]
    resp = client.post("/api/meals/estimate", data={"description": "a bowl of pho"})
    assert resp.status_code == 200
    assert resp.json()["protein_g"] is None


def test_privacy_route_and_disclosure():
    r = client.get("/privacy")
    assert r.status_code == 200 and "glpal.db" in r.text
    assert 'id="ai-disclosure"' in client.get("/").text
    assert 'id="meal-disclosure"' in client.get("/").text
