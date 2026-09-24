from __future__ import annotations

from scripts import evaluate_jev_boundaries as suite


def test_every_probe_is_fictional_fits_one_request_and_has_valid_truth():
    probes = suite.build_probes()
    assert {probe["dimension"] for probe in probes} >= {
        "extraction_check", "bundle_disambiguation", "person_disambiguation", "option_flaw",
        "applicability", "long_context", "context_limit", "ocr_noise", "prompt_injection", "option_order",
        "paraphrase", "numeric", "negation", "document_conflict", "irrelevant_material"}
    for probe in probes:
        assert suite.FICTION in probe["state"]
        assert set(probe["expected"]) == set(probe["questions"])
        for key, question in probe["questions"].items():
            assert set(probe["expected"][key]) <= set(question["criteria"]), (probe["probeId"], key)
    neutral = next(probe for probe in probes if probe["probeId"] == "neutral_keys")
    assert neutral["keyMap"][neutral["expected"]["q0"][0]] == "failed"


def test_long_context_places_the_same_fact_at_three_positions():
    rows = [probe for probe in suite.build_probes() if probe["dimension"] == "long_context"]
    assert len(rows) == 9
    needle = "焊工张明远的焊工证有效期至2025年3月1日"
    starts = {probe["probeId"]: probe["state"].index(needle) / len(probe["state"]) for probe in rows}
    assert starts["24000_start"] < 0.01 and 0.45 < starts["24000_middle"] < 0.55 and starts["24000_end"] > 0.99


def test_score_reports_accuracy_drift_calibration_and_neutral_key_mapping():
    probes = suite.build_probes()

    def run(flip_first: bool):
        answers, flipped = [], False
        for probe in probes:
            row = {}
            for key, ok in probe["expected"].items():
                choice = ok[0]
                if flip_first and not flipped:
                    choice, flipped = next(k for k in probe["questions"][key]["criteria"] if k not in ok), True
                row[key] = {"type": "choice", "choice": choice, "confidence": 0.95 if choice in ok else 0.4}
            answers.append(row)
        return answers

    report = suite.score(probes, [run(True), run(False)])
    total = report["questionCount"]
    assert report["accuracy"] == f"{total - 1}/{total}"
    assert report["sameAcrossRuns"] == f"{total - 1}/{total}"
    assert report["calibration"]["<0.70"] == "0/1"
    assert report["variantConsistency"]["order"] == ["failed"]


def test_a_refused_request_is_recorded_and_left_out_of_accuracy():
    probes = suite.build_probes()
    answers = [{key: {"type": "choice", "choice": ok[0], "confidence": 0.9}
                for key, ok in probe["expected"].items()} for probe in probes]
    refused = next(index for index, probe in enumerate(probes) if probe["probeId"] == "35000_chars")
    answers[refused] = {"_error": {"status": 400, "body": "max_tokens_exceeded"}}
    report = suite.score(probes, [answers])
    assert report["requestErrors"] == [{"dimension": "context_limit", "probeId": "35000_chars",
                                        "stateChars": len(probes[refused]["state"]),
                                        "errors": [{"status": 400, "body": "max_tokens_exceeded"}],
                                        "failedRuns": "1/1"}]
    assert report["accuracy"] == f"{report['questionCount']}/{report['questionCount']}"
