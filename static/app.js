const $ = selector => document.querySelector(selector);
let detailReturnFocus = null;
let tickets = [], currentId = null;
let clerk = null, activeSessionId = null, activeOrganizationId = null, activeIdentityKey;
let authEpoch = 0, refreshGeneration = 0, signInMounted = false, userButtonMounted = false, orgSwitcherMounted = false;
let latestRefresh = Promise.resolve();

const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const toast = message => { const el = $('#toast'); el.textContent = message; el.classList.add('show'); setTimeout(() => el.classList.remove('show'), 3000); };
class SessionChanged extends Error {}
const showError = error => { if (!(error instanceof SessionChanged)) toast(error.message); };

async function authorizedFetch(url, options = {}) {
  const epoch = authEpoch;
  const workspace = activeOrganizationId || 'personal';
  const session = clerk?.session;
  if (!session || session.id !== activeSessionId) throw new Error('Please sign in to continue');
  const token = await session.getToken(activeOrganizationId ? {organizationId: activeOrganizationId} : undefined);
  if (epoch !== authEpoch) throw new SessionChanged();
  if (!token) throw new Error('Your session has ended. Please sign in again.');
  const headers = new Headers(options.headers || {});
  headers.set('Authorization', 'Bearer ' + token);
  headers.set('X-Daybreak-Workspace', workspace);
  const response = await fetch(url, {...options, headers, cache: 'no-store'});
  if (epoch !== authEpoch) throw new SessionChanged();
  if (!response.ok) {
    let message = 'Something went wrong';
    try { const data = await response.json(); if (typeof data.detail === 'string') message = data.detail; } catch {}
    if (epoch !== authEpoch) throw new SessionChanged();
    throw new Error(message);
  }
  return {response, epoch};
}
async function api(url, options) {
  const {response, epoch} = await authorizedFetch(url, options);
  const data = response.status === 204 ? null : await response.json();
  if (epoch !== authEpoch) throw new SessionChanged();
  return data;
}
function deadline(t) { return new Date(new Date(t.submitted_at).getTime() + t.sla_hours * 3600000); }
function sla(t) { if (t.status === 'Resolved') return 'Resolved'; const mins = Math.floor((deadline(t) - Date.now()) / 60000); if (mins < 0) return `${Math.ceil(-mins / 60)}h overdue`; if (mins < 60) return `${mins}m left`; return `${Math.floor(mins / 60)}h ${mins % 60}m left`; }
function render() {
  const open = tickets.filter(t => t.status !== 'Resolved');
  $('#stat-total').textContent = open.length; $('#stat-review').textContent = open.filter(t => t.human_review).length; $('#stat-risk').textContent = open.filter(t => deadline(t) - Date.now() <= 3600000).length; $('#stat-kb').textContent = tickets.length ? Math.round(tickets.filter(t => t.kb).length / tickets.length * 100) + '%' : '0%'; $('#count').textContent = tickets.length;
  const current = $('#category-filter').value; const categories = [...new Set(tickets.map(t => t.category))].sort(); $('#category-filter').innerHTML = '<option value="">All categories</option>' + categories.map(c => `<option ${c === current ? 'selected' : ''}>${esc(c)}</option>`).join('');
  const q = $('#search').value.toLowerCase(); const priority = $('#priority-filter').value; const category = $('#category-filter').value;
  const shown = tickets.filter(t => (!q || `${t.title} ${t.requester} ${t.id}`.toLowerCase().includes(q)) && (!priority || t.priority === priority) && (!category || t.category === category));
  $('#tickets').innerHTML = shown.map(t => `<tr data-id="${esc(t.id)}"><td class="request-cell"><button type="button" class="ticket-title">${esc(t.title)}</button>${t.human_review ? ' <span class="ticket-flag">Review flagged</span>' : ''}${t.incident ? ' <span class="ticket-flag">Possible incident</span>' : ''}<span class="ticket-meta">${esc(t.requester)}<span class="mobile-meta"> · ${esc(t.product)} · ${esc(t.status)}</span><span class="desktop-id"> · #${esc(t.id.slice(0, 8))}</span></span></td><td class="product-cell">${esc(t.product)}</td><td class="priority-cell"><span class="sr-only">Priority: </span><span class="pill ${esc(t.priority.toLowerCase())}">${esc(t.priority)}</span></td><td class="status-cell">${esc(t.status)}</td><td class="sla-cell ${t.status !== 'Resolved' && deadline(t) - Date.now() <= 3600000 ? 'sla-risk' : ''}"><span class="sr-only">SLA: </span>${sla(t)}</td><td class="open-cell" aria-hidden="true">›</td></tr>`).join('');
  $('#empty').hidden = shown.length !== 0;
  $('#queue-table').hidden = shown.length === 0;
  $('#empty-title').textContent = tickets.length ? 'No matching tickets' : 'Your queue is clear';
  $('#empty-copy').textContent = tickets.length ? 'Try another search or filter.' : 'Create a ticket to get started.';
  const counts = {}; tickets.forEach(t => counts[t.category] = (counts[t.category] || 0) + 1); $('#category-chart').innerHTML = Object.entries(counts).sort((a,b)=>b[1]-a[1]).map(([name,n]) => `<div class="bar-row"><div class="bar-head"><span>${esc(name)}</span><span>${n}</span></div><div class="bar"><i style="width:${n / Math.max(1,tickets.length) * 100}%"></i></div></div>`).join('') || '<p>Add a ticket to see the breakdown.</p>';
}
function refresh() {
  const generation = ++refreshGeneration;
  const pending = api('/api/tickets').then(updated => {
    if (generation !== refreshGeneration) return latestRefresh;
    tickets = updated;
    if (currentId && !tickets.some(ticket => ticket.id === currentId)) {
      currentId = null; $('#detail-overlay').hidden = true; $('#detail-content').textContent = '';
    }
    render();
  });
  latestRefresh = pending;
  return pending;
}
function showDetail(id) {
  const t = tickets.find(x => x.id === id); if (!t) return;
  const row = [...document.querySelectorAll('#tickets tr')].find(item => item.dataset.id === id);
  detailReturnFocus = row?.querySelector('.ticket-title') || $('#new-ticket');
  currentId = id; $('#detail-id').textContent = '#' + t.id.slice(0, 8);
  $('#detail-content').innerHTML = `<h2 id="detail-title">${esc(t.title)}</h2><span class="ticket-meta">${esc(t.requester)} · ${esc(t.product)} · ${new Date(t.submitted_at).toLocaleString()}</span><p class="desc">${esc(t.description)}</p>${t.human_review ? `<div class="notice"><b>Human review needed.</b> ${esc(t.review_reason)}</div>` : ''}${t.incident ? '<div class="notice"><b>Possible incident.</b> Three or more similar LMS performance tickets were submitted within 30 minutes. Consider a shared notice and investigate.</div>' : ''}<div class="detail-block detail-grid"><div><span>Category</span><strong>${esc(t.category)} / ${esc(t.subcategory)}</strong></div><div><span>Priority & SLA</span><strong>${esc(t.priority)} · ${t.sla_hours}h · ${sla(t)}</strong></div><div><span>Suggested route</span><strong>${esc(t.queue)} / ${esc(t.assignee_group)}</strong></div><div><label for="detail-status">Status</label><select id="detail-status">${['New','Triaged','Waiting on user','Resolved'].map(s => `<option ${t.status === s ? 'selected' : ''}>${s}</option>`).join('')}</select></div></div><details class="detail-block detail-disclosure"><summary>Why this triage?</summary><p><b>Category:</b> ${esc(t.category_reason)}\n<b>Priority:</b> ${esc(t.priority_reason)}\n<b>Rule confidence:</b> ${Math.round(t.confidence*100)}% (heuristic estimate)</p></details><details class="detail-block detail-disclosure"><summary>Suggested knowledge</summary><h3>${t.kb ? esc(t.kb.title) : 'No confident match found'}</h3><p>${t.kb ? esc(t.kb.content) : esc(t.kb_skeleton)}</p><p>Keyword match: ${t.kb_score}% · heuristic score</p></details><details class="detail-block detail-disclosure"><summary>Reply draft</summary><p>${esc(t.reply_source)} · Review before sending</p><p class="reply">${esc(t.reply)}</p><button class="secondary copy-button" id="copy-reply">Copy draft</button></details><div class="detail-block"><button class="delete-button" id="delete-ticket">Delete ticket</button></div>`;
  $('#detail-overlay').hidden = false;
  $('[data-close-detail]').focus();
  $('#detail-status').addEventListener('change', async e => {
    const select = e.target; select.disabled = true;
    try { await api('/api/tickets/' + encodeURIComponent(id), {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:select.value})}); await refresh(); toast('Status updated'); }
    catch(err) { select.value = t.status; showError(err); }
    finally { select.disabled = false; }
  });
  $('#copy-reply').onclick = async () => { try { await navigator.clipboard.writeText(t.reply); toast('Draft copied'); } catch { toast('Unable to copy draft'); } };
  $('#delete-ticket').onclick = async e => {
    const message = activeOrganizationId
      ? 'Delete this ticket for everyone in this workspace? This cannot be undone.'
      : 'Delete this ticket? This cannot be undone.';
    if (!window.confirm(message)) return;
    const button = e.currentTarget; button.disabled = true;
    try {
      await api('/api/tickets/' + encodeURIComponent(id), {method:'DELETE'});
      $('#detail-overlay').hidden = true; currentId = null;
      await refresh(); $('#new-ticket').focus(); toast('Ticket deleted');
    } catch (err) { showError(err); }
    finally { button.disabled = false; }
  };
}

