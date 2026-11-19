"""Why startups fail: the dataset, the live-page check (on a saved snippet, no network) and the endpoint."""

from fastapi.testclient import TestClient

from tools import startup_failure_data as data

# Wording from the CB Insights report (March 2026), cut down.
PAGE = ("<p>“Ran out of capital” tops the list at 70%, but it is the final cause.</p>"
        "<p>The more telling causes, poor product-market fit (43%), bad timing (29%), and "
        "unsustainable unit economics (19%), reveal why.</p>"
        "<p>The analysis includes 385 companies for which failure reasons could be identified.</p>")


def test_dataset_has_a_source_and_honest_coverage():
    d = data.load()
    assert d["source"]["url"].startswith("https://www.cbinsights.com/")
    assert d["source"]["companies_with_reasons"] == 385
    shares = [r["share"] for r in d["reasons"]]
    assert shares == sorted(shares, reverse=True) and shares[0] == 70 and len(shares) == 9
    assert {r["coverage"] for r in d["reasons"]} <= {"covered", "partly", "none"}
    assert any(r["coverage"] == "none" for r in d["reasons"])  # not everything is claimed


def test_check_text_matches_and_spots_a_change():
    ok = data.check_text(PAGE)
    assert ok["checked"] == 4 and ok["matching"] == 4 and ok["sample_on_page"] == 385
    changed = data.check_text(PAGE.replace("(43%)", "(45%)"))
    assert changed["matching"] == 3
    assert next(r for r in changed["rows"] if r["id"] == "pmf")["page"] == 45


def test_endpoint_serves_the_data_without_fetching():
    from app import app
    body = TestClient(app).get("/api/startup-failure-data").json()
    assert body["source"]["publisher"] == "CB Insights" and "verification" not in body
