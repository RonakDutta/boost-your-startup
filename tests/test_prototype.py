"""Prototype Builder: safety gate, AI path, one repair, labelled fallback, API (hermetic: AI stubbed)."""

import collections
import io
import json
import os
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from agents import prototype_agent
from agents import prototype_blueprints as blueprints
from agents.prototype_agent import build_spec, parse_files, prototype_builder
from agents.prototype_templates import fallback_files
from agents.workflow_state import AgentWorkflowState
from core.llm import llm_client
from tools import prototype_sandbox

IDEA = {
    "type": "idea_validation",
    "project_title": "Tractor Share",
    "problem_statement": "Small farmers cannot afford their own tractor.",
    "target_personas": [{"name": "Small farmer"}, "Tractor owner"],
    "mvp_features": ["Book a tractor"],
    "prd": {"functional_requirements": [
        {"req_id": "FR-03", "title": "Ratings", "description": "Rate a booking", "priority": "Nice to Have"},
        {"req_id": "FR-01", "title": "List tractors", "description": "Owners list tractors", "priority": "Must Have"},
        {"req_id": "FR-02", "title": "Book by the hour", "description": "Farmers book a slot", "priority": "Must Have"},
    ]},
}

GOOD_FEATURES = '''from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api")
TRACTORS = [{"id": 1, "name": "Mahindra 575", "rate": 400}, {"id": 2, "name": "Swaraj 744", "rate": 450}]
BOOKINGS = []


class Booking(BaseModel):
    tractor_id: int
    hours: int


@router.get("/tractors")
def tractors():
    return TRACTORS


@router.post("/bookings", status_code=201)
def book(booking: Booking):
    if booking.hours < 1:
        raise HTTPException(status_code=422, detail="hours must be positive")
    tractor = next((t for t in TRACTORS if t["id"] == booking.tractor_id), None)
    if tractor is None:
        raise HTTPException(status_code=404, detail="tractor not found")
    entry = {"id": len(BOOKINGS) + 1, "cost": tractor["rate"] * booking.hours, **booking.model_dump()}
    BOOKINGS.append(entry)
    return entry


@router.get("/bookings")
def bookings():
    return BOOKINGS
'''
GOOD_TESTS = '''from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_list():
    assert len(client.get("/api/tractors").json()) == 2


def test_book():
    assert client.post("/api/bookings", json={"tractor_id": 1, "hours": 2}).json()["cost"] == 800


def test_missing():
    assert client.post("/api/bookings", json={"tractor_id": 9, "hours": 2}).status_code == 404
'''
GOOD_PAGE = '<!doctype html><html><head><link rel="stylesheet" href="/static/base.css"></head><body><main class="wrap"><div class="card">Tractor Share</div></main></body></html>'


def answer(features=GOOD_FEATURES, page=GOOD_PAGE, tests=GOOD_TESTS):
    return (f"### FILE: features.py\n```python\n{features}\n```\n"
            f"### FILE: static/index.html\n```html\n{page}\n```\n"
            f"### FILE: test_features.py\n```python\n{tests}\n```\n")


@pytest.fixture(autouse=True)
def sandbox_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(prototype_sandbox, "PROTOTYPE_DIR", tmp_path / "protos")
    yield
    prototype_sandbox.processes.stop_all()


CUSTOM = '{"kind": "custom"}'


def build_with(monkeypatch, replies, design=CUSTOM, idea=None):
    """`replies` answer the code calls in order; `design` answers the app-design call (not counted in calls)."""
    calls = []

    def fake_generate(messages, *args, **kwargs):
        if messages[0]["content"] == blueprints.DESIGN_PROMPT:
            if isinstance(design, Exception):
                raise design
            return design
        calls.append(messages)
        reply = replies[min(len(calls), len(replies)) - 1]
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(llm_client, "generate", fake_generate)
    steps = []
    state = AgentWorkflowState(session_id="t", user_query="t", listener=steps.append)
    return prototype_builder.build(idea or IDEA, state), steps, calls


def test_spec_picks_must_have_first():
    spec = build_spec(IDEA)
    assert [r["id"] for r in spec["requirements"]] == ["FR-01", "FR-02", "FR-03"]
    assert spec["personas"] == ["Small farmer", "Tractor owner"]


