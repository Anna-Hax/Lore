/* Same-origin browser client for Lore's authenticated Streamable HTTP endpoint.
   No private keys, plaintext drafts or research copies are persisted. */
const SESSION = 'lore.web.session';
const PENDING = 'lore.web.login';
const read = key => { try { return JSON.parse(sessionStorage.getItem(key)); } catch { return null; } };
const save = (key, value) => sessionStorage.setItem(key, JSON.stringify(value));
const b64 = bytes => btoa(String.fromCharCode(...bytes)).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '');
const random = () => b64(crypto.getRandomValues(new Uint8Array(32)));
/* A gateway serves the site under /app/; any other non-loopback host (Vercel) proxies the gateway's paths (vercel.json).
   Loopback without /app/ is the static preview (python -m http.server). */
export const gatewayOrigin = () => location.pathname.startsWith('/app/') || !['localhost', '127.0.0.1', '[::1]'].includes(location.hostname);
export const hosted = gatewayOrigin;
export const loggedIn = () => Boolean(read(SESSION)?.access_token);
/* The OAuth client this tab registered, so the workspace can mark "this browser" among your agents. */
export const clientId = () => read(SESSION)?.client_id || null;
export function sameOrigin(url) {
  const u = new URL(url, location.origin);
  if (u.origin !== location.origin || u.username || u.password) throw new Error('The gateway returned an unexpected address.');
  return u.href;
}
/* The gateway's OAuth metadata names its own public URL; behind the Vercel proxy, use the same path on this origin. */
const here = url => new URL(new URL(url).pathname, location.origin).href;
async function json(url, options = {}) {
  const r = await fetch(sameOrigin(url), { ...options, cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(30000) });
  const d = await r.json();
  if (!r.ok) throw new Error(d.error_description || d.error || `Gateway returned HTTP ${r.status}.`);
  return d;
}
function storeTokens(d, clientId) {
  if (!d.access_token || d.token_type?.toLowerCase() !== 'bearer') throw new Error('Invalid login response.');
  save(SESSION, { ...d, client_id: clientId, expires_at: Date.now() + (d.expires_in || 3600) * 1000 });
}
export async function login() {
  if (!hosted()) throw new Error('Open this workspace on your Lore gateway to log in.');
  const metadata = await json('/.well-known/oauth-authorization-server');
  const redirect = new URL('workspace.html', location.href).href.split(/[?#]/)[0];
  const client = await json(here(metadata.registration_endpoint), {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ client_name: 'Lore web workspace', redirect_uris: [redirect],
      grant_types: ['authorization_code', 'refresh_token'], response_types: ['code'],
      token_endpoint_auth_method: 'none', scope: 'lore' }),
  });
  const verifier = random(), state = random();
  const challenge = b64(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))));
  const endpoint = here(metadata.token_endpoint);
  save(PENDING, { verifier, state, client_id: client.client_id, redirect, endpoint, route: location.hash, created: Date.now() });
  const url = new URL(here(metadata.authorization_endpoint));
  url.search = new URLSearchParams({ client_id: client.client_id, redirect_uri: redirect,
    response_type: 'code', scope: 'lore', state, code_challenge: challenge, code_challenge_method: 'S256', resource: `${location.origin}/mcp` });
  location.assign(url);
}
export async function finishLogin() {
  const q = new URLSearchParams(location.search);
  if (!q.has('code') && !q.has('error')) return;
  const pending = read(PENDING);
  sessionStorage.removeItem(PENDING);
  history.replaceState(null, '', location.pathname + (pending?.route || '#account'));
  if (!pending || q.get('state') !== pending.state || Date.now() - pending.created > 1800000) throw new Error('Login expired or did not match this tab. Please sign in again.');
  if (q.has('error')) throw new Error('World ID login was cancelled or refused. Please try again.');
  const tokens = await json(pending.endpoint, { method: 'POST', body: new URLSearchParams({
    grant_type: 'authorization_code', client_id: pending.client_id, code: q.get('code'),
    code_verifier: pending.verifier, redirect_uri: pending.redirect, resource: `${location.origin}/mcp`,
  }) });
  storeTokens(tokens, pending.client_id);
}
let refresh = null, initialization = null, sessionId = null, sequence = 0;
export function logout() {
  const old = read(SESSION);
  sessionStorage.removeItem(SESSION); sessionStorage.removeItem(PENDING);
  initialization = null; sessionId = null;
  if (old) fetch('/revoke', { method: 'POST', body: new URLSearchParams({
    token: old.refresh_token || old.access_token, client_id: old.client_id,
  }), redirect: 'error' }).catch(() => {});
}
async function token() {
  let s = read(SESSION);
  if (!s) throw new Error('Sign in with World ID to continue.');
  if (s.expires_at > Date.now() + 60000) return s.access_token;
  if (!s.refresh_token) { logout(); throw new Error('Your session expired. Sign in again.'); }
  if (!refresh) refresh = (async () => {
    const d = await json('/token', { method: 'POST', body: new URLSearchParams({
      grant_type: 'refresh_token', client_id: s.client_id, refresh_token: s.refresh_token,
    }) });
    // A sign-out during refresh must not restore a session.
    if (!read(SESSION)) throw new Error('Signed out.');
    storeTokens(d, s.client_id);
    return d.access_token;
  })().finally(() => { refresh = null; });
  return refresh;
}
async function responseMessage(response, id) {
  if (!response.headers.get('content-type')?.includes('text/event-stream')) return response.json();
  const reader = response.body.getReader(), decoder = new TextDecoder();
  let buffer = '';
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) throw new Error('Gateway closed the response before completing it.');
      buffer += decoder.decode(value, { stream: true });
      let boundary;
      while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0, boundary.index); buffer = buffer.slice(boundary.index + boundary[0].length);
        const data = frame.split(/\r?\n/).filter(l => l.startsWith('data:')).map(l => l.slice(5).trimStart()).join('\n');
        if (!data) continue;
        const msg = JSON.parse(data);
        if (msg.id === id) return msg;
      }
    }
  } finally { await reader.cancel(); }
}
async function rpc(method, params, notification = false) {
  const headers = { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream',
    Authorization: `Bearer ${await token()}`, 'MCP-Protocol-Version': '2025-11-25' };
  if (sessionId) headers['Mcp-Session-Id'] = sessionId;
  const id = ++sequence;
  const r = await fetch('/mcp', { method: 'POST', headers, redirect: 'error', cache: 'no-store',
    signal: AbortSignal.timeout(180000), body: JSON.stringify({ jsonrpc: '2.0', ...(notification ? {} : { id }), method, params }) });
  if (r.status === 401) { logout(); throw new Error('Your session expired. Sign in again.'); }
  if (!r.ok) {
    if (r.status === 404) { initialization = null; sessionId = null; }
    throw new Error(`Gateway returned HTTP ${r.status}. For an action, check your wallet or inbox before retrying.`);
  }
  sessionId = r.headers.get('Mcp-Session-Id') || sessionId;
  if (notification) { await r.body?.cancel(); return; }
  const msg = await responseMessage(r, id);
  if (msg.error) throw new Error(msg.error.message);
  return msg.result;
}
export async function call(name, args = {}) {
  if (!hosted()) throw new Error('This is a static preview. Open the workspace on your Lore gateway.');
  if (!initialization) initialization = (async () => {
    const init = await rpc('initialize', { protocolVersion: '2025-11-25', capabilities: {}, clientInfo: { name: 'lore-web', version: '1.0' } });
    if (init.protocolVersion !== '2025-11-25') throw new Error('This gateway uses an unsupported MCP version.');
    await rpc('notifications/initialized', {}, true);
  })().catch(e => { initialization = null; throw e; });
  await initialization;
  const result = await rpc('tools/call', { name, arguments: args });
  const text = (result.content || []).filter(c => c.type === 'text').map(c => c.text).join('\n');
  if (result.isError) throw new Error(text || 'The gateway could not complete this action.');
  if (result.structuredContent) return result.structuredContent;
  try { return JSON.parse(text); } catch { return { message: text }; }
}
