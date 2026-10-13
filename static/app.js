// GLPal front end: plain JS, no build step.
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const SITES = ["Abdomen - left", "Abdomen - right", "Thigh - left", "Thigh - right", "Upper arm - left", "Upper arm - right"];
const SYMPTOMS = ["nausea", "vomiting", "constipation", "diarrhea", "fatigue", "heartburn", "headache", "bloating", "dizziness"];
const QUESTIONS = ["I missed my shot 3 days ago, what now?", "How much protein should I eat?",
  "How do I deal with nausea?", "Where should I inject?", "How do I store my pen?", "Should I double my dose?"];

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {}, ...opts });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail ? (typeof data.detail === "string" ? data.detail : "Please check the form") : `Error ${r.status}`);
  return data;
}
const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body) });

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 2200);
}

function formData(form) {
  const out = {};
  for (const el of form.elements) {
    if (!el.name || el.type === "file") continue;
    if (el.type === "checkbox") out[el.name] = el.checked;
    else if (el.type === "number" || el.type === "range") { if (el.value !== "") out[el.name] = Number(el.value); }
    else if (el.type === "datetime-local") { if (el.value) out[el.name] = el.value.length === 16 ? el.value + ":00" : el.value; }
    else out[el.name] = el.value;
  }
  return out;
}

// ---------- tabs ----------
function show(view) {
  $$(".tab").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
  if (view === "today") loadDashboard();
  if (view === "history") loadHistory();
  if (view === "settings") loadSettings();
  try { localStorage.setItem("glpal-tab", view); } catch {}
}
$$(".tab").forEach((b) => b.addEventListener("click", () => show(b.dataset.view)));

// ---------- today ----------
function ring(el, value, target, unit) {
  const pct = Math.min(100, Math.round((value / (target || 1)) * 100));
  el.style.setProperty("--p", pct);
  el.dataset.label = `${pct}%`;
  return `<div class="big">${Math.round(value)}<span class="muted"> / ${Math.round(target)} ${unit}</span></div>`;
}

async function loadDashboard() {
  const d = await api("/api/dashboard");
  $("#nudges").innerHTML = d.nudges.map((n) => `<div class="nudge ${n.kind}">${esc(n.text)}</div>`).join("");

  const ds = d.dose;
  let dose = `<h3>Next dose</h3>`;
  if (ds.state === "none") dose += `<p>${esc(ds.message)}</p>`;
  else {
    const when = ds.days_left > 1 ? `in ${ds.days_left} days` : ds.days_left === 1 ? "tomorrow" : ds.days_left === 0 ? "today" : `${-ds.days_left} day(s) overdue`;
    dose += `<div class="big">${esc(when)}</div><div class="muted">${esc(ds.next_due)} · ${esc(d.profile.medication)} ${d.profile.current_dose_mg} mg</div>
      <p>Suggested site: <b>${esc(ds.suggested_site)}</b></p>
      <div class="muted">${ds.weeks_on_current_dose} week(s) logged at this dose</div>`;
    if (ds.missed_rule) dose += `<p class="nudge dose">Label's missed-dose rule: ${esc(ds.missed_rule.text)}
      <br><a href="#" data-ask="I missed my dose, what does the label say?">See the source</a></p>`;
  }
  $("#dose-card").innerHTML = dose;

  $("#protein-text").innerHTML = ring($("#protein-ring"), d.today.protein_g, d.today.protein_target_g, "g");
  $("#water-text").innerHTML = ring($("#water-ring"), d.today.water_ml, d.today.water_target_ml, "ml");

  const w = d.weight;
  $("#weight-card").innerHTML = `<h3>Weight</h3>` + (w.latest == null ? `<p>Log your weight to see your progress.</p>` :
    `<div class="big">${w.latest} kg</div>
     <div class="muted">${w.change <= 0 ? "Down" : "Up"} ${Math.abs(w.change)} kg${w.change_pct != null ? ` (${w.change_pct}%)` : ""} since start</div>
     ${w.per_week != null ? `<p>Recent trend: ${w.per_week > 0 ? "+" : ""}${w.per_week} kg/week</p>` : ""}
     ${w.to_goal != null ? `<p class="muted">${w.to_goal > 0 ? w.to_goal + " kg to goal" : "Goal reached!"}</p>` : ""}`);

  $("#patterns").innerHTML = d.patterns.length ? d.patterns.map((p) =>
    `<div class="card pattern"><b>${esc(p.title)}</b>${esc(p.detail)}<div class="muted">${esc(p.suggestion)}</div></div>`).join("")
    : `<div class="card muted">Keep logging doses, meals and side effects. After a week or two GLPal will spot patterns, like which days or foods make you feel worse.</div>`;
}

