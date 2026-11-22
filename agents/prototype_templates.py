"""
Fixed files of every generated prototype (written by code, not by AI), plus
the built-in fallback prototype used when the AI cannot write working code.

- main.py   : FastAPI server, serves the page, logs every request for the monitor.
- base.css  : one small flat stylesheet the AI-written page uses (no outside fonts).
- fallback  : a small "MVP planner" app built from the PRD's requirements, so the
              build, test, run and monitor steps can still be shown honestly
              (it is labelled as a fallback everywhere).
"""

from typing import Any, Dict, List

MAIN_PY = '''"""
Prototype server (fixed template written by the Prototype Builder, not by AI).
Serves the page and the API router in features.py, and logs every request to
requests.log so the Co-Pilot can monitor the running app.
"""
import json
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from features import router

HERE = Path(__file__).resolve().parent
LOG = HERE / "requests.log"
TITLE = {title!r}

# The page may only load files and call APIs from this app.
CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; "
    "frame-ancestors 'self' http://127.0.0.1:* http://localhost:*"
)

app = FastAPI(title=TITLE, version="0.1.0")
app.include_router(router)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


@app.middleware("http")
async def monitor(request: Request, call_next):
    started = time.time()
    error = ""
    try:
        response = await call_next(request)
    except Exception as err:  # logged for the monitor, then a plain 500
        error = f"{{type(err).__name__}}: {{err}}"
        response = JSONResponse({{"detail": "Internal server error"}}, status_code=500)
    response.headers["Content-Security-Policy"] = CSP
    entry = {{
        "t": round(started, 3),
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "ms": int((time.time() - started) * 1000),
    }}
    if request.headers.get("x-prototype-check"):
        entry["check"] = True
    if error:
        entry["error"] = error
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\\n")
    return response


@app.get("/health")
def health():
    return {{"status": "ok", "app": TITLE}}


@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")
'''

