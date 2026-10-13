"""One-page, printable doctor-visit summary of the last N days."""
import html
from collections import defaultdict
from datetime import datetime, timedelta

from . import db, insights


def build(days: int = 30) -> str:
    now = datetime.now()
    since = (now - timedelta(days=days)).isoformat()
    p = db.get_profile()
    doses = db.list_rows("doses", since)
    symptoms = db.list_rows("symptoms", since)
    meals = db.list_rows("meals", since)
    weights = db.list_rows("weights", since)
    dash = insights.dashboard(now)
    e = html.escape

    dose_rows = "".join(f"<tr><td>{e(d['taken_at'][:10])}</td><td>{e(d['medication'].title())}</td>"
                        f"<td>{d['dose_mg']:g} mg</td><td>{e(d['site'] or '-')}</td><td>{e(d['notes'] or '')}</td></tr>"
                        for d in reversed(doses)) or "<tr><td colspan=5>No doses logged</td></tr>"

    sym = defaultdict(list)
    for s in symptoms:
        sym[s["symptom"].lower()].append(s["severity"])
    sym_rows = "".join(f"<tr><td>{e(k.title())}</td><td>{len(v)}</td><td>{sum(v) / len(v):.1f}/5</td><td>{max(v)}/5</td></tr>"
                       for k, v in sorted(sym.items(), key=lambda kv: -len(kv[1]))) or \
        "<tr><td colspan=4>No symptoms logged</td></tr>"

    by_day = defaultdict(float)
    for m in meals:
        by_day[m["eaten_at"][:10]] += m["protein_g"] or 0
    protein_avg = round(sum(by_day.values()) / len(by_day)) if by_day else 0

    w = dash["weight"]
    ws = sorted(weights, key=lambda r: r["measured_at"])
    weight_line = (f"{ws[0]['weight_kg']:g} kg on {ws[0]['measured_at'][:10]} to {ws[-1]['weight_kg']:g} kg on "
                   f"{ws[-1]['measured_at'][:10]} ({ws[-1]['weight_kg'] - ws[0]['weight_kg']:+.1f} kg)"
                   if len(ws) >= 2 else ("One reading: %g kg" % ws[0]["weight_kg"] if ws else "No weights logged"))
    pattern_items = "".join(f"<li><b>{e(x['title'])}.</b> {e(x['detail'])}</li>" for x in dash["patterns"]) or \
        "<li>Not enough data for patterns yet.</li>"

    return f"""<!doctype html><html><head><meta charset="utf-8"><title>GLPal visit summary</title>
<style>body{{font:14px/1.5 system-ui,sans-serif;max-width:760px;margin:24px auto;padding:0 16px;color:#111}}
h1{{font-size:22px;margin:0}}h2{{font-size:16px;margin:22px 0 6px;border-bottom:1px solid #ccc}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ddd;padding:4px 8px;text-align:left}}
.muted{{color:#555;font-size:12px}}@media print{{button{{display:none}}}}</style></head><body>
<button onclick="print()">Print / save as PDF</button>
<h1>GLPal visit summary{(' - ' + e(p['name'])) if p['name'] else ''}</h1>
<p class="muted">Last {days} days, generated {now:%Y-%m-%d %H:%M}. Patient-reported data from the GLPal app.</p>
<h2>Medication</h2><p>{e((p['medication'] or '').title())}, current dose {p['current_dose_mg']:g} mg weekly.
{dash['dose'].get('weeks_on_current_dose') or 0} logged week(s) at this dose.</p>
<h2>Doses</h2><table><tr><th>Date</th><th>Medicine</th><th>Dose</th><th>Site</th><th>Notes</th></tr>{dose_rows}</table>
<h2>Side effects</h2><table><tr><th>Symptom</th><th>Times logged</th><th>Average</th><th>Worst</th></tr>{sym_rows}</table>
<h2>Weight</h2><p>{e(weight_line)}{'' if w.get('per_week') is None else f'. Recent trend {w["per_week"]:+.2f} kg/week'}.</p>
<h2>Nutrition</h2><p>Average protein on logged days: {protein_avg} g/day (target {p['protein_target_g']:g} g). Days with meals logged: {len(by_day)}.</p>
<h2>Patterns GLPal noticed</h2><ul>{pattern_items}</ul>
<h2>Questions for my prescriber</h2><ol><li>&nbsp;</li><li>&nbsp;</li><li>&nbsp;</li></ol>
<p class="muted">GLPal is an educational tracking tool and does not give medical advice.</p></body></html>"""
