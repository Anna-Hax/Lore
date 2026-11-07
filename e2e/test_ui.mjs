// Run: PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs node --test e2e/test_ui.mjs
// Browser fixtures intercept MCP calls. The gateway test uses demo login, never a real World proof.
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = fileURLToPath(new URL('../site/', import.meta.url));
const origin = 'http://127.0.0.1:4173';
const wallet = '0x' + '1'.repeat(40);
let browser;
before(async () => { browser = await chromium.launch({ headless: true }); });
after(async () => { await browser?.close(); });

async function setup({ authenticated = true, viewport, failures = {}, responses = {} } = {}) {
  const context = await browser.newContext({ viewport: viewport || { width: 1280, height: 900 }, reducedMotion: 'reduce' });
  const page = await context.newPage(), calls = [], errors = [];
  page.on('pageerror', error => errors.push(error.message));
  if (authenticated) await context.addInitScript(() => sessionStorage.setItem('lore.web.session', JSON.stringify({ access_token: 'fixture-token', client_id: 'fixture', expires_at: Date.now() + 3600000 })));
  const fixtures = {
    lore_whoami: { person: '0xperson', wallets: [wallet] },
    lore_wallet: { wallets: [{ address: wallet, native_wei: '2000000000000000000', lore_can_sign: true, author_token: '0x' + '2'.repeat(40) }] },
    lore_claimable: { total: '900000000000000000', by_node: { 1: '900000000000000000' } },
    lore_claim: { human_approval_required: true, checkpoint_id: 'claim-fixture', approve_url: origin + '/checkpoint/claim-fixture' },
    lore_get_topic: { topic_id: 1, meta: { title: 'Research fixture', description: 'Public metadata' }, price: 2000000, nodes: [{ node_id: 1, meta: { title: 'Node one' } }] },
    lore_read_topic: { wallet, nodes: [{ node_id: 1, text: 'Private\u200bresearch <script>evil()</script>', parents: [] }] },
    lore_buy: { confirm: 'This costs about 0.0603 0G.' },
    lore_continue: { status: 'sent', tx_hashes: ['0xconfirmed'] },
    ...responses,
  };
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (url.pathname === '/mcp') {
      const req = route.request().postDataJSON(); calls.push(req);
      assert.equal(route.request().headers().authorization, 'Bearer fixture-token');
      if (req.method === 'notifications/initialized') return route.fulfill({ status: 202 });
      const name = req.params?.name;
      let result = req.method === 'initialize' ? { protocolVersion: '2025-11-25', capabilities: {}, serverInfo: { name: 'fixture', version: '1' } }
        : failures[name] ? { isError: true, content: [{ type: 'text', text: failures[name] }] }
          : { structuredContent: fixtures[name] || {}, content: [] };
      if (name === 'lore_buy' && req.params.arguments.confirm) result = { structuredContent: { human_approval_required: true, checkpoint_id: 'buy-fixture', approve_url: origin + '/checkpoint/buy-fixture' } };
      return route.fulfill({ headers: { 'Mcp-Session-Id': 'fixture-session' }, contentType: 'application/json',
        body: JSON.stringify({ jsonrpc: '2.0', id: req.id, result }) });
    }
    let path = url.pathname.replace(/^\/app\//, '/');
    if (path === '/') path = '/index.html';
    try {
      const body = await readFile(root + path);
      const type = path.endsWith('.js') ? 'text/javascript' : path.endsWith('.css') ? 'text/css' : path.endsWith('.json') ? 'application/json' : 'text/html';
      return route.fulfill({ body, contentType: type });
    } catch { return route.fulfill({ status: 404, body: 'Not found' }); }
  });
  return { page, context, calls, errors };
}

test('landing and explorer use only active destinations, with public data and Lore art', async () => {
  const { page, context, errors } = await setup({ authenticated: false });
  await page.goto(origin + '/index.html');
  assert.equal(await page.locator('a[href="explore.html#connect"],a[href="explore.html#contracts"]').count(), 0);
  await page.getByRole('link', { name: 'Get the MCP URL' }).click();
  await page.getByRole('heading', { name: 'Connect your agent' }).waitFor();
  assert.equal(new URL(page.url()).hash, '#agent');
  await page.goto(origin + '/explore.html');
  await page.locator('#topicList li').first().waitFor();
  assert.equal(await page.locator('#steps,#mcpBody,#leakBody,#checkBody,#contractsBody,#stats').count(), 0);
  assert.equal(await page.locator('.lore-art #lore-line').count(), 1);
  assert(await page.getByRole('link', { name: 'Open this topic on your gateway' }).count() > 0);
  await page.screenshot({ path: '/tmp/lore-explorer-simple.png', fullPage: true });
  assert.deepEqual(errors, []); await context.close();
});