BASE_CSS = """/* Prototype stylesheet (fixed file). Flat and plain on purpose; colours come from the theme. */
:root { --accent: #1f6feb; --bg: #f6f7f9; --soft: #eef1f4; --card: #fff; --text: #1f2328; --muted: #656d76; --line: #dde1e6; --radius: 6px; }
[data-theme="teal"] { --accent: #0f766e; --bg: #f2f7f6; --soft: #e1efec; }
[data-theme="amber"] { --accent: #b45309; --bg: #faf7f2; --soft: #f5ead9; }
[data-theme="indigo"] { --accent: #4338ca; --bg: #f5f5fa; --soft: #e7e7f6; }
[data-theme="green"] { --accent: #15803d; --bg: #f3f8f4; --soft: #e0efe3; }
[data-theme="rose"] { --accent: #be123c; --bg: #faf5f6; --soft: #f5e1e6; }
[data-theme="slate"] { --accent: #334155; --bg: #f4f5f7; --soft: #e3e7ec; --radius: 2px; }
[data-theme="orange"] { --accent: #c2410c; --bg: #f8f6f4; --soft: #f3e6dc; }
* { box-sizing: border-box; }
body { margin: 0; font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; color: var(--text); background: var(--bg); }
.top { background: var(--card); border-bottom: 1px solid var(--line); }
.top .wrap { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 14px; padding-bottom: 14px; flex-wrap: wrap; }
[data-header="accent"] .top { background: var(--accent); border-color: var(--accent); color: #fff; }
[data-header="dark"] .top { background: #1f2328; border-color: #1f2328; color: #fff; }
[data-header="accent"] .top .muted, [data-header="dark"] .top .muted { color: rgba(255, 255, 255, 0.78); }
.brand { font-weight: 700; font-size: 17px; }
.wrap { max-width: 1040px; margin: 0 auto; padding: 0 16px; }
main.wrap { padding-top: 20px; padding-bottom: 40px; }
h1 { font-size: 24px; margin: 0 0 4px; }
h2 { font-size: 16px; margin: 0 0 10px; }
p { margin: 0 0 10px; }
.muted { color: var(--muted); font-size: 13px; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); padding: 16px; margin-bottom: 16px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; }
.cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(300px, 100%), 1fr)); gap: 16px; }
.cols > *, .side-layout > *, .grid > * { min-width: 0; }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.stat { font-size: 26px; font-weight: 700; }
.accent-line { border-top: 3px solid var(--accent); }
.field { display: flex; flex-direction: column; gap: 4px; margin-bottom: 10px; font-size: 13px; color: var(--muted); }
input, select, textarea { font: inherit; color: inherit; padding: 8px 10px; border: 1px solid #c9ced4; border-radius: 4px; background: #fff; width: 100%; }
textarea { min-height: 70px; }
.btn { font: inherit; padding: 8px 14px; border: 1px solid #c9ced4; border-radius: 4px; background: #fff; cursor: pointer; }
.btn:hover { background: var(--soft); }
.btn.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.btn.primary:hover { filter: brightness(0.92); background: var(--accent); }
.btn.small { padding: 4px 10px; font-size: 13px; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { text-align: left; padding: 8px 6px; border-bottom: 1px solid #eceef1; vertical-align: top; }
th { color: var(--muted); font-weight: 600; font-size: 13px; }
.list { list-style: none; padding: 0; margin: 0; }
.list li { padding: 10px 0; border-bottom: 1px solid #eceef1; }
.list-row { padding: 8px 0; border-bottom: 1px solid #eceef1; }
.list-row:last-child { border-bottom: 0; }
.bar { height: 6px; background: var(--soft); border-radius: 3px; margin-top: 6px; }
.bar > span { display: block; height: 100%; background: var(--accent); border-radius: 3px; }
.tag { display: inline-block; padding: 1px 8px; border-radius: 4px; font-size: 12px; background: #eef1f4; color: #424a53; }
.tag.good { background: #dafbe1; color: #116329; }
.tag.warn { background: #fff8c5; color: #7d4e00; }
.tag.bad { background: #ffebe9; color: #a40e26; }
.empty { color: var(--muted); padding: 12px 0; }
.error { color: #a40e26; font-size: 13px; }
/* Layout "sidebar": form and side panel on the left, numbers and records on the right. */
.side-layout { display: grid; grid-template-columns: 330px 1fr; gap: 16px; align-items: start; }
.side-layout aside .card:first-child { border-top: 3px solid var(--accent); }
/* Layout "banner": a coloured band with the title and the numbers, then a one-row form. */
.banner { background: var(--accent); color: #fff; padding: 28px 0 70px; }
.banner .muted { color: rgba(255, 255, 255, 0.8); font-size: 14px; }
.banner-stats { margin-top: -54px; }
.banner-stats .card { box-shadow: none; }
.form-inline { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; align-items: end; }
.form-inline .field { margin-bottom: 0; }
.form-inline .field:has(textarea) { grid-column: 1 / -1; }
h3 { font-size: 14px; margin: 14px 0 6px; }
.spread { justify-content: space-between; }
.bar.neg > span { background: #cf222e; }
.stars { white-space: nowrap; }
.stars b { color: #b45309; font-weight: 400; }
.stars i { color: #d0d4d9; font-style: normal; }
tbody tr:hover { background: var(--soft); }
td select { width: auto; min-width: 96px; padding: 4px 6px; }
.ok { color: #116329; font-size: 13px; }
.save { color: #116329; font-size: 12px; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn.wide { width: 100%; }
.site-foot { color: var(--muted); font-size: 12px; padding-top: 4px; padding-bottom: 28px; }
/* Main views: readings chart, results grid, board, day planner. */
.alerts { display: grid; gap: 6px; margin-bottom: 12px; }
.alert-item { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; text-align: left; font: inherit; font-size: 14px; padding: 8px 10px;
  border: 1px solid #ffcecb; background: #fff6f5; border-radius: 4px; cursor: pointer; color: var(--text); }
.chart { position: relative; margin: 10px 0 6px; }
.chart svg { width: 100%; height: auto; display: block; }
.chart .axis { fill: var(--muted); font-size: 11px; }
.chart .grid-line { stroke: #eceef1; stroke-width: 1; }
.chart .avg-line { stroke: var(--text); stroke-width: 1.5; stroke-dasharray: 5 4; opacity: 0.6; }
.tip { position: absolute; top: 0; transform: translateX(-50%); background: var(--text); color: #fff; font-size: 12px; padding: 4px 8px; border-radius: 4px; white-space: nowrap; pointer-events: none; }
.legend { gap: 6px 10px; font-size: 13px; }
.swatch { display: inline-block; width: 10px; height: 10px; border-radius: 2px; }
.swatch.dash { height: 0; width: 16px; border-top: 2px dashed var(--text); opacity: 0.6; border-radius: 0; }
.matrix { font-size: 13px; }
.matrix th { font-size: 12px; vertical-align: bottom; }
.matrix tr { cursor: pointer; }
.matrix tr.on td { background: var(--soft); }
.matrix td.cell { text-align: center; font-size: 12px; }
.matrix td.score { white-space: nowrap; }
.matrix td.cell.good { color: #116329; }
.matrix td.cell.bad { color: #a40e26; background: #fff6f5; }
.viewer { margin-top: 14px; }
.code { font: 13px/1.6 Consolas, Menlo, monospace; border: 1px solid var(--line); border-radius: 4px; overflow-x: auto; background: #fafbfc; }
.code .line { display: flex; gap: 12px; padding: 0 10px; white-space: pre; }
.code .line.flag { background: #fff1f0; }
.code .ln { color: var(--muted); min-width: 22px; text-align: right; user-select: none; }
.code .why { margin-left: auto; padding-left: 16px; color: #a40e26; font-family: system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; font-size: 12px; }
.board { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; }
.lane { background: var(--soft); border-radius: var(--radius); padding: 10px; display: flex; flex-direction: column; gap: 8px; }
.lane-head { margin-bottom: 2px; }
.ticket { background: var(--card); border: 1px solid var(--line); border-radius: 4px; padding: 10px; display: flex; flex-direction: column; gap: 6px; align-items: flex-start; font-size: 14px; }
.planner { font-size: 13px; }
.planner th { white-space: nowrap; }
.planner td { padding: 4px; }
.booked { display: block; background: var(--soft); border-left: 3px solid var(--accent); padding: 4px 8px; border-radius: 2px; font-size: 12px; }
.btn.free { width: 100%; color: #116329; border-style: dashed; }
/* Layout "store" (shop): catalogue with filters, a cart that is priced on the server, orders. */
.mark { display: inline-flex; align-items: center; justify-content: center; width: 30px; height: 30px; margin-right: 10px; border-radius: 4px;
  background: var(--accent); color: #fff; font-size: 13px; vertical-align: middle; }
[data-header="accent"] .mark { background: #fff; color: var(--accent); }
.store-top .wrap { flex-wrap: nowrap; }
.store-top input[type="search"] { flex: 1; max-width: 440px; }
[data-header="dark"] .store-top input, [data-header="accent"] .store-top input { background: rgba(255, 255, 255, 0.1); border-color: rgba(255, 255, 255, 0.28); color: #fff; }
[data-header="dark"] .store-top input::placeholder, [data-header="accent"] .store-top input::placeholder { color: rgba(255, 255, 255, 0.7); }
.cart-btn { white-space: nowrap; text-decoration: none; color: var(--text); }
.hero { background: var(--soft); border-bottom: 1px solid var(--line); padding: 26px 0; }
.hero .wrap { display: grid; grid-template-columns: 1fr 1.6fr; gap: 24px; align-items: center; }
.hero h1 { font-size: 26px; }
.facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; }
.fact { background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); padding: 10px 12px; font-size: 13px; }
.fact b { display: block; color: var(--accent); font-size: 12px; }
.stats { grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
.stats .card { border-top: 3px solid var(--accent); }
.store { display: grid; grid-template-columns: 1fr 340px; gap: 16px; align-items: start; margin-bottom: 16px; }
.store > * { min-width: 0; }
.tabs { display: flex; gap: 2px; border-bottom: 1px solid var(--line); margin-bottom: 12px; overflow-x: auto; }
.tabs button { font: inherit; font-size: 14px; background: none; border: 0; border-bottom: 2px solid transparent; padding: 8px 12px; cursor: pointer; color: var(--muted); white-space: nowrap; }
.tabs button.on { color: var(--text); border-bottom-color: var(--accent); font-weight: 600; }
.filters { margin-bottom: 12px; }
.filters select { width: auto; padding: 6px 8px; font-size: 14px; }
.filters .count { margin-left: auto; }
.products { display: grid; grid-template-columns: repeat(auto-fill, minmax(205px, 1fr)); gap: 14px; }
.product { background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); display: flex; flex-direction: column; overflow: hidden; }
.product:hover { border-color: var(--accent); }
.thumb { background: var(--soft); height: 124px; display: flex; align-items: center; justify-content: center; border-bottom: 1px solid var(--line); }
.thumb svg { width: 156px; height: 104px; }
.thumb .acc { fill: var(--accent); }
.thumb .hl { fill: none; stroke: #fff; opacity: 0.3; }
.p-body { padding: 12px; display: flex; flex-direction: column; gap: 6px; flex: 1; }
.p-body h3 { font-size: 15px; margin: 0; line-height: 1.35; }
.price strong { font-size: 20px; }
.buy { margin-top: auto; padding-top: 6px; display: grid; grid-template-columns: 74px 1fr; gap: 8px; }
.qty { width: 74px; padding: 6px 8px; }
.cart { position: sticky; top: 12px; border-top: 3px solid var(--accent); }
.cart-line { display: grid; grid-template-columns: 1fr auto; gap: 6px 10px; padding: 10px 0; border-bottom: 1px solid #eceef1; font-size: 14px; }
.cart-line .row { grid-column: 1 / -1; }
.cart-line .amount { text-align: right; }
#totals { padding: 8px 0; }
.total-row { display: flex; justify-content: space-between; padding: 3px 0; font-size: 14px; }
.total-row.save { font-size: 14px; }
.total-row.grand { border-top: 1px solid var(--line); margin-top: 6px; padding-top: 8px; font-weight: 700; font-size: 18px; }
@media (max-width: 860px) { .store, .hero .wrap { grid-template-columns: 1fr; } .cart { position: static; } .store-top .wrap { flex-wrap: wrap; } }
@media (max-width: 480px) { .store-top input[type="search"] { order: 3; flex-basis: 100%; max-width: none; } .products { grid-template-columns: 1fr 1fr; gap: 10px; } .thumb { height: 96px; } .thumb svg { width: 120px; height: 80px; }
  .buy { grid-template-columns: 1fr; } .qty { width: 100%; } .p-body { padding: 10px; } .price strong { font-size: 17px; } .filters .count { margin-left: 0; } }
@media (max-width: 760px) { .side-layout { grid-template-columns: 1fr; } }
"""