function setAuthState({session, organization}) {
  // Wait for Clerk to finish loading the active organization.
  if (session && organization === undefined) return;
  const sessionId = session?.id || null;
  const organizationId = sessionId ? (organization?.id || null) : null;
  const identityKey = sessionId ? sessionId + ':' + (organizationId || 'personal') : null;
  if (identityKey === activeIdentityKey) return;
  activeIdentityKey = identityKey;
  activeSessionId = sessionId; activeOrganizationId = organizationId; authEpoch++;
  tickets = []; currentId = null;
  $('#ticket-form').reset(); $('#form-error').textContent = '';
  $('#detail-content').textContent = ''; $('#detail-id').textContent = '';
  $('#search').value = ''; $('#priority-filter').value = ''; $('#category-filter').value = '';
  $('#toast').classList.remove('show');
  $('#modal').hidden = true; $('#detail-overlay').hidden = true;
  render();
  $('#workspace').hidden = !sessionId;
  $('#workspace-nav').hidden = !sessionId;
  $('#account-controls').hidden = !sessionId;
  $('#auth-screen').hidden = !!sessionId;
  if (sessionId) {
    if (signInMounted) { clerk.unmountSignIn($('#sign-in')); signInMounted = false; }
    if (!userButtonMounted) { clerk.mountUserButton($('#user-button')); userButtonMounted = true; }
    if (!orgSwitcherMounted) {
      clerk.mountOrganizationSwitcher($('#organization-switcher'), {
        afterSelectOrganizationUrl: '/app', afterSelectPersonalUrl: '/app',
        afterCreateOrganizationUrl: '/app', afterLeaveOrganizationUrl: '/app',
      });
      orgSwitcherMounted = true;
    }
    refresh().catch(showError);
  } else {
    if (userButtonMounted) { clerk.unmountUserButton($('#user-button')); userButtonMounted = false; }
    if (orgSwitcherMounted) { clerk.unmountOrganizationSwitcher($('#organization-switcher')); orgSwitcherMounted = false; }
    $('#auth-message').hidden = true;
    if (!signInMounted) {
      clerk.mountSignIn($('#sign-in'), {
        withSignUp: true, forceRedirectUrl: '/app', signUpForceRedirectUrl: '/app',
        appearance: {
          variables: {
            colorPrimary: '#26382c',
            colorForeground: '#242a25',
            colorMutedForeground: '#5f6c61',
            borderRadius: '0.7rem',
            spacing: '0.85rem',
          },
          elements: {
            rootBox: {width: '100%'},
            cardBox: {width: '100%', maxWidth: '100%', boxShadow: '0 10px 32px #26382c14'},
            card: {padding: 'clamp(1.25rem, 5vw, 2rem)'},
            headerTitle: {fontSize: '1.5rem', lineHeight: 1.25, letterSpacing: '-0.025em'},
            socialButtonsBlockButton: {minHeight: '2.75rem'},
            formFieldInput: {minHeight: '2.75rem'},
            formButtonPrimary: {minHeight: '2.75rem'},
          },
        },
      });
      signInMounted = true;
    }
  }
}

