from __future__ import annotations

from pathlib import Path

from scripts.audit_frontend_contract import audit, path_pattern_matches


def test_contract_audit_covers_aicheck_and_login_clients() -> None:
    frontend_root = Path(__file__).resolve().parents[2] / "frontend" / "src" / "api"

    result = audit(frontend_root, ["aicheck/**/*.ts", "login/**/*.ts"])

    assert result.frontend_count >= 100
    assert result.backend_count >= 300
    assert result.missing == []
    assert any(item.path == "/api/auth/logout" for item in result.covered)


def test_contract_audit_matches_backend_parameter_routes() -> None:
    assert path_pattern_matches("/api/admin/{}", "/api/admin/field-mappings")
    assert path_pattern_matches("/api/projects/{}/documents/{}", "/api/projects/{}/documents/{}")
    assert not path_pattern_matches("/api/admin/{}", "/api/admin/config-items/{}")