$$("[data-water]").forEach((b) => b.addEventListener("click", async () => {
  await post("/api/water", { ml: Number(b.dataset.water) }); toast(`Added ${b.dataset.water} ml`); loadDashboard();
}));
document.addEventListener("click", (e) => {
  const a = e.target.closest("[data-ask]");
  if (a) { e.preventDefault(); show("coach"); ask(a.dataset.ask); }
});

// ---------- log ----------
$("#site-select").innerHTML = SITES.map((s) => `<option>${s}</option>`).join("");
$("#symptom-chips").innerHTML = SYMPTOMS.map((s) => `<button type="button" class="chip" data-sym="${s}">${s}</button>`).join("");
$("#symptom-chips").addEventListener("click", (e) => { const b = e.target.closest("[data-sym]"); if (b) $("#symptom-form").symptom.value = b.dataset.sym; });
$("#symptom-form").severity.addEventListener("input", (e) => ($("#sev-label").textContent = `${e.target.value} / 5`));

$("#estimate-btn").addEventListener("click", async () => {
  const f = $("#meal-form"), btn = $("#estimate-btn"), out = $("#estimate-out");
  const fd = new FormData();
  fd.append("description", f.description.value);
  if (f.photo.files[0]) fd.append("photo", f.photo.files[0]);
  btn.disabled = true; btn.textContent = "Estimating…";
  try {
    const r = await api("/api/meals/estimate", { method: "POST", body: fd });
    if (typeof r.protein_g === "number") f.protein_g.value = r.protein_g;
    if (typeof r.calories === "number") f.calories.value = r.calories;
    f.high_fat.checked = !!r.high_fat;
    const items = (r.items || []).map((i) => `${esc(i.name)} (${i.protein_g} g)`).join(", ");
    const numbers = typeof r.protein_g === "number"
      ? `Estimate: ${r.protein_g} g protein · ${r.calories} kcal · confidence ${esc(r.confidence)}${r.mode === "offline-table" ? " (offline estimate)" : ""}`
      : `No estimate available · confidence ${esc(r.confidence)}`;
    out.innerHTML = `<p class="items">${items || "No foods recognised. Enter numbers by hand."}</p>
      <p>${numbers}</p>
      ${r.tip ? `<p>💡 ${esc(r.tip)}</p>` : ""}${r.note ? `<p>${esc(r.note)}</p>` : ""}<p>You can adjust the numbers before saving.</p>`;
  } catch (err) { out.textContent = err.message; }
  btn.disabled = false; btn.textContent = "Estimate with AI";
});

function bindForm(id, path, label, after) {
  $(id).addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const body = formData(e.target);
      if (path === "/api/meals" && !body.description) body.description = "Meal";
      if (path === "/api/meals") body.source = $("#estimate-out").textContent.trim() ? "ai-estimate" : "manual";
      await post(path, body); toast(`${label} saved`); e.target.reset(); after && after();
    } catch (err) { toast(err.message); }
  });
}
bindForm("#meal-form", "/api/meals", "Meal", () => ($("#estimate-out").innerHTML = ""));
bindForm("#symptom-form", "/api/symptoms", "Side effect", () => ($("#sev-label").textContent = "3 / 5"));
bindForm("#dose-form", "/api/doses", "Dose", prefillDose);
bindForm("#weight-form", "/api/weights", "Weight");

async function prefillDose() {
  const d = await api("/api/dashboard");
  const f = $("#dose-form");
  f.medication.value = d.profile.medication || "wegovy";
  f.dose_mg.value = d.profile.current_dose_mg || "";
  if (d.dose.suggested_site) f.site.value = d.dose.suggested_site;
}

// ---------- coach ----------
$("#coach-suggestions").innerHTML = QUESTIONS.map((q) => `<button type="button" class="chip" data-q="${esc(q)}">${esc(q)}</button>`).join("");
$("#coach-suggestions").addEventListener("click", (e) => { const b = e.target.closest("[data-q]"); if (b) ask(b.dataset.q); });
$("#coach-form").addEventListener("submit", (e) => { e.preventDefault(); const q = e.target.question.value.trim(); if (q) { e.target.reset(); ask(q); } });

function addMsg(html, cls) {
  const div = document.createElement("div"); div.className = `msg ${cls}`; div.innerHTML = html;
  $("#chat").appendChild(div); div.scrollIntoView({ behavior: "smooth", block: "end" }); return div;
}

const chatHistory = [];   // recent turns, so the coach can follow the conversation

