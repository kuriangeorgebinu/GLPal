"""AI meal estimates: protein, calories and a high-fat flag from a description or a photo.

Without an AI key, a small built-in food table gives rough estimates so the feature still works.
Estimates are always labelled as estimates and can be edited before saving.
"""
import re

from . import llm

# grams of protein, calories, high_fat flag, for one typical portion
FOODS = {
    "chicken breast": (31, 165, 0), "chicken": (27, 240, 0), "turkey": (25, 170, 0),
    "salmon": (25, 280, 1), "tuna": (25, 130, 0), "shrimp": (20, 100, 0), "fish": (22, 150, 0),
    "steak": (42, 540, 1), "beef": (26, 290, 1), "burger": (25, 550, 1), "pork": (27, 300, 1),
    "bacon": (9, 160, 1), "sausage": (12, 280, 1), "egg": (6, 75, 0),
    "greek yogurt": (17, 130, 0), "yogurt": (9, 150, 0), "cottage cheese": (14, 110, 0),
    "cheese": (7, 110, 1), "milk": (8, 120, 0), "protein shake": (30, 160, 0), "protein bar": (20, 220, 0),
    "tofu": (20, 180, 0), "lentils": (18, 230, 0), "beans": (15, 225, 0), "chickpeas": (14, 270, 0),
    "edamame": (17, 190, 0), "peanut butter": (8, 190, 1), "nuts": (6, 170, 1), "almonds": (6, 165, 1),
    "pizza": (12, 285, 1), "fries": (4, 365, 1), "fried": (10, 400, 1), "pasta": (8, 220, 0),
    "rice": (4, 205, 0), "bread": (4, 80, 0), "toast": (4, 80, 0), "oatmeal": (6, 160, 0),
    "salad": (3, 80, 0), "avocado": (3, 240, 1), "banana": (1, 105, 0), "apple": (0, 95, 0),
    "soup": (8, 150, 0), "sandwich": (20, 400, 0), "wrap": (18, 380, 0), "sushi": (14, 300, 0),
    "ice cream": (5, 270, 1), "donut": (4, 300, 1), "chips": (2, 160, 1), "cookie": (2, 150, 1),
}
NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "half": 0.5, "a": 1, "an": 1}

SYSTEM = """You estimate nutrition for one meal for someone on a GLP-1 medicine who needs to hit a protein target.
Return ONLY a JSON object: {"items": [{"name": str, "protein_g": number, "calories": number}],
"protein_g": number, "calories": number, "high_fat": true|false, "confidence": "low"|"medium"|"high",
"tip": str}. "tip" is one short, friendly, non-medical suggestion to add protein or ease nausea.
Use typical portion sizes when unstated. Round to whole numbers."""


def _offline(description: str) -> dict:
    text = description.lower()
    items, used = [], set()
    for food in sorted(FOODS, key=len, reverse=True):          # longest match first
        m = re.search(rf"(?:(\d+(?:\.\d+)?|{'|'.join(NUM)})\s+)?{re.escape(food)}(?:e?s)?\b", text)
        if m and not any(food in u for u in used):
            qty_raw = m.group(1)
            qty = float(qty_raw) if qty_raw and qty_raw[0].isdigit() else NUM.get(qty_raw or "", 1)
            qty = qty if qty <= 6 else 1                          # "200g chicken" etc.: assume one portion
            p, kcal, fat = FOODS[food]
            items.append({"name": food, "protein_g": round(p * qty), "calories": round(kcal * qty), "high_fat": fat})
            used.add(food)
    if not items:
        # Nothing recognised: return no numbers rather than a misleading 0 g, and ask for real values.
        return {"items": [], "protein_g": None, "calories": None, "high_fat": False, "confidence": "none",
                "tip": "", "note": "I couldn't recognise any foods in that description. Please type the protein "
                                   "and calorie numbers yourself, or describe the meal with common foods.",
                "mode": "offline-table"}
    protein = sum(i["protein_g"] for i in items)
    return {"items": [{k: v for k, v in i.items() if k != "high_fat"} for i in items],
            "protein_g": protein, "calories": sum(i["calories"] for i in items),
            "high_fat": any(i["high_fat"] for i in items),
            "confidence": "low",
            "tip": "Adding a protein like Greek yogurt, eggs or chicken would help you reach your target."
                   if protein < 20 else "Nice protein-forward meal.",
            "mode": "offline-table"}


def estimate(description: str = "", image: bytes | None = None, image_type: str = "image/jpeg") -> dict:
    description = (description or "").strip()
    if image is not None and not llm.supports_vision():
        result = _offline(description) if description else {
            "items": [], "protein_g": None, "calories": None, "high_fat": False, "confidence": "none", "tip": "",
            "mode": "offline-table"}
        result["note"] = ("Photo estimates need an AI provider with vision (set LLM_PROVIDER=anthropic or openai). "
                          "Add a short description and GLPal will estimate from that.")
        return result
    if not description and image is None:
        return {"error": "Describe the meal or add a photo."}
    if llm.provider() == "mock":
        return _numbers(_offline(description))
    prompt = f"Meal description: {description or '(see photo)'}"
    try:
        data = llm.extract_json(llm.chat(SYSTEM, prompt, image=image, image_type=image_type, max_tokens=500))
    except llm.LLMError:
        data = None
    if not data or "protein_g" not in data:
        out = _offline(description)
        out["note"] = "The AI estimate wasn't available, so this is a rough offline estimate."
        return _numbers(out)
    data["protein_g"] = round(float(data.get("protein_g") or 0))
    data["calories"] = round(float(data.get("calories") or 0))
    data["high_fat"] = bool(data.get("high_fat"))
    data["mode"] = llm.provider()
    return data


def _numbers(result: dict) -> dict:
    """Make sure protein/calories are numbers or None, never a string or a missing key."""
    for key in ("protein_g", "calories"):
        v = result.get(key)
        result[key] = None if v is None else round(float(v))
    return result
