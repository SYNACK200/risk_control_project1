from __future__ import annotations

from algorithm.algo.scores import compute_scores


def metrics(**values):
    return [{"code": k, "value": v} for k, v in values.items()]


def test_all_good_scores_high():
    m = metrics(A01="1", B02="0.1", C03="8000", D02="0.02", E01="0.1")
    r = compute_scores(m, [])
    assert r.overall >= 85
    assert r.grade == "good"
    assert len(r.domains) == 5


def test_dti_hit_drops_debt_domain():
    m = metrics(A01="1", B02="0.9", C03="8000", D02="0.02", E01="0.1")
    r = compute_scores(m, [{"code": "DTI_HIGH"}])
    debt = next(d for d in r.domains if d.key == "debt")
    assert debt.score <= 85
    assert "DTI_HIGH" in debt.hits


def test_missing_metrics_reduces_score():
    m = metrics(A01=None, A02=None, B02="0.1")
    r = compute_scores(m, [])
    income = next(d for d in r.domains if d.key == "income")
    assert income.missing == 2
    assert income.score <= 90


def test_overall_is_weighted_average():
    dom = [{"code": "A01", "value": "1"}, {"code": "B02", "value": "0.1"},
           {"code": "C03", "value": "1"}, {"code": "D02", "value": "0.1"},
           {"code": "E01", "value": "0.1"}]
    r = compute_scores(dom, [])
    expected = sum(d.score * d.weight for d in r.domains)
    assert abs(r.overall - round(expected, 1)) < 0.11
