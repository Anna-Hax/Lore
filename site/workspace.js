import { call, finishLogin, logout, loggedIn, hosted, sameOrigin } from './mcp-client.js';

const $ = id => document.getElementById(id);
function node(tag, attrs = {}, ...children) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key.startsWith('on') && typeof value === 'function') element.addEventListener(key.slice(2), value);
    else if (value !== false && value != null) element.setAttribute(key, value);
  }
  element.append(...children.flat(Infinity).filter(value => value != null));
  return element;
}
const p = text => node('p', {}, text);
const link = (text, href, cls = '') => node('a', { href, class: cls }, text);
const panel = (title, ...children) => node('section', { class: 'card panel' }, node('h3', {}, title), ...children);
const money = value => { try { const n = BigInt(value); return `${n / 10n ** 18n}.${(n % 10n ** 18n).toString().padStart(18, '0').replace(/0+$/, '') || '0'} 0G`; } catch { return 'Unavailable'; } };
const short = value => typeof value === 'string' && value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value || '—';
const addr = value => /^0x[0-9a-fA-F]{40}$/.test(value || '');
function showError(box, error) {
  box.querySelector(':scope > .error')?.remove();
  box.append(node('p', { class: 'error', role: 'alert' }, error.message || String(error)));
}
function button(label, run, primary = false) {
  const element = node('button', { type: 'button', class: primary ? 'primary' : '' }, label);
  element.onclick = async () => {
    element.disabled = true;
    try { await run(); } catch (error) { showError(element.closest('section') || $('accountBody'), error); }
    finally { element.disabled = false; }
  };
  return element;
}
function copyRow(value) {
  const code = node('code', {}, value), copy = button('Copy', async () => {
    await navigator.clipboard.writeText(value);
    copy.textContent = 'Copied'; setTimeout(() => { copy.textContent = 'Copy'; }, 1400);
  });
  return node('div', { class: 'copy-row' }, code, copy);
}
function confirmAction(title, description) {
  const dialog = $('review'); $('review-title').textContent = title; $('review-copy').textContent = description;
  dialog.returnValue = 'cancel'; dialog.showModal();
  return new Promise(resolve => dialog.addEventListener('close', () => resolve(dialog.returnValue === 'confirm'), { once: true }));
}
async function perform(title, description, name, args = {}) {
  if (!await confirmAction(title, description)) return;
  const box = panel('Action progress', p('Waiting for the gateway. Check status before retrying.'));
  $('actions').replaceChildren(box); box.scrollIntoView({ behavior: 'smooth', block: 'center' });
  try { await actionResult(await call(name, args), box); }
  catch (error) { box.replaceChildren(node('h3', {}, title)); showError(box, error); box.append(p('The action may have reached the gateway. Check your agent or wallet before trying again.')); }
}
async function actionResult(data, box) {
  if (!loggedIn() || !box.isConnected) return;
  box.replaceChildren(node('h3', {}, 'Action progress'));
  if (data.human_approval_required || data.status === 'waiting_for_approval') {
    const url = sameOrigin(data.approve_url);
    const id = data.checkpoint_id || box.dataset.checkpoint;
    if (!id) throw new Error('The gateway did not provide an approval ID.');
    box.dataset.checkpoint = id;
    sessionStorage.setItem('lore.web.checkpoint', id);
    box.append(p(data.action || 'Fresh World ID approval is required for this action.'),
      link('Open World ID approval ↗', url, 'button primary'),
      p('Return here after approval. A denial or expiry sends nothing.'),
      button('I approved · continue', async () => { await actionResult(await call('lore_continue', { checkpoint_id: id }), box); }));
    return;
  }
  sessionStorage.removeItem('lore.web.checkpoint');
  if (data.tx_hashes?.length) {
    box.append(p('Transactions sent. Check their receipts for the final on-chain result.'));
    data.tx_hashes.forEach(hash => box.append(node('p', { class: 'address' }, hash)));
  } else box.append(p(data.message || data.next || 'No transaction was sent.'));
  box.append(button('Refresh account', renderAccount));
}
async function overview() {
  if (hosted()) {
    try { const response = await fetch('/api/overview', { cache: 'no-store' }); if (response.ok) return { ...await response.json(), archived: false }; }
    catch { /* The saved snapshot is labelled below. */ }
  }
  const response = await fetch('data/snapshot.json');
  if (!response.ok) throw new Error('Public deployment data could not be loaded.');
  return { ...await response.json(), archived: true };
}

