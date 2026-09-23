from __future__ import annotations

from scripts import evaluate_jev_extraction_check as probe


def test_every_claim_has_known_truth_and_fictional_text():
    requests = probe.build_requests()
    assert len(requests) == len(probe.CASES)
    for request in requests:
        assert "完全虚构" in request["state"]
        assert set(request["questions"]) == {f"c{index}" for index in range(len(request["claims"]))}
        assert {claim["expected"] for claim in request["claims"]} <= {"yes", "no", "cannot_determine"}
    old_errors = [claim for request in requests for claim in request["claims"]
                  if claim["kind"] == "old_extractor_start_date"]
    assert old_errors and all(claim["claimed"] == "2024-09-07" for claim in old_errors)


def test_score_separates_catches_false_alarms_abstentions_and_drift():
    requests = probe.build_requests()

    def answered(flip_first_correct: bool):
        run, flipped = [], False
        for request in requests:
            answers = {}
            for key, claim in zip(request["questions"], request["claims"], strict=True):
                choice = claim["expected"]
                if flip_first_correct and claim["kind"] == "correct" and not flipped:
                    choice, flipped = "no", True
                answers[key] = {"type": "choice", "choice": choice, "confidence": 0.9}
            run.append({**request, "answers": answers})
        return run

    report = probe.score([answered(True), answered(False)])
    wrong = sum(claim["expected"] == "no" for request in requests for claim in request["claims"])
    right = sum(claim["expected"] == "yes" for request in requests for claim in request["claims"])
    assert report["wrongValueRejected"] == f"{wrong}/{wrong}"
    assert report["rightValueRejected"] == f"1/{right}"
    assert report["unstatedHandled"] == "1/1"
    assert report["sameChoiceAcrossRuns"] == f"{report['questionCount'] - 1}/{report['questionCount']}"
