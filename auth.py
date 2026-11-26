"""Verify Clerk session tokens before trusting their user IDs."""

from functools import lru_cache

import jwt
from fastapi import Header, HTTPException, Request
from jwt import PyJWKClient, PyJWKClientConnectionError, PyJWKClientError


@lru_cache(maxsize=8)
def jwks_client(issuer: str) -> PyJWKClient:
    # This URL comes from server configuration, never from an untrusted token.
    return PyJWKClient(f'{issuer}/.well-known/jwks.json', timeout=5, lifespan=300)


def current_scope(
    request: Request,
    authorization: str | None = Header(default=None),
    workspace: str | None = Header(default=None, alias='X-Daybreak-Workspace'),
) -> str:
    unauthorized = HTTPException(401, 'Authentication required', headers={'WWW-Authenticate': 'Bearer'})
    if not authorization:
        raise unauthorized
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        raise unauthorized
    token = parts[1]
    settings = request.app.state.settings
    try:
        signing_key = jwks_client(settings.issuer).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token, signing_key.key, algorithms=['RS256'], issuer=settings.issuer,
            options={'require': ['exp', 'iat', 'nbf', 'iss', 'sub', 'azp', 'sid'], 'verify_aud': False},
            leeway=5,
        )
        if (not isinstance(claims['sub'], str) or not claims['sub'].startswith('user_') or
                not isinstance(claims['sid'], str) or not claims['sid'].startswith('sess_') or
                claims['azp'] not in settings.allowed_origins or
                claims.get('sts', 'active') != 'active'):
            raise unauthorized
        # Bound how long a removed member's previously issued token can remain usable.
        if not 0 < int(claims['exp']) - int(claims['iat']) <= 120:
            raise unauthorized
        # Clerk's default claims identify the active organization only when
        # this user is a member. V2 nests the claims; V1 uses top-level fields.
        version = claims.get('v')
        if version == 2:
            if 'org_id' in claims or 'org_role' in claims:
                raise unauthorized
            organization = claims.get('o')
            if organization is None:
                org_id = None
                role = None
            elif isinstance(organization, dict):
                org_id, role = organization.get('id'), organization.get('rol')
                if not isinstance(org_id, str) or not org_id.startswith('org_') or not isinstance(role, str) or not role:
                    raise unauthorized
            else:
                raise unauthorized
        elif version is None or version == 1:
            if 'o' in claims:
                raise unauthorized
            org_id, role = claims.get('org_id'), claims.get('org_role')
            if org_id is not None and (not isinstance(org_id, str) or not org_id.startswith('org_') or not isinstance(role, str) or not role):
                raise unauthorized
            if org_id is None and role is not None:
                raise unauthorized
        else:
            raise unauthorized
        selected_workspace = org_id or 'personal'
        if workspace != selected_workspace:
            raise HTTPException(409, 'Workspace changed. Please try again.')
        return org_id or claims['sub']
    except PyJWKClientConnectionError:
        raise HTTPException(503, 'Authentication service temporarily unavailable') from None
    except (jwt.InvalidTokenError, PyJWKClientError, TypeError, ValueError, KeyError):
        raise unauthorized from None