async function ask(q) {
  addMsg(esc(q), "user");
  const pending = addMsg("…", "bot");
  try {
    const r = await post("/api/coach", { question: q, use_my_data: $("#use-data").checked, history: chatHistory.slice(-8) });
    chatHistory.push({ role: "user", text: q }, { role: "assistant", text: r.answer });
    const body = esc(r.answer).replace(/\[(\d+)\]/g, '<sup class="cite-ref">[$1]</sup>');
    const cites = (r.citations || []).map((c) => `<details><summary><b>[${c.n}]</b> ${esc(c.title)} · ${esc(c.source)}${c.section ? `, ${esc(c.section)}` : ""}</summary>
      <p>“${esc(c.quote)}”</p>${c.url ? `<a href="${esc(c.url)}" target="_blank" rel="noopener">Open source</a>` : ""}</details>`).join("");
    pending.className = `msg bot ${r.kind === "urgent" ? "urgent" : ""}`;
    const caution = r.caution ? `<div class="caution">⚠️ ${esc(r.caution)}</div>` : "";
    const disc = r.kind === "chat" ? "" : `<div class="disc">${esc(r.disclaimer)}</div>`;   // no disclaimer under small talk
    pending.innerHTML = body + caution + (cites ? `<div class="cites"><b>Sources</b>${cites}</div>` : "") + disc;
  } catch (err) { pending.textContent = `Sorry, something went wrong: ${err.message}`; }
}

// ---------- history ----------
async function loadHistory() {
  const [doses, symptoms, meals, weights] = await Promise.all(["doses", "symptoms", "meals", "weights"].map((t) => api(`/api/${t}?days=30`)));
  const rows = [
    ...doses.map((r) => ({ t: r.taken_at, table: "doses", id: r.id, text: `💉 ${r.medication} ${r.dose_mg} mg${r.site ? " · " + r.site : ""}` })),
    ...symptoms.map((r) => ({ t: r.logged_at, table: "symptoms", id: r.id, text: `🤢 ${r.symptom} ${r.severity}/5` })),
    ...meals.map((r) => ({ t: r.eaten_at, table: "meals", id: r.id, text: `🍽️ ${r.description} · ${r.protein_g} g protein` })),
    ...weights.map((r) => ({ t: r.measured_at, table: "weights", id: r.id, text: `⚖️ ${r.weight_kg} kg` })),
  ].sort((a, b) => b.t.localeCompare(a.t)).slice(0, 60);
  $("#history").innerHTML = rows.length ? rows.map((r) => `<div class="card entry"><div>${esc(r.text)}<div class="muted">${esc(r.t.replace("T", " ").slice(0, 16))}</div></div>
    <button data-del="${r.table}/${r.id}" title="Delete">✕</button></div>`).join("") : `<div class="card muted">Nothing logged yet.</div>`;
}
$("#history").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-del]"); if (!b) return;
  await api(`/api/${b.dataset.del}`, { method: "DELETE" }); toast("Deleted"); loadHistory();
});

// ---------- settings ----------
async function loadSettings() {
  const [p, s] = await Promise.all([api("/api/profile"), api("/api/sources")]);
  const f = $("#profile-form");
  for (const k of ["name", "start_weight_kg", "goal_weight_kg", "protein_target_g", "water_target_ml"]) f[k].value = p[k] ?? "";
  updateProteinHint();
  $("#source-list").innerHTML = Object.values(s.sources).map((x) => `<li><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.name)}</a></li>`).join("")
    + `<li class="muted">${s.cards.length} passages in the library</li>`;
}
function updateProteinHint() {
  const w = Number($("#profile-form").start_weight_kg.value);
  $("#protein-hint").textContent = w ? `For ${w} kg, the 2025 nutrition advisory's ranges work out to about ${Math.round(w * 0.8)} g/day (RDA) up to ${Math.round(w * 1.6)} g/day (1.6 g/kg, proposed during weight loss), or a simple 80-120 g/day. Ask your clinician which fits you.` : "";
}
$("#profile-form").start_weight_kg.addEventListener("input", updateProteinHint);
$("#profile-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = formData(e.target);
  for (const k of Object.keys(body)) if (body[k] === "") delete body[k];
  try { await api("/api/profile", { method: "PUT", body: JSON.stringify(body) }); toast("Profile saved"); } catch (err) { toast(err.message); }
});

// ---------- start ----------
(async () => {
  const s = await api("/api/status");
  $("#ai-badge").textContent = s.ai_provider === "mock" ? "AI: offline mode" : `AI: ${s.ai_provider}`;
  applyDisclosure(s.ai_provider);
  prefillDose();
  let tab = "today"; try { tab = localStorage.getItem("glpal-tab") || "today"; } catch {}
  show(tab);
})();

// ---------- privacy disclosure ----------
function applyDisclosure(provider) {
  const real = provider && provider !== "mock";
  const coach = $("#ai-disclosure"), meal = $("#meal-disclosure");
  if (coach) coach.textContent = real
    ? `With an AI key set, your question and, if you allow it, your recent logs are sent to ${provider} to answer. With no key, nothing leaves this computer.`
    : "Offline mode: nothing leaves this computer.";
  if (meal) meal.textContent = real
    ? `With an AI key set, your meal description and photo are sent to ${provider} to estimate. With no key, nothing leaves this computer.`
    : "Offline mode: nothing leaves this computer.";
  const useData = $("#use-data");
  if (useData && real) useData.checked = false;   // log-sharing is opt-in when a real provider is active
}
