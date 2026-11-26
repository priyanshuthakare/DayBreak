import csv
import io
import json
import os
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib import request

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import storage
from auth import current_scope
from settings import Settings

ROOT = Path(__file__).resolve().parent
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = Settings.from_environment()
    app.state.store = storage.create_store(app.state.settings.database_url)
    try:
        yield
    finally:
        app.state.store.dispose()


app = FastAPI(title='Ticket Triage', lifespan=lifespan)
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')


@app.middleware('http')
async def response_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    else:
        # Public pages and assets use stable URLs across releases.
        response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

PRODUCTS = ['LMS', 'Absence', 'Performance', 'ATS', 'Compensation', 'LXP', 'Succession', 'HR Core', 'Reporting', 'Other']
SLAS = {'Low': 48, 'Medium': 24, 'High': 4, 'Critical': 1}
STATUSES = ['New', 'Triaged', 'Waiting on user', 'Resolved']

class Intake(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=10, max_length=5000)
    requester: str = Field(min_length=2, max_length=100)
    product: str
    submitted_at: datetime | None = None

class StatusUpdate(BaseModel):
    status: str

def now():
    return datetime.now(timezone.utc)

def articles():
    result = []
    for path in sorted((ROOT / 'kb').glob('*.md')):
        content = path.read_text(encoding='utf-8')
        lines = content.splitlines()
        result.append({'id': path.stem, 'title': lines[0].removeprefix('# ').strip(), 'content': '\n'.join(lines[1:]).strip()})
    return result

def match_article(text, product):
    terms = set(re.findall(r'[a-z0-9]+', text.lower())) - {'the','and','for','with','this','that','have','from','into','please','when','cant','cannot','will','they','their','what','does','not','how','can','our','are','was','has','after','about','user','users','issue','help','more'}
    best, score = None, 0
    for article in articles():
        words = set(re.findall(r'[a-z0-9]+', (article['title'] + ' ' + article['content']).lower()))
        overlap = terms & words
        value = min(1, len(overlap) / max(3, min(len(terms), 8)))
        if product.lower() in words:
            value = min(1, value + .12)
        if value > score:
            best, score = article, value
    return (best, round(score * 100)) if score >= .28 else (None, round(score * 100))

