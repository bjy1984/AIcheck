from __future__ import annotations

from apps.worker.tasks import ACCURACY_BASELINE_TEXT_ENGINES, accuracy_pipeline_baseline_options


def test_accuracy_pipeline_baseline_runs_text_engines_only() -> None:
    options = accuracy_pipeline_baseline_options(
        {
            "disableResultCache": True,
            "enableTables": True,
            "enableSeals": True,
            "forceHeavyEngines": True,
        }
    )

    assert options["engineAllowlist"] == ACCURACY_BASELINE_TEXT_ENGINES
    assert options["enableTables"] is False
    assert options["enableSeals"] is False
    assert options["forceHeavyEngines"] is False
    assert options["disableResultCache"] is True


def test_accuracy_pipeline_baseline_does_not_mutate_source_options() -> None:
    source = {"enableTables": True}

    accuracy_pipeline_baseline_options(source)

    assert source == {"enableTables": True}
