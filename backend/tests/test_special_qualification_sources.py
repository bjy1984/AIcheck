from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from libs.review_tools.r24_r34_tools import check_wps_pqr_coverage
from libs.standard_annex_sources import special_qualification_source


@pytest.mark.parametrize(('annex', 'kind', 'first', 'last'), [('C', 'buttered_joint', 67, 68), ('D', 'clad_plate', 69, 70), ('E', 'tube_to_tubesheet', 71, 73), ('F', 'stud_arc', 74, 77)])
def test_annex_sources_are_traceable_and_do_not_claim_automatic_decisions(annex, kind, first, last):
    source = special_qualification_source(kind)
    assert source['annex'] == annex
    assert source['sourcePages'] == list(range(first, last + 1))
    pdf = Path(__file__).resolve().parents[2] / source['sourcePdf']
    assert hashlib.sha256(pdf.read_bytes()).hexdigest() == source['sourceSha256']
    assert source['verifiedBy'] is None and source['automatedDecisionSupported'] is False
    assert source['pages'][0]['text']
    assert special_qualification_source(kind, clause=f'{annex}.1') is not None
    assert special_qualification_source(kind, clause='Z.9') is None
    result = check_wps_pqr_coverage({'wpsItems': [{'qualificationKind': kind}], 'pqrItems': [{}], 'workItems': [{}]})
    assert result['result'] == 'evidence_insufficient'
    assert result['sourceReferences'][0]['annex'] == annex


def test_unknown_annex_is_not_guessed():
    assert special_qualification_source('unknown') is None
