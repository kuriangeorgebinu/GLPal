"""Fill GLPal with 4 weeks of realistic demo data so the dashboard and patterns have something to show.

    python scripts/seed_demo.py           # adds demo data to glpal.db
    python scripts/seed_demo.py --reset   # wipes glpal.db first
"""
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config, db  # noqa: E402

LEAN = [("Greek yogurt with berries", 17, 180), ("2 eggs and toast", 16, 230), ("Chicken breast salad", 34, 380),
        ("Tuna sandwich", 28, 420), ("Protein shake", 30, 160), ("Lentil soup", 18, 260), ("Salmon and rice", 30, 520)]
FATTY = [("Cheeseburger and fries", 28, 950), ("Pepperoni pizza, 2 slices", 24, 600), ("Fried chicken", 30, 750)]
SITES = ["Abdomen - left", "Abdomen - right", "Thigh - left", "Thigh - right", "Upper arm - left", "Upper arm - right"]


def main():
    if "--reset" in sys.argv and config.DB_PATH.exists():
        config.DB_PATH.unlink()
    db.init()
    random.seed(7)
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(days=27)
    db.update_profile({"name": "Demo", "medication": "wegovy", "current_dose_mg": 0.5, "start_weight_kg": 102.0,
                       "goal_weight_kg": 85.0, "protein_target_g": 100, "water_target_ml": 2000})
    weight = 102.0
    for day in range(28):
        d = start + timedelta(days=day)
        since_dose = day % 7
        if since_dose == 0:
            dose = 0.25 if day < 21 else 0.5
            db.add("doses", {"taken_at": d.replace(hour=9).isoformat(), "medication": "wegovy", "dose_mg": dose,
                             "site": SITES[(day // 7) % len(SITES)]})
        fatty_day = random.random() < 0.3
        for hour, pool in ((8, LEAN), (13, FATTY if fatty_day else LEAN), (19, LEAN)):
            name, p, kcal = random.choice(pool)
            db.add("meals", {"eaten_at": d.replace(hour=hour).isoformat(), "description": name, "protein_g": p,
                             "calories": kcal, "high_fat": int(pool is FATTY), "source": "demo"})
        nausea = (4 if since_dose in (0, 1) else 2) + (1 if fatty_day else 0) - (1 if day > 20 else 0)
        if since_dose in (0, 1, 2) or fatty_day or random.random() < 0.25:
            db.add("symptoms", {"logged_at": d.replace(hour=18 if fatty_day else 16).isoformat(), "symptom": "nausea",
                                "severity": max(1, min(5, nausea))})
        if random.random() < 0.2:
            db.add("symptoms", {"logged_at": d.replace(hour=20).isoformat(), "symptom": "constipation", "severity": 2})
        for hour in (9, 12, 15, 18):
            db.add("water", {"logged_at": d.replace(hour=hour).isoformat(), "ml": random.choice([250, 300, 500])})
        if day % 3 == 0:
            weight -= random.uniform(0.2, 0.6)
            db.add("weights", {"measured_at": d.replace(hour=7).isoformat(), "weight_kg": round(weight, 1)})
    print(f"Demo data added to {config.DB_PATH}")


if __name__ == "__main__":
    main()
