from copy import deepcopy

import pytest

from libs.ocr.page_progress import final_page_progress, recognition_page_coverage


def call(**extra):
    return {"task": "advanced_recognition", **extra}


@pytest.mark.parametrize("calls,done", [
    ([], False),
    ([call()], True),
    ([call(roiColor="red")], False),
    ([call(outputTruncated=True)], False),
    ([call(outputTruncated=True, supersededByTiles=True, recoveryTileCount=2),
      call(tileRecovery=True, roiBbox=[0, 0, 10, 6])], False),
    ([call(outputTruncated=True, supersededByTiles=True, recoveryTileCount=2),
      call(tileRecovery=True, roiBbox=[0, 0, 10, 6]), call(tileRecovery=True, roiBbox=[0, 4, 10, 10])], True),
    ([call(outputTruncated=True, supersededByTiles=True, recoveryTileCount=2),
      call(tileRecovery=True, roiBbox=[0, 0, 10, 6]), call(tileRecovery=True, roiBbox=[0, 0, 10, 6])], False),
    ([call(outputTruncated=True, supersededByTiles=True, recoveryTileCount=2),
      call(tileRecovery=True, roiBbox=[0, 0, 10, 6]), call(tileRecovery=True, outputTruncated=True, roiBbox=[0, 4, 10, 10])], False),
])
def test_progress_requires_full_page_or_complete_recovery(calls, done):
    before = deepcopy(calls)
    coverage = recognition_page_coverage([1, 2], {1: [call()], 2: calls, 99: [call()]})
    assert coverage["completedPageNos"] == ([1, 2] if done else [1])
    assert coverage["unprocessedPageNos"] == ([] if done else [2])
    assert coverage["complete"] is done
    assert calls == before


@pytest.mark.parametrize("outcome,status", [("completed", "completed"), ("partial", "partial"), ("failed", "failed")])
def test_worker_final_progress_keeps_quality_outcome_even_when_pages_recognized(outcome, status):
    result = {"status": "failed" if outcome == "failed" else "success", "outcomeStatus": outcome,
              "metadata": {"recognitionPageCoverage": recognition_page_coverage([1, 2], {1: [call()], 2: [call()]})}}
    assert final_page_progress(result) == {"completed": 2, "total": 2, "currentPage": None, "status": status}


def test_rendered_pages_alone_do_not_prove_partial_recognition_is_complete():
    result = {"status": "success", "outcomeStatus": "partial", "pages": [{"pageNo": 1}, {"pageNo": 2}]}
    assert final_page_progress(result)["completed"] == 0
    assert final_page_progress(result)["status"] == "partial"
    result["outcomeStatus"] = "completed"
    assert final_page_progress(result)["completed"] == 2  # Existing completed native-text results remain supported.