async function startAuthentication() {
  try {
    const response = await fetch('/api/config', {cache:'no-store'});
    if (!response.ok) throw new Error('Sign-in is unavailable. Please try again later.');
    const config = await response.json();
    const domain = atob(config.publishable_key.split('_')[2]).slice(0, -1);
    if (!/^[a-z0-9.-]+$/i.test(domain)) throw new Error('Invalid Clerk configuration');
    const loadScript = (src, publishableKey) => new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.async = true;
      script.crossOrigin = 'anonymous';
      if (publishableKey) script.dataset.clerkPublishableKey = publishableKey;
      script.src = 'https://' + domain + src;
      script.onload = resolve; script.onerror = reject; document.head.appendChild(script);
    });
    await loadScript('/npm/@clerk/ui@1/dist/ui.browser.js');
    await loadScript('/npm/@clerk/clerk-js@6.48.0/dist/clerk.browser.js', config.publishable_key);
    clerk = window.Clerk;
    await clerk.load({
      ui: {ClerkUI: window.__internal_ClerkUICtor},
      signInFallbackRedirectUrl: '/app', signUpFallbackRedirectUrl: '/app',
      afterSignOutUrl: '/app',
    });
    // Force the initial signed-out state to render even though it also has no session ID.
    activeIdentityKey = undefined;
    setAuthState({session: clerk.session, organization: clerk.organization});
    clerk.addListener(() => setAuthState({session: clerk.session, organization: clerk.organization}));
  } catch {
    $('#auth-message').textContent = 'Sign-in is unavailable. Please check the configuration or try again later.';
    $('#auth-message').hidden = false;
  }
}

