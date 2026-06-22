from __future__ import annotations

from datetime import datetime, timedelta

import pytest

import app as app_module
from config.security_config import load_account_lockout_config
from models import User, db
from services.auth_security_service import AccountLockoutService


@pytest.fixture
def lockout_app(monkeypatch):
    monkeypatch.setenv("ACCOUNT_LOCKOUT_ENABLED", "true")
    monkeypatch.setenv("MAX_FAILED_LOGIN_ATTEMPTS", "3")
    monkeypatch.setenv("LOCKOUT_DURATION_MINUTES", "1")
    monkeypatch.setenv("ENABLE_SECURITY_AUDIT", "true")

    app_module.app.config.update(
        TESTING=True,
        LOGIN_DISABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        WTF_CSRF_ENABLED=False,
    )
    with app_module.app.app_context():
        db.drop_all()
        db.create_all()
        user = User(email="lockout@example.com", full_name="Lockout User", role="farmer")
        user.set_password("correct-password")
        db.session.add(user)
        db.session.commit()
        yield app_module.app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def lockout_client(lockout_app):
    return lockout_app.test_client()


def test_config_uses_safe_defaults_for_invalid_values(monkeypatch):
    monkeypatch.setenv("MAX_FAILED_LOGIN_ATTEMPTS", "-1")
    monkeypatch.setenv("LOCKOUT_DURATION_MINUTES", "bad")

    config = load_account_lockout_config()

    assert config.max_failed_attempts == 5
    assert config.lockout_duration_minutes == 15


def test_service_locks_unlocks_and_resets_user(lockout_app):
    with lockout_app.app_context():
        user = User.query.filter_by(email="lockout@example.com").one()
        service = AccountLockoutService()
        now = datetime.utcnow()

        service.record_failed_login(user, ip="127.0.0.1", user_agent="pytest", now=now)
        service.record_failed_login(user, ip="127.0.0.1", user_agent="pytest", now=now)
        state = service.record_failed_login(user, ip="127.0.0.1", user_agent="pytest", now=now)

        assert state.locked is True
        assert user.failed_login_attempts == 3
        assert user.account_locked_until is not None

        expired_state = service.check_lockout(
            user,
            now=now + timedelta(minutes=2),
        )

        assert expired_state.locked is False
        assert expired_state.unlocked_expired_lock is True
        assert user.failed_login_attempts == 0
        assert user.account_locked_until is None

        user.failed_login_attempts = 2
        service.record_successful_login(user, ip="127.0.0.1", user_agent="pytest", now=now)

        assert user.failed_login_attempts == 0
        assert user.last_successful_login_at == now
        assert user.last_successful_ip == "127.0.0.1"


def test_login_locks_after_threshold_and_resets_after_expiration(
    lockout_client,
    lockout_app,
    monkeypatch,
):
    for _ in range(3):
        response = lockout_client.post(
            "/login",
            data={"email": "lockout@example.com", "password": "wrong-password"},
        )
        assert response.status_code == 200

    locked_response = lockout_client.post(
        "/login",
        data={"email": "lockout@example.com", "password": "correct-password"},
    )

    assert locked_response.status_code == 423

    class ExpiredLockoutService(AccountLockoutService):
        def check_lockout(self, user, now=None):
            return super().check_lockout(user, now=datetime.utcnow() + timedelta(minutes=2))

    monkeypatch.setattr(app_module, "AccountLockoutService", ExpiredLockoutService)

    success_response = lockout_client.post(
        "/login",
        data={"email": "lockout@example.com", "password": "correct-password"},
        follow_redirects=False,
    )

    assert success_response.status_code == 302

    with lockout_app.app_context():
        user = User.query.filter_by(email="lockout@example.com").one()
        assert user.failed_login_attempts == 0
        assert user.account_locked_until is None
