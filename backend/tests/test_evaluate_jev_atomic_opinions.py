from copy import deepcopy

import pytest

from scripts.evaluate_jev_atomic_opinions import (
    candidates_from_state,
    evaluate_labels,
    r19_candidates_from_state,
)
from scripts.prepare_jev_atomic_labels import blind_packet


def _state():
    runs, results = [], []
    for index in range(40):
        run_id = f"RR-{index:02d}"
        atomic_id = f"AC-{index:02d}"
        choice = "failed" if index < 20 else "passed"
        runs.append({"reviewRunId": run_id, "projectId": "P", "nodeId": index % 69 + 1,
                     "inputHash": f"hash-{index}", "jevSecondOpinions": {
                         "status": "completed", "model": "jev-1.13.0", "atomic": [{
                             "atomicCheckId": atomic_id, "choice": choice,
                             "confidence": round(0.50 + index / 100, 2),
                             "sourceDocumentVersionIds": [f"V-{index}"],
                         }]}})
        results.append({"reviewRunId": run_id, "atomicCheckResults": [{
            "atomicCheckId": atomic_id, "result": "passed"}]})
    return {"review_runs": runs, "rule_check_results": results}


def test_new_33_case_pool_is_version_bound_and_never_claims_labels():
    prepared = candidates_from_state(_state())
    assert prepared["status"] == "ready_for_inspector"
    assert (prepared["selectedDisagreementCount"], prepared["selectedJevPassedCount"]) == (16, 17)
    assert len({row["caseId"] for row in prepared["candidates"]}) == 33
    assert all(row["inputHash"] and row["documentVersionIds"] for row in prepared["candidates"])
    assert all("inspectorChoice" not in row for row in prepared["candidates"])


def test_blind_atomic_packet_hides_jev_and_rule_answers():
    packet = blind_packet(_state())
    assert packet["status"] == "ready_for_inspector"
    assert len(packet["cases"]) == 33
    assert all(row["choice"] is None for row in packet["cases"])
    assert all("jevChoice" not in row and "currentResult" not in row
               and "confidence" not in row for row in packet["cases"])


def test_r19_eight_questions_are_separate_and_can_be_blind_labeled():
    state = {"review_runs": [{"reviewRunId": "RR-R19", "projectId": "P", "nodeId": 19,
                              "inputHash": "hash-r19", "jevSecondOpinions": {
                                  "status": "completed", "model": "jev-1.13.0",
                                  "comparisonSource": "r19_semantic_review", "atomic": [
                                      {"atomicCheckId": f"AC-R19-{index:02d}", "choice": "passed",
                                       "confidence": 0.8, "instruction": "固定语义题"}
                                      for index in range(1, 9)]}}],
             "rule_check_results": [{"reviewRunId": "RR-R19", "atomicCheckResults": [
                 {"atomicCheckId": f"AC-R19-{index:02d}", "result": "evidence_insufficient"}
                 for index in range(1, 9)]}]}
    prepared = r19_candidates_from_state(state)
    assert prepared["candidateCount"] == 8
    assert candidates_from_state(state)["availableCount"] == 0
    packet = blind_packet(state, comparison="r19")
    assert packet["status"] == "ready_for_inspector"
    assert len(packet["cases"]) == 8
    assert all(row["choice"] is None and "jevChoice" not in row for row in packet["cases"])


def test_insufficient_pool_is_reported_instead_of_fabricating_old_33_cases():
    state = _state()
    state["review_runs"] = state["review_runs"][:3]
    prepared = candidates_from_state(state)
    assert prepared["status"] == "insufficient_candidate_pool"
    assert prepared["selectedDisagreementCount"] == 3
    assert prepared["selectedJevPassedCount"] == 0


def test_qwen_r19_and_opinions_without_persisted_rule_result_are_excluded():
    state = _state()
    state["review_runs"][0]["jevSecondOpinions"]["comparisonSource"] = "r19_semantic_review"
    state["rule_check_results"] = state["rule_check_results"][:-1]
    state["review_runs"][-1]["jevSecondOpinions"]["atomic"][0]["currentResult"] = "passed"
    prepared = candidates_from_state(state)
    case_ids = {row["caseId"] for row in prepared["candidates"]}
    assert "RR-00/AC-00" not in case_ids
    assert "RR-39/AC-39" not in case_ids


def test_inspector_results_compare_jev_and_current_and_reject_stale_hash():
    candidates = candidates_from_state(_state())["candidates"]
    disagreement = next(row for row in candidates if row["samplingStratum"] == "disagreement")
    passed = next(row for row in candidates if row["samplingStratum"] == "jev_passed")
    labels = [{"caseId": disagreement["caseId"], "inputHash": disagreement["inputHash"],
               "labelSource": "inspector", "annotatedBy": "I1", "choice": "passed"},
              {"caseId": passed["caseId"], "inputHash": passed["inputHash"],
               "labelSource": "inspector", "annotatedBy": "I2", "choice": "failed"},
              {"caseId": candidates[-1]["caseId"], "inputHash": "stale",
               "labelSource": "inspector", "annotatedBy": "I3", "choice": "passed"}]
    report = evaluate_labels(candidates, labels)
    assert report["inspectorComparedCount"] == 2
    assert report["staleInputHashCount"] == 1
    assert report["jev"]["correct"] == 0
    assert report["current"]["correct"] == 1
    assert report["falsePassCaseIds"] == [passed["caseId"]]
    assert report["releaseThresholdApproved"] is False
    assert evaluate_labels(candidates, [deepcopy(labels[2])])["status"] == "no_comparable_inspector_labels"
    with pytest.raises(ValueError, match="duplicate_or_unknown_label_case"):
        evaluate_labels(candidates, [labels[0], labels[0]])
