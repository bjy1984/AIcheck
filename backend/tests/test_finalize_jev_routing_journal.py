"""A live journal must not silently lose or duplicate a paid document request."""

import pytest

from scripts.finalize_jev_routing_journal import aggregate_journal


def _rows():
    identity = {"projectId": "P", "documentId": "D", "documentVersionId": "V"}
    return [{"phase": "manifest", "documentCount": 1, "expectedRequestCount": 2,
             "snapshotSha256": "hash"},
            {"phase": "reserved", "index": 1, **identity, "expectedRequestCount": 2},
            {"phase": "result", "index": 1, **identity,
             "report": {"send": True, "plannedRequestCount": 2, "attemptedRequestCount": 2,
                        "elapsedSeconds": 1.5, "providerReportedCostUSD": None,
                        "shadows": [{**identity, "status": "completed", "nodeScores": [
                            {"nodeId": 25, "choice": "yes", "confidence": 0.9}]}]}}]


def test_complete_journal_reconstructs_exact_requests_and_shadow():
    summary, shadows = aggregate_journal(_rows())
    assert summary["completedSweep"] is True
    assert summary["attemptedRequestCount"] == 2
    assert summary["statusCounts"] == {"completed": 1}
    assert summary["providerReportedCostUSD"] is None
    assert summary["descriptiveRouting"]["choiceCounts"] == {"yes": 1}
    assert len(shadows) == 1


def test_unfinished_or_duplicate_journal_is_not_reported_as_complete():
    rows = _rows()
    summary, shadows = aggregate_journal(rows[:2])
    assert summary["completedSweep"] is False
    assert summary["unresolvedReservationCount"] == 1
    assert shadows == []
    with pytest.raises(ValueError, match="duplicate_sweep_result"):
        aggregate_journal([*rows, rows[-1]])
    changed = _rows()
    changed[-1]["report"]["plannedRequestCount"] = 1
    with pytest.raises(ValueError, match="sweep_request_count_mismatch"):
        aggregate_journal(changed)