# Classes the AI is told it may use (kept next to the stylesheet so they agree).
CSS_CLASSES = (
    "top, wrap, brand, card, grid, row, stat, field, btn, btn primary, btn small, "
    "muted, list, tag, tag good, tag warn, tag bad, empty, error, cols, list-row, bar, accent-line, spread, ok; plain table/th/td"
)

README = """# {title}

A small generated prototype (FastAPI + one HTML page) made by the Boost Your Startup
Prototype Builder from the PRD's top requirements. It is a starting point, not a product.

Files: main.py (fixed template), features.py, static/index.html and test_features.py
({source}), static/base.css (fixed template).

Run it:

    pip install fastapi uvicorn pytest httpx
    uvicorn main:app --port 8100
    pytest -q
"""


def fallback_files(spec: Dict[str, Any]) -> Dict[str, str]:
    """A working MVP-planner prototype built in code from the spec (no AI)."""
    requirements: List[Dict[str, str]] = spec.get("requirements") or []
    seed = [
        {"id": i + 1, "title": r.get("title", f"Requirement {i + 1}")[:80],
         "detail": r.get("description", "")[:200], "priority": r.get("priority", "Must Have"),
         "status": "planned"}
        for i, r in enumerate(requirements[:5])
    ]
    overview = {
        "title": spec.get("title", "Prototype"),
        "problem": spec.get("problem", ""),
        "users": spec.get("personas", [])[:3],
    }
    features = f'''"""MVP planner API (built-in starter app, written by code, not by AI)."""
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api")

OVERVIEW = {overview!r}
STATUSES = ["planned", "building", "done"]
ITEMS = {seed!r}


class NewItem(BaseModel):
    title: str = Field(min_length=3, max_length=80)
    detail: str = Field(default="", max_length=200)
    priority: str = "Must Have"


class StatusChange(BaseModel):
    status: str


@router.get("/overview")
def get_overview():
    return OVERVIEW


@router.get("/items")
def list_items(status: Optional[str] = None) -> List[dict]:
    if status and status not in STATUSES:
        raise HTTPException(status_code=422, detail="Unknown status")
    return [item for item in ITEMS if not status or item["status"] == status]


@router.post("/items", status_code=201)
def add_item(new: NewItem):
    item = {{"id": max([i["id"] for i in ITEMS], default=0) + 1, "status": "planned", **new.model_dump()}}
    ITEMS.append(item)
    return item


@router.patch("/items/{{item_id}}")
def change_status(item_id: int, change: StatusChange):
    if change.status not in STATUSES:
        raise HTTPException(status_code=422, detail="Unknown status")
    for item in ITEMS:
        if item["id"] == item_id:
            item["status"] = change.status
            return item
    raise HTTPException(status_code=404, detail="Item not found")


@router.get("/stats")
def stats():
    counts = {{s: sum(1 for i in ITEMS if i["status"] == s) for s in STATUSES}}
    done = counts["done"]
    return {{"total": len(ITEMS), "by_status": counts,
            "progress": round(100 * done / len(ITEMS)) if ITEMS else 0}}
'''
    tests = '''from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health():
    assert client.get("/health").json()["status"] == "ok"


def test_overview_has_title():
    assert client.get("/api/overview").json()["title"]


def test_add_and_list_item():
    created = client.post("/api/items", json={"title": "Login page"})
    assert created.status_code == 201
    ids = [i["id"] for i in client.get("/api/items").json()]
    assert created.json()["id"] in ids


def test_change_status_and_stats():
    item = client.post("/api/items", json={"title": "Export to CSV"}).json()
    assert client.patch(f"/api/items/{item['id']}", json={"status": "done"}).json()["status"] == "done"
    assert client.get("/api/stats").json()["by_status"]["done"] >= 1


def test_unknown_item_is_404():
    assert client.patch("/api/items/9999", json={"status": "done"}).status_code == 404


def test_short_title_rejected():
    assert client.post("/api/items", json={"title": "x"}).status_code == 422
'''
    page = '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prototype</title>
