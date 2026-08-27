from __future__ import annotations

from libs.security.auth import USERS, verify_password


TEST_PASSWORD = "anyuekeji.123"


def test_all_demo_roles_accept_the_shared_test_password() -> None:
    assert set(USERS) == {"inspection", "contractor", "ndt", "owner", "admin", "fde", "test"}
    for role, user in USERS.items():
        assert verify_password(
            TEST_PASSWORD,
            user.get("passwordHash"),
            user.get("password"),
        ), f"{role} 未使用统一测试密码"
