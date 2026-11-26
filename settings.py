"""Runtime configuration. Values come from the process environment only."""

import os
from dataclasses import dataclass
from urllib.parse import urlsplit


def _origin(value: str, name: str) -> str:
    value = value.strip().rstrip('/')
    parsed = urlsplit(value)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or
            parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
        raise RuntimeError(f'{name} must be an origin such as https://example.com')
    if parsed.scheme != 'https' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise RuntimeError(f'{name} must use HTTPS except on localhost')
    return value


@dataclass(frozen=True)
class Settings:
    publishable_key: str
    issuer: str
    allowed_origins: frozenset[str]
    database_url: str

    @classmethod
    def from_environment(cls):
        publishable_key = os.environ.get('CLERK_PUBLISHABLE_KEY', '').strip()
        issuer = os.environ.get('CLERK_ISSUER_URL', '').strip()
        origins = os.environ.get('CLERK_ALLOWED_ORIGINS', '').strip()
        if not publishable_key.startswith(('pk_test_', 'pk_live_')) or not issuer or not origins:
            raise RuntimeError('Set CLERK_PUBLISHABLE_KEY, CLERK_ISSUER_URL and CLERK_ALLOWED_ORIGINS before starting Daybreak')
        issuer = _origin(issuer, 'CLERK_ISSUER_URL')
        allowed_origins = frozenset(_origin(origin, 'CLERK_ALLOWED_ORIGINS') for origin in origins.split(',') if origin.strip())
        if not allowed_origins:
            raise RuntimeError('CLERK_ALLOWED_ORIGINS must contain at least one origin')

        database_url = os.environ.get('DATABASE_URL', '').strip()
        production = os.environ.get('APP_ENV', 'development').lower() == 'production'
        if production and (not publishable_key.startswith('pk_live_') or
                           not issuer.startswith('https://') or
                           any(not origin.startswith('https://') for origin in allowed_origins)):
            raise RuntimeError('Production requires a live Clerk instance and HTTPS origins')
        if not database_url:
            if production:
                raise RuntimeError('DATABASE_URL is required in production')
            database_url = 'sqlite:///./data/daybreak.sqlite3'
        if database_url.startswith('postgres://'):
            database_url = 'postgresql+psycopg://' + database_url[len('postgres://'):]
        elif database_url.startswith('postgresql://'):
            database_url = 'postgresql+psycopg://' + database_url[len('postgresql://'):]
        if production and not database_url.startswith('postgresql+psycopg://'):
            raise RuntimeError('Production requires a PostgreSQL DATABASE_URL')
        if not database_url.startswith(('postgresql+psycopg://', 'sqlite:///')):
            raise RuntimeError('DATABASE_URL must use PostgreSQL or SQLite')
        return cls(publishable_key, issuer, allowed_origins, database_url)