let accountRun = 0;
async function renderAccount() {
  const run = ++accountRun;
  const box = $('accountBody'); box.replaceChildren();
  if (!hosted() || !loggedIn()) {
    box.append(panel('World ID sign-in',
      p('Sign in through your Lore gateway to load your identity, linked wallets, and royalties.'),
      link('Connect with World ID →', 'login.html', 'button primary')));
  } else {
    const results = await Promise.allSettled([call('lore_whoami'), call('lore_wallet'), call('lore_claimable')]);
    if (run !== accountRun || !loggedIn()) return;
    const [person, walletData, earnings] = results.map(item => item.status === 'fulfilled' ? item.value : null);
    if (person) box.append(node('p', { class: 'account-identity' }, 'Signed in with World ID · person ', node('code', {}, short(person.person))));
    else showError(box, results[0].reason);
    if (walletData) {
      const wallets = walletData.wallets || [];
      box.append(panel('Linked wallets', wallets.length ? node('ul', { class: 'record-list' }, wallets.map(wallet =>
        node('li', {}, node('p', { class: 'address' }, wallet.address), p('Lore wallet (Turnkey) · Lore may sign only Lore calls'),
          p(`${money(wallet.native_wei)}${wallet.author_token ? ` · author token ${short(wallet.author_token)}` : ' · no author token yet (lore_link_token)'}`)))) : p('No wallet yet. Create your Lore wallet below.')));
    } else showError(box, results[1].reason);
    if (earnings) {
      const total = BigInt(earnings.total || 0);
      const claim = button('Review royalty claim', () => perform('Claim royalties', `Claim ${money(earnings.total)} into the wallets that earned it?`, 'lore_claim'), true);
      claim.disabled = total <= 0n;
      box.append(panel('Royalties', node('p', { class: 'amount' }, money(earnings.total)),
        p('Royalties in 0G from your accepted research nodes. Your wallet also pays gas in 0G.'), claim,
        Object.keys(earnings.by_node || {}).length ? node('details', {}, node('summary', {}, 'By research node'),
          node('ul', { class: 'record-list' }, Object.entries(earnings.by_node).map(([id, amount]) => node('li', {}, `Node #${id} · ${money(amount)}`)))) : null));
    } else showError(box, results[2].reason);
  }
  const managed = panel('Create a Lore wallet', p('You own the Turnkey account. Lore may sign only authorized Lore calls for you.'),
    hosted() && loggedIn() ? (() => {
      const form = node('form'), label = node('label', {}, 'Wallet recovery email'), input = node('input', { type: 'email', autocomplete: 'email', required: true });
      const submit = node('button', { type: 'submit', class: 'primary' }, 'Create Lore wallet'); label.append(input); form.append(label, submit);
      form.onsubmit = async event => { event.preventDefault(); submit.disabled = true; try {
        if (await confirmAction('Create wallet', `Create and link a Turnkey wallet for ${input.value}?`)) { await call('lore_create_wallet', { email: input.value }); await renderAccount(); }
      } catch (error) { showError(form, error); } finally { submit.disabled = false; } };
      return form;
    })() : link('Sign in to create a wallet →', 'login.html', 'button'));
  box.append(node('div', { class: 'workspace-grid' }, managed));
}