<link rel="stylesheet" href="/static/base.css">
</head>
<body>
<header class="top"><div class="wrap"><span class="brand" id="brand">Prototype</span><span class="muted">MVP planner (built-in template)</span></div></header>
<main class="wrap">
  <div class="card"><h1 id="title"></h1><p class="muted" id="problem"></p></div>
  <div class="grid">
    <div class="card"><div class="muted">Requirements</div><div class="stat" id="total">0</div></div>
    <div class="card"><div class="muted">Done</div><div class="stat" id="done">0</div></div>
    <div class="card"><div class="muted">Progress</div><div class="stat" id="progress">0%</div></div>
  </div>
  <div class="card">
    <h2>Add a requirement</h2>
    <form id="form" class="row">
      <input id="newTitle" placeholder="For example: user sign up" style="flex:1;min-width:200px">
      <button class="btn primary" type="submit">Add</button>
    </form>
    <p class="error" id="formError"></p>
  </div>
  <div class="card"><h2>Requirements</h2><table><thead><tr><th>#</th><th>Requirement</th><th>Priority</th><th>Status</th></tr></thead><tbody id="rows"></tbody></table></div>
</main>
<script>
const STATUSES = ["planned", "building", "done"];
const TONE = { planned: "tag", building: "tag warn", done: "tag good" };
async function api(path, options) {
  const res = await fetch(path, Object.assign({ headers: { "Content-Type": "application/json" } }, options));
  if (!res.ok) throw new Error((await res.json()).detail || res.status);
  return res.json();
}
function cell(text) { const td = document.createElement("td"); td.textContent = text; return td; }
async function load() {
  const [items, stats] = await Promise.all([api("/api/items"), api("/api/stats")]);
  document.getElementById("total").textContent = stats.total;
  document.getElementById("done").textContent = stats.by_status.done;
  document.getElementById("progress").textContent = stats.progress + "%";
  const rows = document.getElementById("rows");
  rows.replaceChildren();
  for (const item of items) {
    const tr = document.createElement("tr");
    tr.append(cell(item.id), cell(item.title), cell(item.priority));
    const td = document.createElement("td");
    const select = document.createElement("select");
    for (const s of STATUSES) { const o = document.createElement("option"); o.value = s; o.textContent = s; o.selected = s === item.status; select.append(o); }
    select.onchange = async () => { await api("/api/items/" + item.id, { method: "PATCH", body: JSON.stringify({ status: select.value }) }); load(); };
    td.append(select); tr.append(td); rows.append(tr);
  }
}
document.getElementById("form").onsubmit = async (e) => {
  e.preventDefault();
  const input = document.getElementById("newTitle");
  try { await api("/api/items", { method: "POST", body: JSON.stringify({ title: input.value }) }); input.value = ""; document.getElementById("formError").textContent = ""; load(); }
  catch (err) { document.getElementById("formError").textContent = "Could not add: " + err.message; }
};
api("/api/overview").then((o) => {
  document.getElementById("brand").textContent = o.title;
  document.getElementById("title").textContent = o.title;
  document.getElementById("problem").textContent = o.problem;
  document.title = o.title;
});
load();
</script>
</body>
</html>
'''
    return {"features.py": features, "static/index.html": page, "test_features.py": tests}