def test_parse_files_reads_the_three_blocks():
    files = parse_files("Some intro\n" + answer())
    assert set(files) == set(prototype_agent.AI_FILES)
    assert files["features.py"].startswith("from fastapi")


def test_safety_check_blocks_unsafe_code():
    bad = {
        "features.py": "import os\nrouter = 1\neval('1')\nx = ().__class__\n",
        "static/index.html": '<script src="https://cdn.example.com/x.js"></script>',
        "test_features.py": "import subprocess\n",
    }
    issues = " ".join(prototype_sandbox.safety_check(bad))
    for word in ("'os'", "'eval'", "__class__", "outside scripts", "'subprocess'"):
        assert word in issues
    assert prototype_sandbox.safety_check({"features.py": "x = 1\n"}) == ["features.py: must define 'router = APIRouter(...)'."]


def test_safety_check_blocks_file_serving_and_reflection():
    for line in ("from fastapi.responses import FileResponse", "from fastapi.staticfiles import StaticFiles",
                 "import starlette.responses", "import fastapi\nx = fastapi.responses.FileResponse",
                 "import fastapi\nx = getattr(fastapi, 'staticfiles')"):
        issues = prototype_sandbox.safety_check({"features.py": f"{line}\nrouter = 1\n"})
        assert issues, line
    assert prototype_sandbox.safety_check({"features.py": "from fastapi.responses import JSONResponse\nrouter = 1\n"}) == []


def test_fallback_files_are_safe_and_compile():
    files = fallback_files(build_spec(IDEA))
    assert prototype_sandbox.safety_check(files) == []
    assert prototype_sandbox.compile_check(files) == []


def test_ai_build_runs_tests_and_starts_the_app(monkeypatch):
    build, steps, calls = build_with(monkeypatch, [answer()])
    assert len(calls) == 1  # one AI call, no fix needed
    assert build["generation_source"] == "llm" and not build["repaired"]
    assert build["checks"]["tests"]["passed"] == 3 and build["checks"]["tests"]["ok"]
    assert build["checks"]["server"]["ok"]
    paths = {e["path"]: e["status"] for e in build["checks"]["endpoints"]}
    assert paths["/"] == 200 and paths["/api/tractors"] == 200
    by = {f["path"]: f["written_by"] for f in build["files"]}
    assert by["features.py"] == "ai" and by["main.py"] == "template"
    names = [s["agent_name"] for s in steps]
    assert names[:2] == ["Spec Planner", "Code Writer"] and "Endpoint Checker" in names
    status = prototype_sandbox.processes.status(build["id"])
    assert status["state"] == "running" and status["requests_checks"] >= 3 and status["requests_visitors"] == 0


def test_broken_code_is_fixed_once_with_the_real_error(monkeypatch):
    broken = GOOD_FEATURES.replace("def tractors():", "def tractors(:")
    build, steps, calls = build_with(monkeypatch, [answer(features=broken), answer()])
    assert len(calls) == 2 and build["repaired"]
    assert "invalid syntax" in calls[1][-1]["content"] or "features.py:" in calls[1][-1]["content"]
    assert build["generation_source"] == "llm" and build["checks"]["tests"]["ok"]
    assert any(s["agent_name"] == "Code Fixer" and not s["details"].get("skipped") for s in steps)


def test_unsafe_code_falls_back_and_is_labelled(monkeypatch):
    unsafe = "import os\n" + GOOD_FEATURES
    build, steps, _ = build_with(monkeypatch, [answer(features=unsafe), answer(features=unsafe)])
    assert build["generation_source"] == "fallback" and "still failed" in build["fallback_reason"]
    assert build["checks"]["tests"]["ok"]  # the fallback prototype's own tests
    assert {f["written_by"] for f in build["files"]} == {"fallback", "template"}
    assert any(s["status"] == "warning" and s["agent_name"] == "Safety Check" for s in steps)


