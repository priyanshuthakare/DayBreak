def test_landing_links_to_public_workspace_shell(client):
    landing = client.get('/', headers={'Authorization': ''})
    assert landing.status_code == 200
    assert 'A calmer start to' in landing.text
    assert 'href="/app"' in landing.text

    workspace = client.get('/app', headers={'Authorization': ''})
    assert workspace.status_code == 200
    assert 'id="auth-screen"' in workspace.text
    assert 'src="/static/app.js"' in workspace.text
    assert workspace.headers['cache-control'] == 'no-cache'
    assert client.get('/static/app.js').headers['cache-control'] == 'no-cache'
