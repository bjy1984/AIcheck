from __future__ import annotations

from libs.review_orchestrator.output_contract import _visible_jev_opinions


def _run(confidence=0.7, agrees=True):
    return {"jevSecondOpinions": {"status": "completed", "model": "jev-1.13.0", "atomic": [{
        "atomicCheckId": "AC-1", "choice": "passed", "confidence": confidence,
        "model": "jev-1.13.0", "agreesWithRuleEngine": agrees,
    }]}}


def _enable(monkeypatch):
    monkeypatch.setenv("AICHECK_JEV_CALIBRATION_APPROVED", "true")
    monkeypatch.setenv("AICHECK_JEV_SECOND_OPINION_UI_ENABLED", "true")
    monkeypatch.setenv("AICHECK_JEV_QUEUE_ENTER_CONFIDENCE", "0.68")
    monkeypatch.setenv("AICHECK_JEV_QUEUE_EXIT_CONFIDENCE", "0.72")


def test_unlabelled_opinion_is_never_published_to_workbench(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.delenv("AICHECK_JEV_CALIBRATION_APPROVED")
    assert _visible_jev_opinions(_run()) == {}


def test_disagreement_first_and_hysteresis_retains_prior_queue(monkeypatch):
    _enable(monkeypatch)
    assert _visible_jev_opinions(_run(0.9, False))["AC-1"]["priority"] == "disagreement"
    assert _visible_jev_opinions(_run(0.67))["AC-1"]["priority"] == "low_confidence"
    assert _visible_jev_opinions(_run(0.72))["AC-1"]["priority"] == "normal"
    middle = _run(0.7)
    middle["jevQueuePrevious"] = {"AC-1": False}
    assert _visible_jev_opinions(middle)["AC-1"]["priority"] == "normal"
    middle["jevQueuePrevious"] = {"AC-1": True}
    assert _visible_jev_opinions(middle)["AC-1"]["priority"] == "low_confidence"


def test_invalid_threshold_pair_blocks_display(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setenv("AICHECK_JEV_QUEUE_ENTER_CONFIDENCE", "0.8")
    assert _visible_jev_opinions(_run()) == {}
