import json

import httpx

from lead_intake.models import Enrichment, LeadIn
from lead_intake.scoring import LLMScorer, Scorer, heuristic_score


def test_heuristic_is_deterministic_and_ranks_sensibly():
    hot = LeadIn(email="a@northwind-logistics.com", name="A", title="CEO", budget="$10,000",
                 message="budget approved, automate ASAP")
    cold = LeadIn(email="b@gmail.com", name="B", message="hi")
    e_hot = Enrichment(domain="northwind-logistics.com", employees=400)
    e_cold = Enrichment(domain="gmail.com", is_free_email=True)
    s1, s2 = heuristic_score(hot, e_hot), heuristic_score(hot, e_hot)
    assert s1 == s2
    assert s1.tier == "hot" and s1.score >= 70
    assert heuristic_score(cold, e_cold).tier == "cold"


def test_budget_parsing_handles_k_suffix():
    lead = LeadIn(email="x@acme.io", name="X", budget="10k")
    assert any("budget" in r for r in heuristic_score(lead, Enrichment(domain="acme.io")).reasons)


def _mock_llm(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_llm_scorer_parses_json(settings):
    settings.openai_api_key = "test"

    def handler(request):
        body = {"choices": [{"message": {"content": json.dumps({"score": 88, "summary": "Great fit", "reasons": ["CEO"]})}}]}
        return httpx.Response(200, json=body)

    scorer = Scorer(settings, llm=LLMScorer(settings, client=_mock_llm(handler)))
    s = scorer.score(LeadIn(email="a@b.com", name="A"), Enrichment(domain="b.com"))
    assert s.score == 88 and s.tier == "hot" and s.scored_by.startswith("llm:")


def test_llm_failure_falls_back_to_heuristic(settings):
    settings.openai_api_key = "test"
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(500, json={"error": "down"})

    llm = LLMScorer(settings, client=_mock_llm(handler))
    s = Scorer(settings, llm=llm).score(LeadIn(email="a@b.com", name="A"), Enrichment(domain="b.com"))
    assert s.scored_by == "heuristic"
    assert len(calls) == settings.retry_attempts  # 5xx was retried before falling back


def test_llm_garbage_falls_back(settings):
    settings.openai_api_key = "test"
    handler = lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})  # noqa: E731
    s = Scorer(settings, llm=LLMScorer(settings, client=_mock_llm(handler))).score(
        LeadIn(email="a@b.com", name="A"), Enrichment(domain="b.com"))
    assert s.scored_by == "heuristic"


def test_no_key_means_heuristic(settings):
    assert Scorer(settings).llm is None