const TOOLS = [
  ['lore_inbox', 'What needs your attention'], ['lore_list_topics', 'Browse topics'], ['lore_get_topic', 'Topic graph and public metadata'],
  ['lore_submit', 'Stake and submit research'], ['lore_my_vote_tasks', 'Votes waiting for you'], ['lore_get_vote_task', 'Read an eligible vote task'],
  ['lore_vote', 'Cast your vote'], ['lore_buy', 'Buy a topic pass'], ['lore_read_topic', 'Read a topic you own'],
  ['lore_claimable', 'Royalties you can claim'], ['lore_claim', 'Claim royalties'], ['lore_report_leak', 'Report leaked text'],
  ['lore_check_proof', 'Verify a TEE proof receipt'], ['lore_create_wallet', 'Create a Lore wallet'], ['lore_wallet', 'Wallets and balances'],
  ['lore_create_wallet', 'Create your Lore (Turnkey) wallet'], ['lore_link_token', 'Link your comfy author token'], ['lore_whoami', 'Your person and wallets'], ['lore_continue', 'Continue an approved action'],
];
function renderAgent(data) {
  const url = data.archived ? '<gateway>/mcp' : (data.mcp_url || `${location.origin}/mcp`);
  $('agentBody').replaceChildren(panel('MCP endpoint',
    p('Use your own MCP-capable agent. Lore hosts the gateway; your agent does the reasoning and asks for approval when needed.'),
    copyRow(url), node('h4', {}, 'Claude Code'), copyRow(`claude mcp add --transport http lore ${url}`),
    node('ul', { class: 'bullets' },
      node('li', {}, 'Sign in with World ID: one person, one vote, however many agents you run.'),
      node('li', {}, 'Self-held wallets sign locally. Lore wallets permit delegated Lore calls; configured gateways request fresh World ID approval.'),
      node('li', {}, 'Content tools check on-chain access, vote eligibility or role before returning anything.')),
    node('details', {}, node('summary', {}, `${TOOLS.length} available MCP tools`),
      node('ul', { class: 'tools' }, TOOLS.map(([name, description]) => node('li', {}, node('code', {}, name), node('span', {}, description)))))));
}
function renderActivity(data) {
  const box = $('activityBody'); box.replaceChildren();
  const pending = sessionStorage.getItem('lore.web.checkpoint');
  const approval = panel('Human checkpoints',
    p('Before Lore signs a stake, purchase, vote or claim, your agent may ask for fresh World ID approval for that one action. Denied or expired approvals send nothing.'));
  if (pending && loggedIn()) approval.append(p(`Unfinished action: ${pending}`), button('Check or continue approval', async () => {
    const resultBox = panel('Approval progress', p('Checking approval…')); resultBox.dataset.checkpoint = pending;
    $('actions').replaceChildren(resultBox); await actionResult(await call('lore_continue', { checkpoint_id: pending }), resultBox);
  }, true));
  else approval.append(p('Approval links appear in your agent when an action needs your decision.'));
  const checkpoints = Array.isArray(data.checkpoints) ? data.checkpoints : [];
  if (checkpoints.length) approval.append(node('details', {}, node('summary', {}, 'Indexed checkpoint activity'),
    node('ul', { class: 'record-list' }, checkpoints.map(item => node('li', {}, `${item.action || 'Agent action'} · ${item.status || 'Pending'}`)))));
  const topics = new Map((data.topics || []).map(topic => [topic.topic_id, topic.title || topic.meta?.title]));
  const reports = panel('Leak tracing', p('Every delivered copy carries a wallet-keyed invisible watermark. A match identifies the delivered copy; it does not by itself prove who leaked it or ban a person.'));
  if (data.archived) reports.append(node('p', { class: 'info' }, 'Reports below are from a saved deployment snapshot.'));
  const list = Array.isArray(data.reports) ? data.reports : [];
  reports.append(list.length ? node('ul', { class: 'record-list' }, list.map(report => node('li', {},
    node('strong', {}, `Report #${report.report_id} · ${report.matched ? 'Traced' : 'No match'}`),
    p(topics.get(report.topic_id) || `Topic #${report.topic_id}`),
    report.matched ? p(`Matched copy: ${report.matched_wallet || '—'} · ${Number.isFinite(report.score_bps) ? `${(report.score_bps / 100).toFixed(1)}% match` : 'score unavailable'}`) : p('No known copy matched.')))) : p('No leak reports indexed.'));
  box.append(node('div', { class: 'workspace-grid' }, approval, reports));
}
const CONTRACTS = [
  ['LoreRoles', 'Roles: verifier, curator, leak detector'], ['PersonRegistry', 'One World ID person, many linked wallets'],
  ['TopicGraph', 'Topics and node commit graph'], ['Submissions', 'Stakes, verifier reports and votes'],
  ['Access', 'Soulbound topic passes'], ['Royalties', 'Sale splits and claims'], ['Reports', 'Leak reports and traced matches'],
  ['AuthorTokens', "Each author's comfy token"],
  ['LockVault', "Buyers' author tokens, locked 30 days"],
];
function renderContracts(data) {
  const chain = data.chain || {}, map = chain.contracts || {};
  const box = $('contractsBody'); box.replaceChildren();
  if (data.archived) box.append(node('p', { class: 'info' }, 'These addresses belong to a saved deployment snapshot. Open this page on your gateway for current addresses.'));
  const card = panel(`${chain.name || '0G Galileo Testnet'}${chain.chain_id ? ` · chain ${chain.chain_id}` : ''}`,
    link('Open the chain explorer ↗', 'https://chainscan-galileo.0g.ai/', 'external-link'));
  card.append(node('ul', { class: 'contract-list' }, CONTRACTS.map(([name, role]) => node('li', { class: 'contract' },
    node('span', { class: 'name' }, name), addr(map[name])
      ? link(short(map[name]), `https://chainscan-galileo.0g.ai/address/${map[name]}`)
      : node('span', {}, 'Address unavailable'), node('span', { class: 'role' }, role)))));
  box.append(card);
}

