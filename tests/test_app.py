import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
import app as module

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'STORE', tmp_path / 'tickets.json')
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    return TestClient(module.app)

def test_seed_classifications_and_persistence(client):
    assert client.post('/api/seed').json()['added'] == 12
    tickets = client.get('/api/tickets').json()
    for t in tickets:
        assert t['priority'] in t['expected']
        assert t['category'] in t['expected']
        if 'human review' in t['expected']:
            assert t['human_review']
    assert client.post('/api/seed').json()['added'] == 0
    assert len(client.get('/api/tickets').json()) == 12

def test_intake_status_and_export(client):
    payload = {'title':'LMS login problem', 'description':'I cannot login and training is due tomorrow', 'requester':'Test User', 'product':'LMS'}
    result = client.post('/api/tickets', json=payload)
    assert result.status_code == 200
    ticket = result.json()
    assert ticket['priority'] == 'High' and ticket['sla_hours'] == 4
    assert ticket['kb'] and ticket['category_reason'] and ticket['reply']
    assert client.patch('/api/tickets/' + ticket['id'], json={'status':'Resolved'}).json()['status'] == 'Resolved'
    assert 'LMS login problem' in client.get('/api/export').text
    assert client.patch('/api/tickets/' + ticket['id'], json={'status':'Unknown'}).status_code == 422

def test_incident_and_sensitive_handling(client, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'fake')
    monkeypatch.setenv('OPENAI_MODEL', 'fake')
    monkeypatch.setattr(module.request, 'urlopen', lambda *args, **kwargs: pytest.fail('Sensitive ticket must not leave the app'))
    result = client.post('/api/tickets', json={'title':'Compensation discrepancy', 'description':'The amount in my compensation letter is wrong', 'requester':'Test User', 'product':'Compensation'}).json()
    assert result['priority'] == 'Critical' and result['human_review']
    monkeypatch.delenv('OPENAI_API_KEY')
    for i in range(3):
        response = client.post('/api/tickets', json={'title':'LMS slowness', 'description':'The LMS is slow to load this morning', 'requester':f'User {i}', 'product':'LMS'})
        assert response.status_code == 200
    assert sum(t['incident'] for t in client.get('/api/tickets').json()) == 3

def test_unmatched_article_and_validation(client):
    result = client.post('/api/tickets', json={'title':'Strange zebra issue', 'description':'Purple zebras are appearing everywhere', 'requester':'Test User', 'product':'Other'}).json()
    assert result['kb'] is None and result['kb_skeleton']
    assert client.post('/api/tickets', json={'title':'x','description':'short','requester':'x','product':'LMS'}).status_code == 422

def test_incident_requires_three_within_one_30_minute_window(client):
    base = datetime.now(timezone.utc) - timedelta(minutes=50)
    for minutes in (0, 25, 50):
        client.post('/api/tickets', json={'title':'LMS slowness', 'description':'The LMS is slow to load this morning', 'requester':'Test User', 'product':'LMS', 'submitted_at':(base + timedelta(minutes=minutes)).isoformat()})
    assert not any(t['incident'] for t in client.get('/api/tickets').json())
