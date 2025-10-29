import bcrypt
import pytest

from daemon.utils.auth import AuthError, AuthManager


def test_auth_manager_token_roundtrip():
    password = 'SuperSecret!'
    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    manager = AuthManager(password_hash=password_hash, token_secret='test-secret', token_ttl_seconds=60)

    assert manager.verify_password(password) is True
    assert manager.verify_password('wrong-password') is False

    token_data = manager.issue_token('admin')
    assert 'token' in token_data
    payload = manager.verify_token(token_data['token'])
    assert payload['sub'] == 'admin'


def test_auth_manager_requires_hash():
    manager = AuthManager(password_hash='', token_secret='testing', token_ttl_seconds=60)
    with pytest.raises(AuthError):
        manager.verify_password('anything')
