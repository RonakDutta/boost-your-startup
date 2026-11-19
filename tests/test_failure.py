"""Failure Simulator: checks, readiness score, research filter, fix critic, API (hermetic: AI and search stubbed)."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agents.failure_agent import FailureSimulatorAgent, failure_simulator
from agents.orchestrator import orchestrator
from core.llm import llm_client
from tools import failure_checks as checks
from tools.paper_search import Paper, PaperSearchResult

DEMO = str(Path(__file__).resolve().parent.parent / "sample_startup_repo")


def kinds(source):
    return sorted({k for k, _, _ in checks.scan_source(source, "x.py")})


def test_each_check_fires_on_the_failure_and_not_on_the_safe_version():
    assert kinds("import requests\nrequests.get(url)") == ["no_timeout"]
    assert kinds("import requests\nrequests.get(url, timeout=5)") == []
    assert kinds("try:\n    x()\nexcept Exception:\n    pass") == ["ignored_error"]
    assert kinds("try:\n    x()\nexcept:\n    return_value = 0") == ["bare_except"]
    assert kinds("try:\n    x()\nexcept ValueError as err:\n    log(err)") == []
    assert kinds('db.execute(f"SELECT * FROM t WHERE id = {uid}")') == ["sql_injection"]
    assert kinds('db.execute("SELECT * FROM t WHERE id = " + uid)') == ["sql_injection"]
    assert kinds('db.execute("SELECT * FROM t WHERE id = ?", (uid,))') == []
    assert kinds('API_KEY = "sk_live_abcdef123456"') == ["hardcoded_secret"]
    assert kinds('API_KEY = os.environ["API_KEY"]') == [] and kinds('PASSWORD = "change-me-please"') == []
    assert kinds("import pickle\npickle.loads(blob)") == ["unsafe_deserialization"]
    assert kinds("yaml.load(text)") == ["unsafe_deserialization"] and kinds("yaml.safe_load(text)") == []
    assert kinds("eval(text)") == ["code_injection"]
    assert kinds("subprocess.run(cmd, shell=True)") == ["shell_injection"] and kinds("subprocess.run([a, b])") == []
    assert kinds("f = open('x.log', 'a')") == ["resource_leak"]
    assert kinds("with open('x.log', 'a') as f:\n    f.write('x')") == []
    assert kinds("DEBUG = True") == ["debug_mode"] and kinds("app.run(debug=True)") == ["debug_mode"]
    assert kinds("assert user is not None") == ["assert_check"]
    assert kinds("def broken(:") == []  # a file that does not parse is skipped, not a crash


def test_readiness_is_computed_and_capped_per_kind():
    many = [{"type": "no_timeout"}] * 7  # counted at most 2 times
    r = checks.readiness(many + [{"type": "assert_check"}])
    assert r["score"] == 100 - 16 - 1 and r["band"] == "Fix before launch"
    assert checks.readiness([])["score"] == 100


def test_fixed_code_check():
    assert checks.fixed_code_check("requests.get(url, timeout=5)", "no_timeout") == {"compiles": True, "failure_gone": True}
    assert checks.fixed_code_check("requests.get(url)", "no_timeout") == {"compiles": True, "failure_gone": False}
    assert checks.fixed_code_check("def f(:", "no_timeout")["compiles"] is False


def paper(title, abstract, url):
    return Paper(title=title, authors=["A. Author"], year=2021, abstract=abstract, url=url, source="arxiv")


def fake_search(queries, per_source=5):
    text = " ".join(queries)
    if "timeout" in text:
        papers = [paper("TFix: Automatic Timeout Bug Fixing", "Timeout bugs cause hangs and outages in cloud systems. "
                        "We study missing timeout settings and fix them automatically.", "https://arxiv.org/abs/1"),
                  paper("Deep Learning for Images", "We classify images with neural networks.", "https://arxiv.org/abs/2")]
    else:
        papers = []
    return PaperSearchResult(papers=papers, queries=queries, sources_ok=["arxiv"], sources_failed={})


@pytest.fixture
def research_on(monkeypatch):
    monkeypatch.setattr(failure_simulator, "research_enabled", True)
    monkeypatch.setattr(failure_simulator, "searcher", fake_search)


def run_demo():
    return orchestrator.process("Find failure points", repo_path=DEMO, force_intent="failure_analysis")


def test_demo_repo_offline_finds_every_planted_failure(research_on):
    state = run_demo()
    out = state.final_output
    assert out["type"] == "failure_analysis" and out["counts"]["total"] == 12
    assert {t["type"] for t in out["failure_types"]} == {
        "no_timeout", "ignored_error", "bare_except", "sql_injection", "hardcoded_secret",
        "unsafe_deserialization", "resource_leak", "debug_mode", "assert_check"}
    secret = next(f for f in out["findings"] if f["type"] == "hardcoded_secret")
    assert "sk_live_51HcampusEatsDemoKey" not in json.dumps(out) and "sk_l" in secret["code_line"]  # masked
    sql = next(f for f in out["findings"] if f["type"] == "sql_injection")
    assert [c["symbol"] for c in sql["callers"]] == ["handle_list_orders"] and "handle_list_orders" in sql["scenario"]
    # Research: the off-topic paper is dropped because it never names the failure.
    timeout = next(g for g in out["research"] if g["type"] == "no_timeout")
    assert [p["title"] for p in timeout["papers"]] == ["TFix: Automatic Timeout Bug Fixing"] and timeout["dropped"] == 1
    assert "Timeout bugs cause hangs" in timeout["papers"][0]["key_sentence"]
    # No AI here: standard fixes, labelled.
    assert out["generation_source"] == "fallback" and all(x["generated_by"] == "fallback" for x in out["fixes"])
    names = [s.agent_name for s in state.execution_trace]
    for step in ("Failure Scanner", "Failure Spread", "Failure Research", "Fix Advisor", "Fix Critic"):
        assert step in names
    json.dumps(out)


def test_ai_fixes_are_checked_in_code(research_on, monkeypatch):
    from indexer import index_cache
    findings, _, _ = FailureSimulatorAgent.scan(index_cache.get_index(DEMO), DEMO)
    first_timeout = next(f.id for f in findings if f.type == "no_timeout")
    first_sql = next(f.id for f in findings if f.type == "sql_injection")
    first_secret = next(f.id for f in findings if f.type == "hardcoded_secret")
    reply = {"fixes": [
        {"id": first_timeout, "what_can_go_wrong": "Orders hang when the gateway is slow.",
         "fixed_code": "requests.get(url, params=p, timeout=5)", "research_note": "Timeout bugs cause hangs in cloud systems [R1]."},
        {"id": first_sql, "what_can_go_wrong": "Other students' orders leak.",
         "fixed_code": 'rows = db.execute(f"SELECT * FROM orders WHERE id = {x}")', "research_note": "Studies show this [R7]."},
        {"id": first_secret, "what_can_go_wrong": "The key leaks.", "fixed_code": "API_KEY = os.environ[",
         "research_note": ""},
    ]}
    monkeypatch.setattr(llm_client, "generate_json", lambda *a, **k: reply)
    out = run_demo().final_output
    fixes = {x["id"]: x for x in out["fixes"]}
    good, sql, broken = fixes[first_timeout], fixes[first_sql], fixes[first_secret]
    assert good["checks"]["compiles"] and good["checks"]["failure_gone"] and good["cited_refs"] == ["R1"]
    assert good["checks"]["abstract_support"] > 0.3
    assert sql["checks"]["failure_gone"] is False  # the "fix" still builds SQL from text
    assert sql["research_note"] == "" and sql["checks"]["citations_removed"] == 1  # [R7] was never retrieved
    assert broken["checks"]["compiles"] is False
    assert out["verification"]["fixes_checked"] == 3 and out["verification"]["failures_removed"] == 1
    assert out["generation_source"] == "llm"


def test_stream_endpoint_runs_the_failure_pipeline(monkeypatch):
    from app import app
    from tests.test_run_stream import _events
    monkeypatch.setattr(failure_simulator, "research_enabled", False)
    client = TestClient(app)
    body = client.post("/api/run/stream", json={"query": "Find failure points", "repo_path": DEMO,
                                               "force_intent": "failure_analysis"}).text
    events = _events(body)
    assert events[-1][0] == "result"
    out = events[-1][1]["final_output"]
    assert out["type"] == "failure_analysis" and out["counts"]["total"] == 12 and out["research"] == []
    assert client.get("/api/sample-repo-path").json()["startup_path"].endswith("sample_startup_repo")