def optional_llm(ticket, result):
    key, base, model = os.getenv('OPENAI_API_KEY'), os.getenv('OPENAI_BASE_URL', 'https://api.openai.com/v1'), os.getenv('OPENAI_MODEL')
    if os.getenv('ENABLE_AI_DRAFTS', '').lower() != 'true' or not key or not model or result['human_review']:
        return result
    prompt = ('Draft a concise, empathetic first response for this HR support ticket. Do not assert a fix or request sensitive information. '
              'Never include compensation figures. Return only the reply. Ticket: ' + json.dumps(ticket) + '\nSuggested article: ' + (result['kb']['title'] if result['kb'] else 'none'))
    payload = json.dumps({'model': model, 'messages': [{'role': 'user', 'content': prompt}], 'temperature': 0.2}).encode()
    try:
        req = request.Request(base.rstrip('/') + '/chat/completions', data=payload, headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
        with request.urlopen(req, timeout=12) as response:
            content = json.load(response)['choices'][0]['message']['content'].strip()
        if content:
            result['reply'] = content
            result['reply_source'] = 'AI-assisted draft'
    except Exception:
        result['reply_source'] = 'Template draft · AI unavailable'
    return result

def triage(ticket):
    text = (ticket['title'] + ' ' + ticket['description']).lower()
    product = ticket['product']
    categories = {'LMS': ('Learning', 'Course access'), 'Absence': ('Absence management', 'Leave request'), 'Performance': ('Performance', 'Review workflow'), 'ATS': ('Recruiting', 'Candidate workflow'), 'Compensation': ('Compensation', 'Compensation letter'), 'LXP': ('Learning experience', 'Content playback'), 'Succession': ('Succession', 'Plan data'), 'HR Core': ('HR Core', 'Account access'), 'Reporting': ('Reporting', 'Headcount report'), 'Other': ('General support', 'Needs review')}
    category, subcategory = categories[product]
    if product == 'LMS' and any(x in text for x in ['login', 'log in', 'sign in', 'sso']): subcategory = 'Login / SSO'
    if product == 'LMS' and any(x in text for x in ['slow', 'slowness', 'outage']): subcategory = 'Performance / availability'
    if product == 'Absence' and 'balance' in text: subcategory = 'Leave balance'
    sensitive = product in ('Compensation', 'Absence') or ('manager' in text and 'approv' in text) or 'payroll' in text
    if product == 'Compensation' or any(x in text for x in ['security breach', 'data breach']): priority, reason = 'Critical', 'Sensitive compensation or security issue needs immediate human attention.'
    elif product == 'Absence' or any(x in text for x in ['tomorrow', 'urgent', 'deadline', 'outage']): priority, reason = 'High', 'Time-sensitive or leave-related issue needs prompt attention.'
    elif product in ('LXP', 'Reporting', 'HR Core') or 'password reset' in text: priority, reason = 'Low', 'A standard request with no immediate deadline indicated.'
    else: priority, reason = 'Medium', 'A workflow is blocked, with no immediate deadline indicated.'
    article, score = match_article(text, product)
    if article:
        guidance = f"A relevant starting point is “{article['title']}”. {article['content']}"
    else:
        guidance = 'We are checking the right next steps for this issue. Please share any non-sensitive error message and when the issue started.'
    reply = f"Hi {ticket['requester']},\n\nThanks for reaching out. I understand you need help with {ticket['title'].lower()}.\n\n{guidance}\n\nIf the issue continues, please share the time it occurred and any non-sensitive error message so we can investigate. We aim to respond within {SLAS[priority]} hour(s).\n\nThanks,\nPeople Tech Support"
    return optional_llm(ticket, {'category': category, 'subcategory': subcategory, 'priority': priority, 'sla_hours': SLAS[priority], 'confidence': 0.85 if product != 'Other' else 0.5, 'category_reason': f'The selected product is {product}; the issue text indicates {subcategory.lower()}.', 'priority_reason': reason, 'human_review': sensitive, 'review_reason': 'Sensitive people data or an approval workflow requires human review.' if sensitive else None, 'queue': 'People Tech L1', 'assignee_group': 'People Tech · ' + product, 'kb': article, 'kb_score': score, 'kb_skeleton': None if article else f'# {ticket["title"]}\n\n## Symptoms\nDescribe the issue.\n\n## Troubleshooting\nDocument verified steps.\n\n## Escalation\nIdentify the appropriate support group.', 'reply': reply, 'reply_source': 'Template draft'})

def create_ticket(data):
    if data.product not in PRODUCTS: raise HTTPException(422, 'Unknown product')
    submitted = data.submitted_at or now()
    if submitted.tzinfo is None: submitted = submitted.replace(tzinfo=timezone.utc)
    ticket = data.model_dump(mode='json')
    ticket.update({'id': str(uuid.uuid4()), 'submitted_at': submitted.isoformat(), 'created_at': now().isoformat(), 'status': 'Triaged'})
    ticket.update(triage(ticket))
    return ticket

def incident_flags(tickets):
    candidates = []
    for index, ticket in enumerate(tickets):
        ticket['incident'] = False
        if ticket['product'] == 'LMS' and ticket.get('subcategory') == 'Performance / availability':
            candidates.append((datetime.fromisoformat(ticket['submitted_at']), index))
    candidates.sort()
    difference = [0] * (len(candidates) + 1)
    left = 0
    for right, (submitted, _) in enumerate(candidates):
        while submitted - candidates[left][0] > timedelta(minutes=30):
            left += 1
        if right - left + 1 >= 3:
            difference[left] += 1
            difference[right + 1] -= 1
    active = 0
    for position, (_, index) in enumerate(candidates):
        active += difference[position]
        tickets[index]['incident'] = active > 0
    return tickets

@app.get('/')
def index(): return FileResponse(ROOT / 'static' / 'landing.html')

@app.get('/app')
def workspace(): return FileResponse(ROOT / 'static' / 'index.html')

@app.get('/api/config')
def public_config(request: Request):
    settings = request.app.state.settings
    return {'publishable_key': settings.publishable_key}

@app.get('/api/tickets')
def list_tickets(request: Request, scope: str = Depends(current_scope)):
    return incident_flags(storage.list_tickets(request.app.state.store, scope))

@app.post('/api/tickets')
def add_ticket(data: Intake, request: Request, scope: str = Depends(current_scope)):
    ticket = create_ticket(data)
    storage.add_ticket(request.app.state.store, scope, ticket)
    return ticket

@app.patch('/api/tickets/{ticket_id}')
def update_ticket(ticket_id: str, update: StatusUpdate, request: Request, scope: str = Depends(current_scope)):
    if update.status not in STATUSES: raise HTTPException(422, 'Unknown status')
    ticket = storage.update_status(request.app.state.store, scope, ticket_id, update.status)
    if not ticket: raise HTTPException(404, 'Ticket not found')
    return ticket

@app.delete('/api/tickets/{ticket_id}', status_code=204)
def delete_ticket(ticket_id: str, request: Request, scope: str = Depends(current_scope)):
    if not storage.delete_ticket(request.app.state.store, scope, ticket_id):
        raise HTTPException(404, 'Ticket not found')
    return Response(status_code=204)

@app.get('/api/export')
def export(request: Request, scope: str = Depends(current_scope)):
    tickets = incident_flags(storage.list_tickets(request.app.state.store, scope))
    output = io.StringIO(newline='')
    fields = ['id','title','requester','product','submitted_at','status','category','subcategory','priority','sla_hours','category_reason','priority_reason','human_review','incident']
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction='ignore')
    writer.writeheader()
    for ticket in tickets:
        safe = {key: ("'" + value if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')) else value) for key, value in ticket.items()}
        writer.writerow(safe)
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="triage-log.csv"'})
