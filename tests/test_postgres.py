"""Optional integration test against a disposable local PostgreSQL-compatible server."""
import os
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import app as module
import auth
from conftest import PRIVATE_KEY, headers


def test_postgresql_driver_isolates_and_persists_users(monkeypatch):
    database_url = os.environ.get('DAYBREAK_TEST_POSTGRES_URL')
    if not database_url:
        pytest.skip('Set DAYBREAK_TEST_POSTGRES_URL to a disposable local PostgreSQL server')
    if urlsplit(database_url).hostname not in ('127.0.0.1', 'localhost', '::1'):
        pytest.fail('The PostgreSQL integration test only accepts a local disposable server')
    origin = 'https://daybreak.example.test'
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.setenv('CLERK_PUBLISHABLE_KEY', 'pk_live_placeholder')
    monkeypatch.setenv('CLERK_ISSUER_URL', 'https://clerk.example.test')
    monkeypatch.setenv('CLERK_ALLOWED_ORIGINS', origin)
    monkeypatch.setenv('DATABASE_URL', database_url)
    monkeypatch.delenv('ENABLE_AI_DRAFTS', raising=False)
    fake_jwks = SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=PRIVATE_KEY.public_key()))
    monkeypatch.setattr(auth, 'jwks_client', lambda issuer: fake_jwks)
    suffix = uuid4().hex
    alice = headers('user_alice_' + suffix, changes={'azp': origin})
    bob = headers('user_bob_' + suffix, changes={'azp': origin})
    org_id = 'org_team_' + suffix
    org_claims = {'azp': origin, 'v': 2, 'o': {'id': org_id, 'rol': 'member'}}
    alice_team = headers('user_alice_' + suffix, workspace=org_id, changes=org_claims)
    bob_team = headers('user_bob_' + suffix, workspace=org_id, changes=org_claims)
    payload = {'title': 'Private PostgreSQL ticket', 'description': 'A sufficiently detailed ticket', 'requester': 'Alice', 'product': 'LMS'}
    with TestClient(module.app) as client:
        created = client.post('/api/tickets', json=payload, headers=alice)
        assert created.status_code == 200
        ticket_id = created.json()['id']
        assert client.get('/api/tickets', headers=bob).json() == []
        assert client.patch('/api/tickets/' + ticket_id, json={'status': 'Resolved'}, headers=bob).status_code == 404
        assert client.delete('/api/tickets/' + ticket_id, headers=bob).status_code == 404
        assert 'Private PostgreSQL ticket' not in client.get('/api/export', headers=bob).text
        assert client.patch('/api/tickets/' + ticket_id, json={'status': 'Resolved'}, headers=alice).status_code == 200
        shared = client.post('/api/tickets', json={**payload, 'title': 'Team PostgreSQL ticket'}, headers=alice_team).json()
        assert client.get('/api/tickets', headers=bob_team).json()[0]['id'] == shared['id']
        assert 'Team PostgreSQL ticket' not in client.get('/api/export', headers=bob).text
    with TestClient(module.app) as client:
        assert client.get('/api/tickets', headers=alice).json()[0]['status'] == 'Resolved'
        assert client.delete('/api/tickets/' + ticket_id, headers=alice).status_code == 204
        assert client.delete('/api/tickets/' + shared['id'], headers=bob_team).status_code == 204