test('workspace has meaningful human sections, not agent action forms or duplicate topic list', async () => {
  const { page, context, calls, errors } = await setup({ authenticated: false, viewport: { width: 390, height: 844 } });
  await page.goto(origin + '/workspace.html');
  for (const title of ['Account & wallets', 'Connect your agent', 'Reports & approvals', 'Contracts'])
    await page.getByRole('heading', { name: title }).waitFor();
  assert.equal(await page.locator('aside,textarea').count(), 0);
  assert.equal(await page.getByRole('button', { name: /submit research|vote yes|vote no|report a leak/i }).count(), 0);
  assert.equal(await page.getByText('Static preview', { exact: true }).count(), 0);
  assert.equal(await page.getByText('Report #1', { exact: false }).count(), 1);
  assert.equal(await page.locator('.contract').count(), 9);
  assert.equal(calls.length, 0);
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({ path: '/tmp/lore-workspace-simple-mobile.png', fullPage: true });
  await page.goto(origin + '/login.html');
  await page.getByLabel('Lore gateway address').waitFor();
  assert.equal(await page.getByRole('button', { name: 'Continue with World ID' }).count(), 0);
  await page.screenshot({ path: '/tmp/lore-login-mobile.png', fullPage: true });
  assert.deepEqual(errors, []); await context.close();
});

test('World ID account data, the Lore wallet and royalties share one screen', async () => {
  const { page, context, errors } = await setup();
  await page.goto(origin + '/app/workspace.html#account');
  await page.getByText('Signed in with World ID').waitFor();
  await page.getByText('0.9 0G', { exact: true }).waitFor();
  await page.getByText('Lore wallet (Turnkey) · Lore may sign only Lore calls').waitFor();
  assert.equal(await page.getByRole('button', { name: /link wallet/i }).count(), 0); // Turnkey only: no self-held wallets
  assert.equal(await page.locator('textarea').count(), 0);
  assert.deepEqual(errors, []); await context.close();
});

test('topic buy and gated reading remain human controls, with review and approval', async () => {
  const { page, context, calls, errors } = await setup();
  await page.goto(origin + '/app/workspace.html#topic/1');
  await page.getByRole('button', { name: 'Read my copy' }).click();
  await page.getByText('Your watermarked copy').first().waitFor();
  assert.equal(await page.locator('.research').textContent(), 'Private\u200bresearch <script>evil()</script>');
  assert.equal(await page.locator('.research script').count(), 0);
  await page.getByRole('button', { name: 'Review purchase' }).click();
  await page.locator('dialog[open]').waitFor();
  assert(!calls.some(item => item.params?.arguments?.confirm));
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await page.getByRole('button', { name: 'Review purchase' }).click();
  await page.getByRole('button', { name: 'Confirm', exact: true }).click();
  await page.getByRole('link', { name: 'Open World ID approval' }).waitFor();
  assert(calls.some(item => item.params?.name === 'lore_buy' && item.params.arguments.confirm));
  assert(!calls.some(item => item.params?.name === 'lore_continue'));
  await page.getByRole('link', { name: 'Sign out' }).click();
  assert.equal(await page.locator('.research').count(), 0);
  assert.deepEqual(errors, []); await context.close();
});

test('refused research stays hidden; royalty claim approval can continue', async () => {
  const { page, context, calls } = await setup({ failures: { lore_read_topic: 'buy this topic first' } });
  await page.goto(origin + '/app/workspace.html#topic/1');
  await page.getByRole('button', { name: 'Read my copy' }).click();
  await page.getByRole('alert').filter({ hasText: 'buy this topic first' }).waitFor();
  assert.equal(await page.locator('.research').count(), 0);
  await page.getByRole('button', { name: 'Review royalty claim' }).click();
  await page.getByRole('button', { name: 'Confirm', exact: true }).click();
  await page.getByRole('link', { name: 'Open World ID approval' }).waitFor();
  await page.getByRole('button', { name: 'I approved · continue' }).click();
  await page.getByText('0xconfirmed', { exact: true }).waitFor();
  assert(calls.some(item => item.params?.name === 'lore_continue'));
  await context.close();
});

test('bad OAuth state remains an error and never exchanges a code', async () => {
  const { page, context, calls } = await setup({ authenticated: false });
  await page.goto(origin + '/app/workspace.html?code=untrusted&state=bad');
  await page.getByRole('alert').filter({ hasText: 'Login expired' }).waitFor();
  assert.equal(new URL(page.url()).search, ''); assert.equal(calls.length, 0);
  await context.close();
});

test('real gateway connects the new login page through OAuth to World ID/demo login', { skip: !process.env.GATEWAY_PYTHON }, async () => {
  const child = spawn(process.env.GATEWAY_PYTHON, [fileURLToPath(new URL('ui_gateway_fixture.py', import.meta.url))]);
  const context = await browser.newContext();
  try {
    const base = await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('Gateway fixture did not start')), 15000);
      child.stdout.once('data', data => { clearTimeout(timeout); resolve(data.toString().trim()); });
      child.once('exit', code => { clearTimeout(timeout); reject(new Error(`Gateway fixture exited ${code}`)); });
      child.stderr.on('data', data => process.stderr.write(data));
    });
    for (let i = 0; i < 50; i++) {
      try { if ((await fetch(base + '/app/login.html')).ok) break; } catch {}
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    const page = await context.newPage();
    await page.goto(base + '/app/login.html');
    await page.getByRole('button', { name: 'Continue with World ID' }).click();
    await page.getByLabel('Demo person name').fill('UI test person');
    await page.getByRole('button', { name: 'Approve', exact: true }).click();
    await page.getByText('Signed in with World ID').waitFor();
    assert.equal(new URL(page.url()).pathname, '/app/workspace.html');
    assert.equal(await page.locator('.error').count(), 0);
    await page.screenshot({ path: '/tmp/lore-workspace-simple-desktop.png', fullPage: true });
  } finally { await context.close(); child.kill('SIGTERM'); }
});