const navigation = document.querySelectorAll('.nav');
navigation.forEach(button => {
  if (button.classList.contains('active')) button.setAttribute('aria-current', 'page');
  button.addEventListener('click', () => {
    navigation.forEach(item => {
      item.classList.toggle('active', item === button);
      if (item === button) item.setAttribute('aria-current', 'page');
      else item.removeAttribute('aria-current');
    });
    ['queue','insights','about'].forEach(view => $('#'+view+'-view').hidden = view !== button.dataset.view);
  });
});
['#search','#priority-filter','#category-filter'].forEach(s => $(s).addEventListener('input',render));
$('#tickets').addEventListener('click', e => { const row = e.target.closest('tr'); if (row) showDetail(row.dataset.id); });
function closeTicketForm() { $('#modal').hidden = true; $('#new-ticket').focus(); }
function closeDetail() {
  const row = [...document.querySelectorAll('#tickets tr')].find(item => item.dataset.id === currentId);
  const target = detailReturnFocus?.isConnected ? detailReturnFocus : row?.querySelector('.ticket-title');
  $('#detail-overlay').hidden = true; currentId = null;
  (target || $('#new-ticket')).focus();
}
$('#new-ticket').onclick = () => {
  $('#modal').hidden=false; $('#ticket-form').reset(); $('#form-error').textContent='';
  $('#ticket-form input[name="requester"]').focus();
};
$('[data-close]').onclick = closeTicketForm;
$('[data-close-detail]').onclick = closeDetail;
document.addEventListener('keydown', e => {
  const overlay = !$('#detail-overlay').hidden ? $('#detail-overlay') : (!$('#modal').hidden ? $('#modal') : null);
  if (!overlay) return;
  if (e.key === 'Escape') { e.preventDefault(); if (overlay.id === 'modal') closeTicketForm(); else closeDetail(); return; }
  if (e.key !== 'Tab') return;
  const focusable = [...overlay.querySelectorAll('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, a[href], [tabindex]:not([tabindex="-1"])')].filter(element => element.getClientRects().length);
  if (!focusable.length) return;
  const first = focusable[0], last = focusable[focusable.length - 1];
  if (e.shiftKey && (document.activeElement === first || !overlay.contains(document.activeElement))) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && (document.activeElement === last || !overlay.contains(document.activeElement))) { e.preventDefault(); first.focus(); }
});
$('#ticket-form').onsubmit = async e => {
  e.preventDefault(); const form=e.currentTarget; const data=Object.fromEntries(new FormData(form));
  if(data.submitted_at) data.submitted_at = new Date(data.submitted_at).toISOString(); else delete data.submitted_at;
  const button=form.querySelector('[type=submit]'); button.disabled=true; button.textContent='Triaging...';
  try { const ticket=await api('/api/tickets',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}); $('#modal').hidden=true; await refresh(); showDetail(ticket.id); toast('Ticket triaged'); }
  catch(err) { if (!(err instanceof SessionChanged)) $('#form-error').textContent=err.message; }
  finally { button.disabled=false; button.innerHTML='Triage ticket <span>✳</span>'; }
};
$('#export').onclick = async () => {
  try {
    const {response, epoch} = await authorizedFetch('/api/export');
    const blob = await response.blob();
    if (epoch !== authEpoch) throw new SessionChanged();
    const url = URL.createObjectURL(blob); const link = document.createElement('a');
    link.href = url; link.download = 'triage-log.csv'; document.body.appendChild(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (err) { showError(err); }
};
startAuthentication();
setInterval(() => {
  render();
  if (activeSessionId && document.visibilityState === 'visible') refresh().catch(showError);
}, 30000);
document.addEventListener('visibilitychange', () => {
  if (activeSessionId && document.visibilityState === 'visible') refresh().catch(showError);
});