def test_api_build_stream_monitor_stop_and_download(monkeypatch):
    from agents.conversation_session import session_manager
    from tests.test_run_stream import _events
    from app import app

    session = session_manager.get_or_create_session("proto01")
    session.active_entities["final_output"] = IDEA
    monkeypatch.setattr(llm_client, "generate", lambda m, *a, **k: CUSTOM if m[0]["content"] == blueprints.DESIGN_PROMPT else answer())
    client = TestClient(app)

    assert client.post("/api/prototype/build/stream", json={"session_id": "nosuch"}).status_code == 404
    events = _events(client.post("/api/prototype/build/stream", json={"session_id": "proto01"}).text)
    assert events[0][0] == "start" and events[-1][0] == "result"
    build = events[-1][1]["final_output"]
    proto_id = build["id"]

    status = client.get(f"/api/prototype/{proto_id}/status").json()
    assert status["state"] == "running"
    assert client.get(f"/api/prototype/{proto_id}").json()["build"]["id"] == proto_id
    assert client.post(f"/api/prototype/{proto_id}/stop").json()["state"] == "stopped"

    archive = zipfile.ZipFile(io.BytesIO(client.get(f"/api/prototype/{proto_id}/download").content))
    names = {n.split("/", 1)[1] for n in archive.namelist()}
    assert {"main.py", "features.py", "static/index.html", "test_features.py"} <= names
    assert client.get("/api/prototype/../../etc/status").status_code == 404
    assert client.get("/api/prototype/zzzz/status").status_code == 404
    json.dumps(build)  # the build must be plain JSON


def test_parse_answer_tolerates_headings_and_drops_cut_off_files():
    loose = (f"**features.py**\n```python\n{GOOD_FEATURES}\n```\n"
             f"`static/index.html`:\n```html\n{GOOD_PAGE}\n```\n"
             f"### FILE: test_features.py\n```python\n{GOOD_TESTS[:80]}")  # answer hit its token limit
    files, cut = prototype_agent.parse_answer(loose)
    assert set(files) == {"features.py", "static/index.html"} and cut == ["test_features.py"]
    unnamed, _ = prototype_agent.parse_answer(f"```python\n{GOOD_TESTS}\n```")
    assert list(unnamed) == ["test_features.py"]  # named by its content


def test_page_check_finds_calls_to_missing_routes():
    page = 'fetch("/api/tractors"); api(`/api/bookings/${id}`); api("/api/bookings/" + id); fetch("/api/rentals")'
    features = GOOD_FEATURES + '\n\n@router.delete("/bookings/{booking_id}")\ndef cancel(booking_id: int):\n    return {}\n'
    issues = prototype_sandbox.page_api_check({"features.py": features, "static/index.html": page})
    assert len(issues) == 1 and "/api/rentals" in issues[0]
    assert prototype_sandbox.api_routes(GOOD_FEATURES) == ["/api/tractors", "/api/bookings", "/api/bookings"]


def test_missing_file_goes_to_the_fixer_not_the_fallback(monkeypatch):
    partial = answer().split("### FILE: test_features.py")[0]
    tests_only = f"### FILE: test_features.py\n```python\n{GOOD_TESTS}\n```\n"
    build, steps, calls = build_with(monkeypatch, [partial, tests_only])
    assert len(calls) == 2 and "Missing files: test_features.py" in calls[1][-1]["content"]
    assert build["generation_source"] == "llm" and build["repaired"] and build["checks"]["tests"]["ok"]


def test_page_calling_a_missing_route_is_sent_to_the_fixer(monkeypatch):
    bad_page = GOOD_PAGE.replace("</body>", '<script>fetch("/api/rentals")</script></body>')
    build, steps, calls = build_with(monkeypatch, [answer(page=bad_page), answer()])
    assert len(calls) == 2 and "/api/rentals" in calls[1][-1]["content"]
    assert build["checks"]["page_ok"] and build["checks"]["tests"]["ok"]
    assert any(s["agent_name"] == "Page Check" and s["status"] == "warning" for s in steps)


def test_sandbox_env_finds_installed_packages_without_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "secret")
    env = prototype_sandbox._sandbox_env(tmp_path)
    assert "GROQ_API_KEY" not in env and "HTTPS_PROXY" not in env
    assert any("site-packages" in p or "dist-packages" in p for p in env["PYTHONPATH"].split(os.pathsep))
    assert prototype_sandbox.runtime_check() == ""


