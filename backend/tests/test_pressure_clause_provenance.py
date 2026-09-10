import hashlib
from pathlib import Path

from libs.review_orchestrator.design_facts import frozen_special_requirement_rules


def test_frozen_pressure_labels_match_reviewed_source_identity_without_human_signoff():
    pressure = frozen_special_requirement_rules()['pressureTest']
    source = pressure['sourceReview']
    path = Path(__file__).resolve().parents[2] / source['documentPath']
    assert hashlib.sha256(path.read_bytes()).hexdigest() == source['documentSha256']
    assert source['pdfPages'] == [127, 128]
    assert source['printedPages'] == [119, 120]
    assert source['humanVerified'] is False
    assert source['reviewedScope'] == 'pressure_ratio_clause_labels_only'
    for rule in pressure['checks']:
        assert rule['verifiedBy'] is None
        assert rule['standardRef'] == 'STD-GBT-20801.1-2025'
        assert rule['sourceClause'].startswith('GB/T 20801.1-2025 ')
        assert '1.15' not in rule['sourceClause']
    ratio = next(rule for rule in pressure['checks'] if rule['code'] == 'test_pressure_ratio')
    assert '上限' in ratio['sourceClause'] and '例外' in ratio['sourceClause']
    assert ratio['actualPath'] == 'requirements.testPressureMeetsRatio'
