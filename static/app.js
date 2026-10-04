const $ = (id) => document.getElementById(id);
let selected = null;

const fmt = (iso) => new Date(iso + "T00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" });
const addDays = (iso, n) => { const d = new Date(iso + "T00:00"); d.setDate(d.getDate() + n); return d.toLocaleDateString("en-CA"); };
const today = new Date().toLocaleDateString("en-CA");
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const body = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, body };
}

function errorText(body) {
  if (Array.isArray(body.detail)) return body.detail.map((d) => d.msg).join(", ");
  return body.detail || "Something went wrong";
}

async function loadEquipment() {
  const { body } = await api("/api/equipment");
  $("equipment").innerHTML = body.map((e) => `
    <button class="item" data-id="${e.id}">
      <div class="name">${esc(e.name)}</div>
      <div class="meta">₹${e.daily_rate}/day · ${e.total_units} unit${e.total_units > 1 ? "s" : ""}</div>
    </button>`).join("");
  document.querySelectorAll(".item").forEach((el) => el.addEventListener("click", () => {
    document.querySelectorAll(".item").forEach((x) => x.classList.remove("active"));
    el.classList.add("active");
    selected = Number(el.dataset.id);
    $("result").innerHTML = ""; $("book-card").classList.add("hidden");
    refresh();
  }));
}

async function check(e) {
  e?.preventDefault();
  if (!selected) { $("result").innerHTML = `<div class="msg bad">Pick an item first.</div>`; return; }
  const q = new URLSearchParams({ equipment_id: selected, start: $("start").value, end: $("end").value });
  const { ok, body } = await api(`/api/availability?${q}`);
  $("book-result").innerHTML = "";
  if (!ok) { $("result").innerHTML = `<div class="msg bad">${esc(errorText(body))}</div>`; return; }

  if (body.available) {
    $("result").innerHTML = `<div class="msg ok">✓ ${body.free_units} of ${body.total_units} unit(s) free for ${body.days} day(s).
      Estimated cost <b>₹${body.estimated_cost}</b>.</div>`;
    $("book-card").classList.remove("hidden");
  } else {
    $("book-card").classList.add("hidden");
    $("result").innerHTML = `<div class="msg bad">✗ Fully booked for those dates. Next free ${body.days}-day slots:
      <div class="chips">${suggestionChips(body.suggestions)}</div></div>`;
    bindChips();
  }
}

function suggestionChips(list) {
  return list.map((s) => `<button class="chip" data-start="${s.start}" data-end="${s.end}">${fmt(s.start)} → ${fmt(s.end)}</button>`).join("");
}

function bindChips() {
  document.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => {
    $("start").value = c.dataset.start; $("end").value = c.dataset.end; check();
  }));
}

async function book(e) {
  e.preventDefault();
  const payload = { equipment_id: selected, customer_name: $("name").value, customer_phone: $("phone").value,
                    start: $("start").value, end: $("end").value };
  const { ok, status, body } = await api("/api/bookings", { method: "POST", body: JSON.stringify(payload) });
  if (ok) {
    $("book-result").innerHTML = `<div class="msg ok">Booked! #${body.id} · unit <b>${esc(body.serial_no)}</b> · ₹${body.total_cost}</div>`;
    $("book-form").reset();
  } else if (status === 409) {
    $("book-result").innerHTML = `<div class="msg bad">Someone just took the last unit. Try:
      <div class="chips">${suggestionChips(body.suggestions)}</div></div>`;
    bindChips();
  } else {
    $("book-result").innerHTML = `<div class="msg bad">${esc(errorText(body))}</div>`;
  }
  refresh();
}

async function refresh() {
  if (!selected) return;
  const [cal, list] = await Promise.all([
    api(`/api/equipment/${selected}/calendar?days=60`),
    api(`/api/bookings?equipment_id=${selected}`),
  ]);
  const c = cal.body;
  const full = new Set();
  c.fully_booked.forEach((r) => { for (let d = r.start; d < r.end; d = addDays(d, 1)) full.add(d); });
  let cells = "";
  for (let i = 0; i < 60; i++) { const d = addDays(c.from, i); cells += `<span class="${full.has(d) ? "full" : ""}" title="${d}"></span>`; }
  $("calendar").innerHTML = `
    <div class="strip">${cells}</div>
    <p class="muted">${fmt(c.from)} – ${fmt(c.to)} · red = all ${c.total_units} unit(s) out · peak demand: ${c.peak_concurrent_bookings}</p>
    ${c.fully_booked.length ? `<p>Fully booked: ${c.fully_booked.map((r) => `${fmt(r.start)} → ${fmt(r.end)}`).join(", ")}</p>` : ""}`;

  $("bookings").innerHTML = list.body.length ? `<table><tr><th>#</th><th>Customer</th><th>Unit</th><th>Pickup</th><th>Return</th><th></th></tr>
    ${list.body.map((b) => `<tr><td>${b.id}</td><td>${esc(b.customer_name)}</td><td>${esc(b.serial_no)}</td>
      <td>${fmt(b.start_date)}</td><td>${fmt(b.end_date)}</td>
      <td><button class="link" data-cancel="${b.id}">Cancel</button></td></tr>`).join("")}</table>`
    : `<p class="muted">No bookings yet.</p>`;
  document.querySelectorAll("[data-cancel]").forEach((b) => b.addEventListener("click", async () => {
    await api(`/api/bookings/${b.dataset.cancel}`, { method: "DELETE" }); refresh();
  }));
}

$("start").min = $("end").min = today;
$("start").value = addDays(today, 1);
$("end").value = addDays(today, 4);
$("check-form").addEventListener("submit", check);
$("book-form").addEventListener("submit", book);
loadEquipment();
