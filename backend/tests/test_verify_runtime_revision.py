from __future__ import annotations

import pytest

from scripts.verify_runtime_revision import SERVICES, verify


@pytest.mark.parametrize('fault', ['old_worker', 'stopped', 'missing', 'different_image', None])
def test_revision_verification_rejects_partial_or_stale_deployments(monkeypatch, fault):
    rows = [[f'/{name}', 'sha256:image', 'true', 'abc123'] for name in SERVICES]
    if fault == 'old_worker':
        rows[-1][3] = 'old'
    elif fault == 'stopped':
        rows[-1][2] = 'false'
    elif fault == 'missing':
        rows.pop()
    elif fault == 'different_image':
        rows[-1][1] = 'sha256:old'
    monkeypatch.setattr('scripts.verify_runtime_revision.subprocess.check_output',
                        lambda *a, **k: '\n'.join(' '.join(row) for row in rows))
    if fault:
        with pytest.raises(ValueError):
            verify('abc123')
    else:
        verify('abc123')