def test_code_call_waits_for_a_full_budget_instead_of_shrinking():
    from core.llm import LLMClient
    client = LLMClient()
    model = client._get_candidate_models(None)[0]
    client._model_budget[model] = {"remaining_tokens": 2500, "reset_tokens_at": time.time() + 30}
    assert client._clamp_max_tokens(model, 4800, 1500) is not None  # normal calls shrink
    assert client._clamp_max_tokens(model, 4800, 1500, min_answer=4000) is None  # code calls wait
    client._model_budget.clear()
    assert client._clamp_max_tokens(model, 4800, 1500, min_answer=4000) == 4800  # not cut to MAX_TOKENS_CAP


def test_fallback_idea_title_is_readable():
    from agents.idea_agent import fallback_title
    assert fallback_title("A mobile app that helps college students split shared grocery bills") == "Split Shared Grocery Bills"
    assert fallback_title("A low-cost IoT energy auditing system for societies") == "Low-cost IoT Energy Auditing System"
    assert fallback_title("") == "Engineering Project"
    assert fallback_title("An e-commerce website for a small rubber products manufacturer in Kerala that sells sheets") == \
        "E-commerce Website for Rubber Products Manufacturer"


def test_unreadable_answer_is_written_once_more_and_saved(monkeypatch):
    build, steps, calls = build_with(monkeypatch, ["Sorry, here is the plan without code.", answer()])
    assert len(calls) == 2 and "could not be read" in calls[1][-1]["content"]
    assert build["generation_source"] == "llm" and build["checks"]["tests"]["ok"]
    assert (prototype_sandbox.proto_path(build["id"]) / "ai_answer.log").read_text().startswith("Sorry")
    wrapped = "````markdown\n" + answer().replace("```", "~~~") + "````"
    assert set(prototype_agent.parse_answer(wrapped)[0]) == set(prototype_agent.AI_FILES)


def test_wait_covers_enough_bookings_for_a_big_call():
    from core.llm import LLMClient
    client = LLMClient()
    model = client._get_candidate_models(None)[0]
    now = time.time()
    # Three bookings 50s, 30s and 10s old (2k tokens each) on an 8k-per-minute model.
    with client._ledger._lock:
        client._ledger._window[model] = collections.deque([[now - 50, 2000.0], [now - 30, 2000.0], [now - 10, 2000.0]])
    wait = client._ledger_wait(model, 5400)  # needs two bookings to leave: the 30s-old one leaves in ~30s
    assert 29 < wait < 32


# ------------------------------------------------------------ app designs (the normal path)

TRACTOR_DESIGN = json.dumps({
    "kind": "booking", "app_name": "Tractor Share", "tagline": "Book a tractor by the slot",
    "entity": "Booking", "entity_plural": "Bookings", "action": "Book tractor",
    "fields": [{"name": "farmer", "label": "Farmer", "type": "text"},
               {"name": "tractor", "label": "Tractor", "type": "choice", "choices": ["Mahindra 575", "Swaraj 744"]},
               {"name": "day", "label": "Day", "type": "date"},
               {"name": "slot", "label": "Slot", "type": "choice", "choices": ["06:00", "10:00", "14:00"]}],
    "seed": [{"farmer": "Ramesh Yadav", "tractor": "Mahindra 575", "day": "2026-11-18", "slot": "06:00"},
             {"farmer": "Sunita Devi", "tractor": "Swaraj 744", "day": "2026-11-18", "slot": "06:00"},
             {"farmer": "Mohan Patil", "tractor": "Mahindra 575", "day": "2026-11-18", "slot": "06:00"}],  # double booking: dropped
    "rule": {"resource_field": "tractor", "day_field": "day", "slot_field": "slot"},
})


def test_design_build_uses_one_small_call_and_passes_its_tests(monkeypatch):
    build, steps, calls = build_with(monkeypatch, [], design=TRACTOR_DESIGN)
    assert calls == []  # only the design call, no code-writing call
    assert build["generation_source"] == "llm" and build["build_mode"] == "design" and build["app_kind"] == "booking"
    assert build["checks"]["tests"]["ok"] and build["checks"]["tests"]["passed"] >= 7
    assert build["checks"]["page_ok"] and build["checks"]["server"]["ok"]
    by = {f["path"]: f["written_by"] for f in build["files"]}
    assert by["features.py"] == "generated" and by["main.py"] == "template"
    code = next(f["content"] for f in build["files"] if f["path"] == "features.py")
    assert "Mahindra 575" in code and "Mohan Patil" not in code
    assert any(s["agent_name"] == "Code Fixer" and s["details"].get("skipped") for s in steps)


