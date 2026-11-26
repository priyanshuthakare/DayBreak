from conftest import headers


PAYLOAD = {'title': 'Shared workspace ticket', 'description': 'A sufficiently detailed support request', 'requester': 'Team member', 'product': 'LMS'}


def team_headers(user, org, *, version=2):
    if version == 2:
        claims = {'v': 2, 'o': {'id': org, 'rol': 'member'}}
    else:
        claims = {'org_id': org, 'org_role': 'org:member'}
    return headers(user, workspace=org, changes=claims)


def test_members_share_a_queue_and_other_workspaces_are_isolated(client):
    alice_team = team_headers('user_alice', 'org_team_a')
    bob_team = team_headers('user_bob', 'org_team_a')
    other_team = team_headers('user_bob', 'org_team_b')
    personal = client.post('/api/tickets', json={**PAYLOAD, 'title': 'Personal ticket'}).json()
    shared = client.post('/api/tickets', json=PAYLOAD, headers=alice_team).json()
    assert [t['id'] for t in client.get('/api/tickets', headers=bob_team).json()] == [shared['id']]
    assert [t['id'] for t in client.get('/api/tickets').json()] == [personal['id']]
    assert client.get('/api/tickets', headers=other_team).json() == []
    assert 'Shared workspace ticket' in client.get('/api/export', headers=bob_team).text
    assert 'Shared workspace ticket' not in client.get('/api/export', headers=other_team).text
    assert 'Personal ticket' not in client.get('/api/export', headers=bob_team).text
    assert client.patch('/api/tickets/' + shared['id'], json={'status': 'Resolved'}, headers=other_team).status_code == 404
    assert client.delete('/api/tickets/' + shared['id'], headers=other_team).status_code == 404
    assert client.patch('/api/tickets/' + shared['id'], json={'status': 'Resolved'}, headers=bob_team).status_code == 200
    assert client.get('/api/tickets', headers=alice_team).json()[0]['status'] == 'Resolved'
    assert client.delete('/api/tickets/' + shared['id'], headers=bob_team).status_code == 204
    assert client.get('/api/tickets', headers=alice_team).json() == []
    assert [t['id'] for t in client.get('/api/tickets').json()] == [personal['id']]


def test_clerk_v1_and_v2_tokens_address_the_same_organization(client):
    v1 = team_headers('user_alice', 'org_team_a', version=1)
    v2 = team_headers('user_bob', 'org_team_a')
    created = client.post('/api/tickets', json=PAYLOAD, headers=v1).json()
    assert client.get('/api/tickets', headers=v2).json()[0]['id'] == created['id']


def test_workspace_header_cannot_select_a_different_signed_scope(client):
    assert client.get('/api/tickets', headers=headers(workspace='org_team_a')).status_code == 409
    wrong = headers('user_alice', workspace='org_team_b', changes={'v': 2, 'o': {'id': 'org_team_a', 'rol': 'member'}})
    for method, path, body in (
        ('GET', '/api/tickets', None),
        ('POST', '/api/tickets', PAYLOAD),
        ('PATCH', '/api/tickets/unknown', {'status': 'Resolved'}),
        ('DELETE', '/api/tickets/unknown', None),
        ('GET', '/api/export', None),
    ):
        assert client.request(method, path, json=body, headers=wrong).status_code == 409
    assert client.get('/api/tickets', headers={'X-Daybreak-Workspace': ''}).status_code == 409


def test_incomplete_or_conflicting_organization_claims_fail_closed(client):
    for claims in (
        {'v': 2, 'o': {'id': 'org_team_a'}},
        {'v': 2, 'o': {'id': 'user_other', 'rol': 'member'}},
        {'v': 2, 'o': 'org_team_a'},
        {'v': 2, 'org_id': 'org_team_a', 'org_role': 'org:member'},
        {'org_id': 'org_team_a'},
        {'org_role': 'org:member'},
        {'v': 3},
    ):
        assert client.get('/api/tickets', headers=headers(changes=claims)).status_code == 401