let topicRun = 0;
async function renderTopic() {
  const run = ++topicRun;
  const container = $('topicAccess'); container.replaceChildren();
  const match = /^#topic\/(\d+)$/.exec(location.hash);
  if (!match || Number(match[1]) < 1) { container.hidden = true; return; }
  container.hidden = false;
  const id = Number(match[1]);
  container.append(node('div', { class: 'block-head' }, node('h2', {}, `Topic #${id} access`), link('← Browse public topics', 'explore.html#topics')));
  if (!hosted() || !loggedIn()) {
    container.append(panel('Sign in to buy or read', p('Public topic metadata is in the explorer. A wallet and Lore gateway sign-in are required to buy or read your watermarked copy.'),
      link('Connect with World ID →', `login.html#topic/${id}`, 'button primary')));
    return;
  }
  const [topic, balance] = await Promise.all([call('lore_get_topic', { topic_id: id }), call('lore_wallet')]);
  if (run !== topicRun || !loggedIn()) return;
  const wallets = balance.wallets || [];
  const selector = node('select', { 'aria-label': 'Paying wallet' }, wallets.length
    ? wallets.map(wallet => node('option', { value: wallet.address }, `${short(wallet.address)} · ${money(wallet.native_wei)}`))
    : node('option', { value: '' }, 'Link a wallet first'));
  const reading = panel('Your watermarked copy', p('Only a wallet with topic access can read the research.'));
  const read = button('Read my copy', async () => {
    const copy = await call('lore_read_topic', { topic_id: id });
    if (run !== topicRun || !loggedIn() || !reading.isConnected) return;
    reading.replaceChildren(node('h3', {}, 'Your watermarked copy'), p(`Delivered to ${copy.wallet}. Do not redistribute.`));
    for (const item of copy.nodes || []) reading.append(panel(item.meta?.title || `Node #${item.node_id}`,
      p(`Parents: ${(item.parents || []).join(', ') || 'Root node'}`), node('div', { class: 'research' }, item.text)));
  }, true);
  const buy = button('Review purchase', async () => {
    if (!selector.value) throw new Error('Link a wallet in Account & wallets first.');
    const quote = await call('lore_buy', { topic_id: id, wallet: selector.value });
    const description = (quote.confirm || '').replace(/\s*Call again with confirm=true\.?$/, '');
    await perform('Buy topic pass', `${description} Paying wallet: ${selector.value}. The contract charges the current price when the transaction executes.`,
      'lore_buy', { topic_id: id, wallet: selector.value, confirm: true });
  });
  container.append(panel(topic.meta?.title || `Topic #${id}`, p(topic.meta?.description || 'Public metadata pending.'),
    node('p', { class: 'amount' }, money(topic.price)), p('The price can change as nodes are accepted.'),
    node('label', {}, 'Paying wallet', selector), node('div', { class: 'button-row' }, read, buy)), reading);
}

async function render() {
  $('connection').hidden = !hosted();
  if (hosted()) $('connection').textContent = loggedIn() ? 'Gateway · signed in' : 'Gateway · signed out';
  $('auth').textContent = loggedIn() ? 'Sign out' : 'Sign in';
  $('auth').href = 'login.html';
  const data = await overview();
  renderAgent(data); renderActivity(data); renderContracts(data);
  await Promise.allSettled([renderAccount(), renderTopic()]).then(results => results.forEach((item, index) => {
    if (item.status === 'rejected') showError(index === 0 ? $('accountBody') : $('topicAccess'), item.reason);
  }));
  const target = document.getElementById(location.hash.slice(1).split('/')[0]);
  if (target) requestAnimationFrame(() => target.scrollIntoView({ behavior: 'instant', block: 'start' }));
}
$('auth').onclick = async event => {
  if (!loggedIn()) return;
  event.preventDefault(); logout(); sessionStorage.removeItem('lore.web.checkpoint'); $('actions').replaceChildren(); await render();
};
window.addEventListener('hashchange', () => { renderTopic().catch(error => showError($('topicAccess'), error)); });
let loginError;
try { await finishLogin(); } catch (error) { loginError = error; }
try { await render(); } catch (error) { showError($('accountBody'), error); }
if (loginError) showError($('accountBody'), loginError);
