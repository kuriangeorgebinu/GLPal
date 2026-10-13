"""GLPal web app: FastAPI JSON API + a single-page front end served from /static."""
from datetime import datetime
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import coach, config, db, insights, knowledge, llm, meals, report

app = FastAPI(title="GLPal", version="0.1.0",
              description="Companion app for people on GLP-1 medicines. Educational, not medical advice.")
db.init()

Medication = Literal["wegovy", "ozempic", "mounjaro", "zepbound"]


def _iso(dt: datetime | None) -> str | None:
    """Store timestamps as plain ISO strings without microseconds (YYYY-MM-DDTHH:MM:SS)."""
    return dt.replace(microsecond=0).isoformat() if dt else None


class ProfileIn(BaseModel):
    name: str | None = None
    medication: Medication | None = None
    current_dose_mg: float | None = Field(None, gt=0, le=20)
    dose_weekday: int | None = Field(None, ge=0, le=6)
    start_weight_kg: float | None = Field(None, gt=20, lt=400)
    goal_weight_kg: float | None = Field(None, gt=20, lt=400)
    protein_target_g: float | None = Field(None, gt=0, lt=400)
    water_target_ml: float | None = Field(None, gt=0, lt=10000)


class DoseIn(BaseModel):
    medication: Medication
    dose_mg: float = Field(..., gt=0, le=20)
    site: str = ""
    notes: str = ""
    taken_at: datetime | None = None


class SymptomIn(BaseModel):
    symptom: str = Field(..., min_length=1, max_length=60)
    severity: int = Field(..., ge=1, le=5)
    notes: str = ""
    logged_at: datetime | None = None


class MealIn(BaseModel):
    description: str = Field(..., min_length=1, max_length=500)
    protein_g: float = Field(0, ge=0, le=400)
    calories: float = Field(0, ge=0, le=10000)
    high_fat: bool = False
    source: str = "manual"
    eaten_at: datetime | None = None


class WeightIn(BaseModel):
    weight_kg: float = Field(..., gt=20, lt=400)
    measured_at: datetime | None = None


class WaterIn(BaseModel):
    ml: float = Field(..., gt=0, le=5000)
    logged_at: datetime | None = None


class AskIn(BaseModel):
    question: str = Field(..., max_length=1000)
    use_my_data: bool = True


@app.get("/api/status")
def status():
    return {"app": "GLPal", "version": app.version, "ai_provider": llm.provider(),
            "vision": llm.supports_vision(), "knowledge": knowledge.stats()}


@app.get("/api/profile")
def get_profile():
    return db.get_profile()


@app.put("/api/profile")
def put_profile(body: ProfileIn):
    return db.update_profile(body.model_dump(exclude_none=True))


def _logger(table: str, model):
    def create(body: model):  # type: ignore[valid-type]
        row = body.model_dump()
        if table == "meals":
            row["high_fat"] = int(row["high_fat"])
        for col in ("taken_at", "logged_at", "eaten_at", "measured_at"):
            if col in row:
                row[col] = _iso(row[col])
        if table == "doses":
            # Only the most recent dose defines the profile's medicine and current dose. Logging a
            # back-dated or different dose must not silently rewrite the profile (and bias the coach).
            latest = db.list_rows("doses", limit=1)
            if not latest or (row.get("taken_at") or "") >= (latest[0]["taken_at"] or ""):
                db.update_profile({"medication": row["medication"], "current_dose_mg": row["dose_mg"]})
        return db.add(table, row)

    def list_(days: int = 30):
        from datetime import datetime, timedelta
        return db.list_rows(table, (datetime.now() - timedelta(days=days)).isoformat())

    app.post(f"/api/{table}", status_code=201)(create)
    app.get(f"/api/{table}")(list_)


for _t, _m in [("doses", DoseIn), ("symptoms", SymptomIn), ("meals", MealIn), ("weights", WeightIn), ("water", WaterIn)]:
    _logger(_t, _m)


@app.delete("/api/{table}/{row_id}")
def delete_row(table: str, row_id: int):
    if not db.delete(table, row_id):
        raise HTTPException(404, "Not found")
    return {"deleted": row_id}


@app.post("/api/meals/estimate")
async def estimate_meal(description: str = Form(""), photo: UploadFile | None = File(None)):
    image, ctype = None, "image/jpeg"
    if photo is not None and photo.filename:
        image = await photo.read()
        ctype = photo.content_type or ctype
        if len(image) > 5_000_000:
            raise HTTPException(413, "Photo is too large (max 5 MB).")
        if ctype not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
            raise HTTPException(415, "Use a JPEG, PNG, WebP or GIF photo.")
    result = meals.estimate(description, image, ctype)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@app.get("/api/dashboard")
def dashboard():
    return insights.dashboard()


@app.post("/api/coach")
def ask(body: AskIn):
    profile = db.get_profile()
    ctx = insights.context_for_coach() if body.use_my_data else ""
    return coach.answer(body.question, medication=profile.get("medication"), user_context=ctx)


@app.get("/api/sources")
def sources():
    passages, srcs = knowledge.load()
    return {"sources": srcs, "cards": [{"id": p["id"], "title": p["title"], "source": p["source_name"],
                                        "url": p["url"], "section": p.get("section", "")} for p in passages]}


@app.get("/report", response_class=HTMLResponse)
def visit_report(days: int = 30):
    return report.build(max(1, min(days, 365)))


@app.get("/privacy", response_class=PlainTextResponse)
def privacy():
    return (config.ROOT / "PRIVACY.md").read_text(encoding="utf-8")


app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(config.STATIC_DIR / "index.html")
