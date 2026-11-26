# Daybreak

Daybreak helps People Technology teams triage support requests, review suggested priorities and guidance, and track work through to resolution. People review every suggestion; replies are never sent automatically.

The service currently available at https://daybreak-ticket-triage.onrender.com is an earlier public version with a shared, temporary data store. Do not enter real data there until the changes in this checkout are configured, tested and deployed.

## How workspaces work

Sign in and use the workspace selector to choose a personal workspace or a Clerk organization. Personal tickets are private to the signed-in user. An organization has a shared queue: every active member can view, create, update, export and delete its tickets. Members cannot access another organization or another user's personal queue. Organization administrators can invite and manage members through Clerk's organization controls.

Open a ticket to review its classification, suggested knowledge, SLA and draft reply. Change its status as work progresses. Deletion requires confirmation and removes the ticket for everyone in the selected workspace. CSV export contains only the selected workspace's tickets. Incident indicators compare tickets within the selected workspace.

## Run locally

Use Python 3.10 or later. Create and activate a virtual environment, then install the dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

In the selected Clerk application's development instance, enable Organizations and choose **Membership optional** so both individual and team workspaces are available. Configure who may create organizations and invite members. Obtain the instance's publishable key and Frontend API URL. Set these process environment variables in your own terminal; do not commit keys or paste secrets into a chat. The issuer is the instance's Frontend API URL, including `https://` and without a trailing slash. Each allowed origin must exactly match the browser URL's scheme, hostname and port:

```powershell
$env:CLERK_PUBLISHABLE_KEY = '<development publishable key>'
$env:CLERK_ISSUER_URL = 'https://<development frontend API hostname>'
$env:CLERK_ALLOWED_ORIGINS = 'http://localhost:8000'
python -m uvicorn app:app --reload
```

Open http://localhost:8000 and enter the workspace. The application reads process environment variables and does not load an environment file. Local development defaults to `data/daybreak.sqlite3`; set `DATABASE_URL` explicitly to use another SQLite file or PostgreSQL database. The SQLite file is ignored by Git.

Clerk's publishable key is intentionally served to the browser; no Clerk secret key is needed by this integration. The server verifies the session token signature using the configured instance's JWKS endpoint, validates its issuer, lifetime, session and authorized origin, and derives the user and active organization from signed claims. Requests must also match the workspace selected in the interface. Set `CLERK_PUBLISHABLE_KEY` and `CLERK_ISSUER_URL` to the same instance. Tokens without an allowed `azp` claim are rejected.

Membership and session changes are reflected when Clerk issues a fresh session token. A previously issued token remains usable until it expires, with a five-second clock-skew allowance. The server accepts token lifetimes of at most two minutes; retain Clerk's usual one-minute lifetime or configure a shorter one. The app does not provide separate ticket permissions for organization admins and members.

The old `data/tickets.json` is preserved and is not imported because its records have no trustworthy owner. Determine each record's rightful workspace before arranging any migration.

## Render and Clerk configuration

The selected Clerk application is `app_3McErVlcG5SzNWTmSyBosU0tUIo`. Its production instance is `ins_3MdMl1KVcxqZsMKIlshXFZoGIfw` for `daybreak.0xpriyanshu.me`. Organizations are enabled with optional membership in both instances. Development and production have separate users and organizations.

Clerk issued the following records for the `0xpriyanshu.me` DNS zone. The names below are relative to that zone. If your provider expects a full name, append `.0xpriyanshu.me` once. Keep a single DMARC record at the listed name and preserve any existing stricter policy.

| Type | Name | Value |
| --- | --- | --- |
| CNAME | `clerk.daybreak` | `frontend-api.clerk.services` |
| CNAME | `accounts.daybreak` | `accounts.clerk.services` |
| CNAME | `clkmail.daybreak` | `mail.asy073lw2cxm.clerk.services` |
| CNAME | `clk._domainkey.daybreak` | `dkim1.asy073lw2cxm.clerk.services` |
| CNAME | `clk2._domainkey.daybreak` | `dkim2.asy073lw2cxm.clerk.services` |
| TXT | `_dmarc.daybreak` | `v=DMARC1; p=none;` |

From this linked checkout, run `npx clerk deploy status --mode agent` to check DNS and TLS verification. In the production Clerk Dashboard, configure your own OAuth credentials for Google and GitHub, or disable providers that you will not offer. Use the callbacks shown by Clerk. At release, add `daybreak.0xpriyanshu.me` as a custom domain on the secured Render service and use Render's DNS target for the app hostname.

Provision persistent PostgreSQL and configure backups. In the Render service's environment settings, set:

| Variable | Value |
| --- | --- |
| `APP_ENV` | `production` |
| `DATABASE_URL` | PostgreSQL connection URL, stored privately in Render |
| `CLERK_PUBLISHABLE_KEY` | The selected application's production publishable key, already set in `render.yaml` |
| `CLERK_ISSUER_URL` | `https://clerk.daybreak.0xpriyanshu.me` |
| `CLERK_ALLOWED_ORIGINS` | `https://daybreak.0xpriyanshu.me` |

`render.yaml` sets the production mode, public Clerk configuration and allowed origin. Supply the database URL in Render. If you manage the service without Blueprint sync, copy the public values from `render.yaml` into the service's environment settings. Production startup rejects missing settings, development Clerk keys, non-HTTPS origins and SQLite. Ensure the service can reach Clerk's JWKS endpoint and the database. Production storage is separate from the old JSON file and the local database.

Before deploying, verify the selected Clerk instance and target PostgreSQL service with two authorized users in the same organization and a user outside it. Check invitation and switching, shared ticket creation, updates, export and deletion, isolation from other organizations and personal workspaces, and persistence across a restart. Configure and test database recovery. Deleting a ticket removes it from the active database; existing backups may retain it.

## Test

```powershell
python -m pip install pytest
python -m pytest -q
```

The tests sign temporary test tokens with ephemeral keys and exercise server-side verification and workspace isolation with a temporary SQLite database. `tests/test_postgres.py` also exercises the PostgreSQL driver when `DAYBREAK_TEST_POSTGRES_URL` points to a disposable local server; it is skipped otherwise. The browser harness under `tests/` uses temporary test identities and must never be deployed. These checks do not replace verification against the selected Clerk instance and hosted PostgreSQL service.

## Scope and limitations

Categories, priorities, SLA timing, routing, knowledge search and confidence use deterministic heuristics; scores are not calibrated probabilities. SLA countdowns use elapsed hours, not business hours. The incident indicator covers LMS performance requests and needs human investigation. Daybreak does not integrate with ServiceNow or monitor incidents in real time.

AI-generated drafts are disabled by default. Setting `ENABLE_AI_DRAFTS=true` with `OPENAI_API_KEY`, `OPENAI_MODEL`, and optionally `OPENAI_BASE_URL` sends ticket content to the configured provider for tickets not flagged for human review. Sensitivity rules can miss private information; assess provider terms and data handling before enabling this. If a call fails, the template remains available.
