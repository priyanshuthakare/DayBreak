from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from random import Random

import pytest
import app as module
import storage
from conftest import headers


PAYLOAD = {'title': 'LMS login problem', 'description': 'I cannot login and training is due tomorrow', 'requester': 'Test User', 'product': 'LMS'}


def test_ticket_persistence_between_connections(client):
    ticket = client.post('/api/tickets', json=PAYLOAD).json()
    reopened = storage.create_store(module.app.state.settings.database_url)
    try:
        assert storage.list_tickets(reopened, 'user_alice')[0]['id'] == ticket['id']
    finally:
        reopened.dispose()


def test_intake_status_and_export(client):
    result = client.post('/api/tickets', json=PAYLOAD)
    assert result.status_code == 200
    ticket = result.json()
    assert ticket['priority'] == 'High' and ticket['sla_hours'] == 4
    assert ticket['kb'] and ticket['category_reason'] and ticket['reply']
    assert client.patch('/api/tickets/' + ticket['id'], json={'status': 'Resolved'}).json()['status'] == 'Resolved'
    assert 'LMS login problem' in client.get('/api/export').text
    assert client.patch('/api/tickets/' + ticket['id'], json={'status': 'Unknown'}).status_code == 422


def test_sensitive_handling_and_ai_is_opt_in(client, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'fake')
    monkeypatch.setenv('OPENAI_MODEL', 'fake')
    monkeypatch.setattr(module.request, 'urlopen', lambda *args, **kwargs: pytest.fail('Ticket must not leave the app'))
    assert client.post('/api/tickets', json=PAYLOAD).status_code == 200
    monkeypatch.setenv('ENABLE_AI_DRAFTS', 'true')
    result = client.post('/api/tickets', json={'title': 'Compensation discrepancy', 'description': 'The amount in my compensation letter is wrong', 'requester': 'Test User', 'product': 'Compensation'}).json()
    assert result['priority'] == 'Critical' and result['human_review']


def test_unmatched_article_and_validation(client):
    result = client.post('/api/tickets', json={'title': 'Strange zebra issue', 'description': 'Purple zebras are appearing everywhere', 'requester': 'Test User', 'product': 'Other'}).json()
    assert result['kb'] is None and result['kb_skeleton']
    assert client.post('/api/tickets', json={'title': 'x', 'description': 'short', 'requester': 'x', 'product': 'LMS'}).status_code == 422


def test_incident_requires_three_within_one_window_and_one_account(client):
    base = datetime.now(timezone.utc) - timedelta(minutes=50)
    slow = {'title': 'LMS slowness', 'description': 'The LMS is slow to load this morning', 'requester': 'Test User', 'product': 'LMS'}
    for minutes in (0, 25, 50):
        assert client.post('/api/tickets', json={**slow, 'submitted_at': (base + timedelta(minutes=minutes)).isoformat()}).status_code == 200
    assert not any(t['incident'] for t in client.get('/api/tickets').json())
    for _ in range(2):
        assert client.post('/api/tickets', json=slow, headers=headers('user_bob')).status_code == 200
    assert not any(t['incident'] for t in client.get('/api/tickets').json())
    assert not any(t['incident'] for t in client.get('/api/tickets', headers=headers('user_bob')).json())
    client.post('/api/tickets', json=slow, headers=headers('user_bob'))
    assert all(t['incident'] for t in client.get('/api/tickets', headers=headers('user_bob')).json())


def test_cross_user_list_update_delete_and_export(client):
    alice = client.post('/api/tickets', json={**PAYLOAD, 'title': 'Alice private ticket', 'owner_id': 'user_bob'}).json()
    bob_headers = headers('user_bob')
    assert client.get('/api/tickets', headers=bob_headers).json() == []
    assert client.patch('/api/tickets/' + alice['id'], json={'status': 'Resolved'}, headers=bob_headers).status_code == 404
    assert client.delete('/api/tickets/' + alice['id'], headers=bob_headers).status_code == 404
    assert 'Alice private ticket' not in client.get('/api/export', headers=bob_headers).text
    bob = client.post('/api/tickets', json={**PAYLOAD, 'title': 'Bob private ticket'}, headers=bob_headers).json()
    assert [t['id'] for t in client.get('/api/tickets', headers=bob_headers).json()] == [bob['id']]
    assert [t['id'] for t in client.get('/api/tickets').json()] == [alice['id']]
    assert client.get('/api/tickets').json()[0]['status'] == 'Triaged'
    assert client.delete('/api/tickets/' + alice['id']).status_code == 204
    assert client.delete('/api/tickets/' + alice['id']).status_code == 404
    assert client.get('/api/tickets').json() == []
    assert [t['id'] for t in client.get('/api/tickets', headers=bob_headers).json()] == [bob['id']]


def test_csv_formula_injection_is_escaped(client):
    client.post('/api/tickets', json={**PAYLOAD, 'title': '=SUM(1,2)'})
    assert "'=SUM(1,2)" in client.get('/api/export').text


def test_concurrent_ticket_creation_preserves_every_ticket(client):
    def create(index):
        response = client.post('/api/tickets', json={**PAYLOAD, 'title': f'Concurrent ticket {index}'})
        assert response.status_code == 200
        return response.json()['id']
    with ThreadPoolExecutor(max_workers=4) as workers:
        ids = list(workers.map(create, range(4)))
    assert len(set(ids)) == 4
    assert {ticket['id'] for ticket in client.get('/api/tickets').json()} == set(ids)


def test_incident_windows_match_brute_force_with_overlaps_and_boundaries():
    generator = Random(37)
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for _ in range(50):
        minutes = [generator.randrange(100) for _ in range(25)] + [0, 15, 30]
        times = [base + timedelta(minutes=minute) for minute in minutes]
        tickets = [{'product': 'LMS', 'subcategory': 'Performance / availability', 'submitted_at': time.isoformat()} for time in times]
        expected = [
            any(start <= time <= start + timedelta(minutes=30) and
                sum(start <= other <= start + timedelta(minutes=30) for other in times) >= 3
                for start in times)
            for time in times
        ]
        assert [ticket['incident'] for ticket in module.incident_flags(tickets)] == expected
