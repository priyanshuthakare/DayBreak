from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import app as module
import auth

ISSUER = 'https://clerk.example.test'
ORIGIN = 'http://localhost:8000'
PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_token(user='user_alice', *, changes=None, key=PRIVATE_KEY):
    now = datetime.now(timezone.utc)
    claims = {
        'iss': ISSUER, 'sub': user, 'sid': 'sess_example', 'azp': ORIGIN,
        'iat': now, 'nbf': now - timedelta(seconds=1), 'exp': now + timedelta(minutes=1),
    }
    if changes:
        claims.update(changes)
    return jwt.encode(claims, key, algorithm='RS256', headers={'kid': 'test-key'})


def headers(user='user_alice', *, workspace='personal', **kwargs):
    return {'Authorization': 'Bearer ' + make_token(user, **kwargs), 'X-Daybreak-Workspace': workspace}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('CLERK_PUBLISHABLE_KEY', 'pk_test_placeholder')
    monkeypatch.setenv('CLERK_ISSUER_URL', ISSUER)
    monkeypatch.setenv('CLERK_ALLOWED_ORIGINS', ORIGIN)
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///' + (tmp_path / 'tickets.sqlite3').as_posix())
    monkeypatch.setenv('APP_ENV', 'development')
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('OPENAI_MODEL', raising=False)
    monkeypatch.delenv('ENABLE_AI_DRAFTS', raising=False)
    fake_jwks = SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=PRIVATE_KEY.public_key()))
    monkeypatch.setattr(auth, 'jwks_client', lambda issuer: fake_jwks)
    with TestClient(module.app) as test_client:
        test_client.headers.update(headers())
        yield test_client