def test_ai_down_builds_a_labelled_app_from_the_idea_keywords(monkeypatch):
    build, steps, calls = build_with(monkeypatch, [], design=RuntimeError("Engine busy"))
    assert build["generation_source"] == "fallback" and build["app_kind"] == "booking"
    assert "Engine busy" in build["fallback_reason"] and build["checks"]["tests"]["ok"]
    assert any(s["agent_name"] == "Code Writer" and s["status"] == "warning" for s in steps)


@pytest.mark.parametrize("idea, kind", [
    ("A smart ultrasonic water meter for residential buildings using LoRaWAN to detect pipe leakages in real time "
     "and estimate daily household consumption.", "monitor"),
    ("An automated AI peer review platform for engineering students that checks their lab code submissions for "
     "code quality, linting and AST-based standards.", "review"),
    ("A low-cost IoT energy auditing system for residential societies that detects abnormal power spikes using "
     "ESP32 with CT current sensors and alerts residents.", "monitor"),
    ("Hostel students raise complaints and track their status", "tracker"),
    ("An e-commerce website for a small rubber products manufacturer in Kerala that sells rubber sheets, gaskets, "
     "O-rings, hoses and gloves online to workshops and factories, with material and hardness details, minimum order "
     "quantities, live stock, bulk discounts, GST and delivery charges by order value.", "shop"),
    ("Flatmates split shared grocery bills and see who owes whom", "split"),
    ("Parents find a home tutor nearby and read ratings from other parents", "listing"),
])
def test_demo_ideas_get_a_working_app_without_ai(idea, kind):
    design = blueprints.default_design({"title": "Demo", "problem": idea})
    assert design["kind"] == kind
    files = blueprints.render(design)
    assert prototype_sandbox.safety_check(files) == [] and prototype_sandbox.compile_check(files) == []
    assert prototype_sandbox.page_api_check(files) == []
    from agents.prototype_templates import BASE_CSS, MAIN_PY
    prototype_sandbox.write_files("abcdef1234", {**files, "main.py": MAIN_PY.format(title="Demo"), "static/base.css": BASE_CSS})
    tests = prototype_sandbox.run_tests("abcdef1234")
    assert tests["ok"] and tests["passed"] >= 7, tests["output"]


def test_messy_designs_are_cleaned_or_rejected():
    spec = {"title": "T"}
    with pytest.raises(ValueError):
        blueprints.normalize({"kind": "custom"}, spec)
    with pytest.raises(ValueError):
        blueprints.normalize("not a dict", spec)
    d = blueprints.normalize({"kind": "review", "fields": [{"name": "status", "type": "text"}],
                              "rule": {"checks": [{"kind": "contains", "value": "x"}, {"kind": "not_contains", "value": "X"},
                                                  {"kind": "regex", "value": ".*"}]}}, spec)
    assert [c["kind"] for c in d["rule"]["checks"]] == ["contains"]  # opposite and unknown checks dropped
    assert d["fields"][0]["name"] == "status_value" and any(f["type"] == "long_text" for f in d["fields"])
    assert len(d["seed"]) >= 3


def test_rubber_shop_design_has_every_pricing_factor():
    idea = "An e-commerce website for a rubber products manufacturer selling gaskets, hoses and sheets with bulk discounts and GST"
    d = blueprints.default_design({"title": "Rubber Mart", "problem": idea})
    rule = d["rule"]
    assert d["kind"] == "shop" and d["look"]["layout"] == "store"
    assert rule["moq_field"] and rule["unit_field"] and rule["tax_percent"] == 18 and len(rule["bulk"]) == 2
    assert {f["name"] for f in d["fields"]} >= {"material", "hardness", "price", "stock", "min_order"}
    page = blueprints.render(d)["static/index.html"]
    assert "/api/quote" in page and "/api/orders" in page and "Place order" in page


