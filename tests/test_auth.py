from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

import jwt
import pytest
from fastapi.testclient import TestClient

import app as module
import auth
from conftest import OTHER_KEY, PRIVATE_KEY, headers, make_token
from settings import Settings


@pytest.mark.parametrize('method,path,body', [
    ('GET', '/api/tickets', None),
    ('POST', '/api/tickets', {'title': 'Valid title', 'description': 'A valid description', 'requester': 'User', 'product': 'LMS'}),
    ('PATCH', '/api/tickets/123', {'status': 'Resolved'}),
    ('DELETE', '/api/tickets/123', None),
    ('GET', '/api/export', None),
])
def test_ticket_routes_reject_missing_credentials(client, method, path, body):
    response = client.request(method, path, json=body, headers={'Authorization': ''})
    assert response.status_code == 401
    assert response.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('changes', [
    {'iss': 'https://other.example.test'},
    {'sub': ''},
    {'sid': ''},
    {'azp': 'https://attacker.example.test'},
    {'sts': 'pending'},
    {'exp': datetime.now(timezone.utc) - timedelta(minutes=5)},
    {'exp': datetime.now(timezone.utc) + timedelta(minutes=10)},
    {'nbf': datetime.now(timezone.utc) + timedelta(minutes=5)},
    {'iat': datetime.now(timezone.utc) + timedelta(minutes=5)},
])
def test_rejects_invalid_claims(client, changes):
    assert client.get('/api/tickets', headers=headers(changes=changes)).status_code == 401


def test_rejects_forged_malformed_and_wrong_scheme(client):
    assert client.get('/api/tickets', headers=headers(key=OTHER_KEY)).status_code == 401
    assert client.get('/api/tickets', headers={'Authorization': 'Bearer not-a-jwt'}).status_code == 401
    assert client.get('/api/tickets', headers={'Authorization': 'Basic ' + make_token()}).status_code == 401
    assert client.get('/api/tickets', headers={'Authorization': 'Bearer ' + make_token() + ' extra'}).status_code == 401


def test_real_signature_verification_accepts_valid_user_and_config_is_public(client):
    assert client.get('/api/tickets', headers=headers('user_bob')).status_code == 200
    response = client.get('/api/config', headers={'Authorization': ''})
    assert response.status_code == 200
    assert set(response.json()) == {'publishable_key'}


def test_production_rejects_missing_or_ephemeral_database(monkeypatch):
    monkeypatch.setenv('CLERK_PUBLISHABLE_KEY', 'pk_live_placeholder')
    monkeypatch.setenv('CLERK_ISSUER_URL', 'https://clerk.example.test')
    monkeypatch.setenv('CLERK_ALLOWED_ORIGINS', 'https://example.test')
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.delenv('DATABASE_URL', raising=False)
    with pytest.raises(RuntimeError, match='DATABASE_URL'):
        Settings.from_environment()
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///./temporary.sqlite3')
    with pytest.raises(RuntimeError, match='PostgreSQL'):
        Settings.from_environment()


def test_invalid_origin_configuration_fails_closed(monkeypatch):
    monkeypatch.setenv('CLERK_PUBLISHABLE_KEY', 'pk_test_placeholder')
    monkeypatch.setenv('CLERK_ISSUER_URL', 'https://clerk.example.test')
    monkeypatch.setenv('CLERK_ALLOWED_ORIGINS', 'https://example.test/path')
    with pytest.raises(RuntimeError, match='origin'):
        Settings.from_environment()


def test_production_rejects_test_clerk_key(monkeypatch):
    monkeypatch.setenv('CLERK_PUBLISHABLE_KEY', 'pk_test_placeholder')
    monkeypatch.setenv('CLERK_ISSUER_URL', 'https://clerk.example.test')
    monkeypatch.setenv('CLERK_ALLOWED_ORIGINS', 'https://example.test')
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.setenv('DATABASE_URL', 'postgresql://localhost/daybreak')
    with pytest.raises(RuntimeError, match='live Clerk'):
        Settings.from_environment()


def test_fetches_trusted_jwks_and_checks_real_signatures(tmp_path, monkeypatch):
    public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(PRIVATE_KEY.public_key(), as_dict=True)
    public_jwk.update({'kid': 'test-key', 'use': 'sig', 'alg': 'RS256'})
    requests = []

    class JWKSHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            body = json.dumps({'keys': [public_jwk]}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(('127.0.0.1', 0), JWKSHandler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        issuer = 'http://127.0.0.1:' + str(server.server_port)
        monkeypatch.setenv('APP_ENV', 'development')
        monkeypatch.setenv('CLERK_PUBLISHABLE_KEY', 'pk_test_placeholder')
        monkeypatch.setenv('CLERK_ISSUER_URL', issuer)
        monkeypatch.setenv('CLERK_ALLOWED_ORIGINS', 'http://localhost:8000')
        monkeypatch.setenv('DATABASE_URL', 'sqlite:///' + (tmp_path / 'jwks.sqlite3').as_posix())
        try:
            with TestClient(module.app) as client:
                assert client.get('/api/tickets', headers=headers(changes={'iss': issuer})).status_code == 200
                assert client.get('/api/tickets', headers=headers(changes={'iss': issuer}, key=OTHER_KEY)).status_code == 401
                assert requests == ['/.well-known/jwks.json']
        finally:
            server.shutdown()
            thread.join()
            auth.jwks_client.cache_clear()
