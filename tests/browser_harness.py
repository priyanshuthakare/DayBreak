"""Local browser-test server with test accounts and ephemeral signing keys.

Run explicitly with python tests/browser_harness.py. It must never be deployed.
"""
import base64
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import jwt
import uvicorn
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.responses import PlainTextResponse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as module
import auth

PORT = 18765
ORIGIN = f'http://127.0.0.1:{PORT}'
ISSUER = 'https://clerk.example.test'
test_dir = tempfile.TemporaryDirectory(prefix='daybreak-browser-test-')
pk_payload = base64.b64encode(b'clerk.invalid$').decode()
os.environ.update({
    'APP_ENV': 'development',
    'CLERK_PUBLISHABLE_KEY': 'pk_test_' + pk_payload,
    'CLERK_ISSUER_URL': ISSUER,
    'CLERK_ALLOWED_ORIGINS': ORIGIN,
    'DATABASE_URL': 'sqlite:///' + (Path(test_dir.name) / 'tickets.sqlite3').as_posix(),
    'ENABLE_AI_DRAFTS': 'false',
})
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
fake_jwks = SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=key.public_key()))
auth.jwks_client = lambda issuer: fake_jwks


@module.app.get('/__browser_test/info')
def info():
    return {'module': module.__file__, 'root': str(module.ROOT)}


@module.app.get('/__browser_test/token/{user}', response_class=PlainTextResponse)
def token(user: str, workspace: str = 'personal'):
    if user not in ('alice', 'bob') or workspace not in ('personal', 'org_team_a', 'org_team_b'):
        return PlainTextResponse('Not found', status_code=404)
    now = datetime.now(timezone.utc)
    claims = {
        'iss': ISSUER, 'sub': 'user_' + user, 'sid': 'sess_' + user, 'azp': ORIGIN,
        'iat': now, 'nbf': now - timedelta(seconds=1), 'exp': now + timedelta(minutes=1),
    }
    if workspace != 'personal':
        claims.update({'v': 2, 'o': {'id': workspace, 'rol': 'member'}})
    return jwt.encode(claims, key, algorithm='RS256', headers={'kid': 'local-test'})


if __name__ == '__main__':
    uvicorn.run(module.app, host='127.0.0.1', port=PORT, log_level='warning')