def test_messy_shop_and_split_designs_are_cleaned():
    spec = {"title": "T"}
    shop = blueprints.normalize({"kind": "shop", "fields": [{"name": "item", "type": "text"}, {"name": "cost", "type": "number"}],
                                 "rule": {"price_field": "cost", "bulk": [{"min_qty": 50, "off_percent": 10},
                                                                          {"min_qty": 20, "off_percent": 20},  # fewer units: dropped
                                                                          {"min_qty": 100, "off_percent": 5}]},  # smaller discount: dropped
                                 "seed": [{"item": "Pen", "cost": 10, "stock": 0, "category": "Standard"}]}, spec)
    rule = shop["rule"]
    assert rule["price_field"] == "cost" and rule["stock_field"] != "cost" and rule["bulk"] == [{"min_qty": 50, "off_percent": 10}]
    stock = rule["stock_field"]
    assert any(row[stock] >= 1 for row in shop["seed"])  # at least one product can be ordered
    files = blueprints.render(shop)
    assert prototype_sandbox.safety_check(files) == [] and prototype_sandbox.page_api_check(files) == []
    split = blueprints.normalize({"kind": "split", "fields": [{"name": "what", "type": "text"}, {"name": "payer", "type": "text"},
                                                             {"name": "amount", "type": "number"}],
                                  "rule": {"payer_field": "payer", "amount_field": "amount", "members": ["Asha", "Ravi", "Asha"]}}, spec)
    assert split["rule"]["payer_field"] == "payer" and split["rule"]["members"] == ["Asha", "Ravi"]


def test_ensure_never_drops_a_field_the_rule_uses():
    fields = [{"name": f"f{i}", "label": "x", "type": "text"} for i in range(4)] + [{"name": "where", "label": "Where", "type": "text"}]
    group = blueprints._ensure(fields, "where", ("text",), {"name": "location", "label": "L", "type": "text"})
    blueprints._ensure(fields, "reading", ("number",), {"name": "reading", "label": "R", "type": "number", "min": 0, "max": 9},
                       keep={group["name"]})
    assert "where" in [f["name"] for f in fields] and len(fields) == 5


DEMO_KINDS = {"Smart water meter": "monitor", "AI code reviewer": "review", "Energy spike monitor": "monitor",
              "Rubber products store": "shop", "Tractor booking": "booking", "Hostel complaints": "tracker",
              "Bill splitter": "split", "Home tutor finder": "listing"}


def test_every_demo_idea_in_the_ui_gets_its_own_app_kind():
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "web/react-app/src/App.jsx").read_text(encoding="utf-8")
    block = src.split("const IDEA_EXAMPLES = [")[1].split("\n]")[0]
    demos = dict(re.findall(r"\['([^']+)', '([^']+)'\]", block))
    assert set(demos) == set(DEMO_KINDS)
    for label, idea in demos.items():
        d = blueprints.default_design({"title": label, "problem": idea})
        assert d and d["kind"] == DEMO_KINDS[label], label
        files = blueprints.render(d)
        assert prototype_sandbox.safety_check(files) == [] and prototype_sandbox.page_api_check(files) == [], label
        if d["kind"] in blueprints._EXTRA_TITLE:
            assert 'id="extra"' in files["static/index.html"], label


def test_monitor_sample_week_builds_and_passes_its_tests():
    d = blueprints.default_design({"title": "W", "problem": "smart water meter that detects pipe leaks"})
    assert len(d["seed"]) == 32
    files = blueprints.render(d)
    from agents.prototype_templates import BASE_CSS, MAIN_PY
    prototype_sandbox.write_files("abcdef9999", {**files, "main.py": MAIN_PY.format(title="W"), "static/base.css": BASE_CSS})
    out = prototype_sandbox.run_tests("abcdef9999")
    assert out["ok"], out["output"]
    code = files["features.py"]
    assert "B-204" in code and "C-301" in code


def test_product_idea_that_mentions_code_is_an_idea_without_a_repo():
    from agents.orchestrator import orchestrator
    from agents.workflow_state import AgentWorkflowState
    state = AgentWorkflowState(session_id="t1", user_query="An automated AI peer review platform for engineering students "
                               "that checks their lab code submissions for code quality, linting and AST-based standards.")
    orchestrator.classify(state)
    assert state.intent == "idea_validation"
    bug = AgentWorkflowState(session_id="t2", user_query="ValueError: Token expired in verify_token, where is the bug?")
    orchestrator.classify(bug)
    assert bug.intent == "codebase_analysis"
