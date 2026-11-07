import { call, finishLogin, logout, loggedIn, hosted, sameOrigin, clientId } from './mcp-client.js?v=11';
import { format0G, formatTokens, plural, cleanError, relativeTime, absoluteTime } from './format.js?v=11';

const $ = id => document.getElementById(id);
function node(tag, attrs = {}, ...children) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key.startsWith('on') && typeof value === 'function') element.addEventListener(key.slice(2), value);
    else if (value !== false && value != null) element.setAttribute(key, value);
  }
  element.append(...children.flat(Infinity).filter(value => value != null && value !== false));
  return element;
}
const p = (text, cls) => node('p', cls ? { class: cls } : {}, text);
const link = (text, href, cls = '') => node('a', { href, class: cls }, text);
const external = (text, href, cls = '') => node('a', { href, class: cls, target: '_blank', rel: 'noopener noreferrer' }, text);
const panel = (title, ...children) => node('section', { class: 'card panel' }, node('h3', {}, title), ...children);
const short = value => typeof value === 'string' && value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value || '—';
const addr = value => /^0x[0-9a-fA-F]{40}$/.test(value || '');
const EXPLORER = 'https://chainscan-galileo.0g.ai';
const addrLink = value => addr(value) ? external(short(value), `${EXPLORER}/address/${value}`, 'mono') : node('span', { class: 'mono' }, short(value));
const tag = (text, kind = '') => node('span', { class: `tag ${kind}` }, text);
const hex = text => '0x' + Array.from(new TextEncoder().encode(text), value => value.toString(16).padStart(2, '0')).join('');
const big = value => { try { return BigInt(typeof value === 'number' ? Math.round(value) : value ?? 0); } catch { return 0n; } };
const when = ts => relativeTime(ts) ? node('time', { title: absoluteTime(ts) }, relativeTime(ts)) : null;

function showError(box, error) {
  box.querySelector(':scope > .error')?.remove();
  box.append(node('p', { class: 'error', role: 'alert' }, cleanError(error)));
}
function button(label, run, primary = false) {
  const element = node('button', { type: 'button', class: primary ? 'primary' : '' }, label);
  element.onclick = async () => {
    element.disabled = true;
    try { await run(); } catch (error) { showError(element.closest('section, li, form') || $('accountBody'), error); }
    finally { element.disabled = false; }
  };
  return element;
}
function copyRow(value, label = 'Copy') {
  const code = node('code', {}, value), copy = button(label, async () => {
    await navigator.clipboard.writeText(value);
    copy.textContent = 'Copied'; setTimeout(() => { copy.textContent = label; }, 1400);
  });
  copy.setAttribute('aria-label', `${label}: ${value}`);
  return node('div', { class: 'copy-row' }, code, copy);
}
function confirmAction(title, description, details = []) {
  const dialog = $('review'); $('review-title').textContent = title; $('review-copy').textContent = description;
  $('review-details').replaceChildren(...details);
  dialog.returnValue = 'cancel'; dialog.showModal();
  return new Promise(resolve => dialog.addEventListener('close', () => resolve(dialog.returnValue === 'confirm'), { once: true }));
}
/* Approval pages live on the gateway (or its World ID approval host). Never follow anything else. */
function approvalHref(url) {
  if (!url) return null;
  try { return sameOrigin(url); } catch { /* checked below */ }
  try { const u = new URL(url); if (u.protocol === 'https:' && !u.username && !u.password) return u.href; } catch { /* invalid */ }
  return null;
}

async function perform(title, description, name, args = {}, details = []) {
  if (!await confirmAction(title, description, details)) return;
  const box = panel('Action progress', p('Waiting for the gateway. Check status before retrying.'));
  $('actions').replaceChildren(box); box.scrollIntoView({ behavior: 'smooth', block: 'center' });
  try { await actionResult(await call(name, args), box); }
  catch (error) { box.replaceChildren(node('h3', {}, title)); showError(box, error); box.append(p('The action may have reached the gateway. Check your approvals, agent or wallet before trying again.')); }
}
async function actionResult(data, box) {
  if (!loggedIn() || !box.isConnected) return;
  box.replaceChildren(node('h3', {}, 'Action progress'));
  if (data.human_approval_required || data.status === 'waiting_for_approval') {
    const url = approvalHref(data.approve_url);
    const id = data.checkpoint_id || box.dataset.checkpoint;
    if (!id) throw new Error('The gateway did not provide an approval ID.');
    box.dataset.checkpoint = id;
    sessionStorage.setItem('lore.web.checkpoint', id);
    box.append(p(data.action ? `Approve with World ID: ${data.action}.` : 'Fresh World ID approval is required for this action.'),
      url ? external('Open World ID approval ↗', url, 'button primary') : p('Open the approval link from your agent.'),
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
let overviewData = {};
async function overview() {
  if (hosted()) {
    try { const response = await fetch('/api/overview', { cache: 'no-store' }); if (response.ok) return { ...await response.json(), archived: false }; }
    catch { /* The saved snapshot is labelled below. */ }
  }
  const response = await fetch('data/snapshot.json');
  if (!response.ok) throw new Error('Public deployment data could not be loaded.');
  return { ...await response.json(), archived: true };
}
const mcpUrl = () => overviewData.archived ? '<gateway>/mcp' : (overviewData.mcp_url || `${location.origin}/mcp`);
const contributorShare = () => {
  const bps = overviewData.archived ? null : overviewData.params?.platform_cut_bps;
  return `${Number.isFinite(bps) ? +((10000 - bps) / 100).toFixed(1) : 90}%`;
};
const topicName = id => {
  const topic = (overviewData.topics || []).find(item => item.topic_id === id);
  return topic?.title || topic?.meta?.title || `Topic #${id}`;
};

/* ---------- wallets ---------- */
let walletNotice = null;
function createWalletForm() {
  const form = node('form', { class: 'inline-form' });
  const input = node('input', { id: 'walletEmail', type: 'email', autocomplete: 'email', required: true, placeholder: 'you@example.com' });
  const submit = node('button', { type: 'submit', class: 'primary' }, 'Create Lore wallet');
  form.append(node('label', { for: 'walletEmail' }, 'Email for your Turnkey account'), node('div', { class: 'field-row' }, input, submit));
  form.onsubmit = async event => {
    event.preventDefault(); submit.disabled = true;
    try {
      if (await confirmAction('Create your Lore wallet', `Create a Turnkey wallet owned by ${input.value} and link it to your World ID?`,
        [p('You are the Turnkey root user. Lore gets delegated access to sign only Lore actions: submit, vote, buy, claim and report.')])) {
        const created = await call('lore_create_wallet', { email: input.value });
        walletNotice = created.next || null;
        await renderAccount();
      }
    } catch (error) { showError(form, error); } finally { submit.disabled = false; }
  };
  return form;
}
function revokeHelp() {
  return p(['To revoke Lore’s access, sign in at ', external('app.turnkey.com ↗', 'https://app.turnkey.com'),
    ' with the same email (you are the root user) and remove Lore’s delegated user from your sub-organisation.'], 'muted small');
}
function linkTokenForm(wallet) {
  const form = node('form', { class: 'inline-form' });
  const id = `token-${wallet.address.slice(2, 10)}`;
  const input = node('input', { id, type: 'text', required: true, spellcheck: 'false', autocomplete: 'off', placeholder: '0x… token address' });
  const submit = node('button', { type: 'submit' }, 'Sign & link token');
  form.append(node('label', { for: id }, 'Token address'), node('div', { class: 'field-row' }, input, submit),
    p('Your browser wallet signs a one-time message (no transaction). Use the wallet that launched the token on comfy.fun.', 'muted small'));
  form.onsubmit = async event => {
    event.preventDefault(); submit.disabled = true;
    try {
      const token = input.value.trim();
      if (!addr(token)) throw new Error('Enter the token’s contract address (0x followed by 40 hex characters).');
      const provider = window.ethereum;
      if (!provider?.request) throw new Error('No browser wallet detected.');
      const challenge = await call('lore_link_token', { token, wallet: wallet.address });
      if (!challenge.sign_this) throw new Error('The gateway did not return a message to sign.');
      const accounts = await provider.request({ method: 'eth_requestAccounts' });
      if (!addr(accounts?.[0])) throw new Error('Your browser wallet did not return an address.');
      const signature = await provider.request({ method: 'personal_sign', params: [hex(challenge.sign_this), accounts[0]] });
      await call('lore_link_token', { token, signature, wallet: wallet.address });
      await renderAccount();
    } catch (error) { showError(form, error); } finally { submit.disabled = false; }
  };
  return form;
}

/* ---------- account: guided setup + your activity ---------- */
function step(number, title, done, ...body) {
  return node('li', { class: `setup-step${done ? ' done' : ''}` },
    node('span', { class: 'step-mark', 'aria-hidden': 'true' }, done ? '✓' : String(number)),
    node('div', { class: 'step-body' },
      node('h3', {}, title, ' ', tag(done ? 'Done' : 'To do', done ? 'ok' : '')),
      ...body));
}
function setupSteps(data) {
  const signedIn = Boolean(data?.person);
  const wallets = data?.wallets || null;
  const list = node('ol', { class: 'setup-steps', 'aria-label': 'Set up Lore' });
  // 1. World ID
  list.append(step(1, 'Sign in with World ID', signedIn,
    signedIn ? node('p', { class: 'account-identity' }, 'Signed in with World ID · person ', node('code', {}, short(data.person)))
      : [p('Lore accepts only an Orb-verified World ID. It is your only login: one person, one vote, however many agents you run.'),
        hosted() ? link('Sign in with World ID →', 'login.html', 'button primary') : link('Open the sign-in page →', 'login.html', 'button primary')]));
  // 2. Wallet
  const loreWallet = wallets?.find(wallet => wallet.lore_can_sign);
  let walletBody;
  if (!signedIn) walletBody = p('After sign-in, Lore creates a wallet for you in your own Turnkey account.', 'muted');
  else if (!wallets) walletBody = p('Wallets could not be loaded.', 'muted');
  else {
    walletBody = [];
    if (loreWallet) {
      walletBody.push(p(['Lore wallet ', node('code', {}, short(loreWallet.address)), ' is ready.']),
        node('p', { class: 'warn-note' }, walletNotice
          ? `Next: ${walletNotice}.`
          : 'Lore can spend whatever is in this wallet on Lore actions, so keep only the 0G you mean to spend here.'),
        revokeHelp());
    } else {
      walletBody.push(p('Lore creates a wallet in your own Turnkey account, reachable by your email. You own it; Lore may sign only Lore actions (submit, vote, buy, claim, report), and each spend still needs your World ID approval.'),
        createWalletForm());
    }
  }
  list.append(step(2, 'Create your Lore wallet', Boolean(wallets?.length), walletBody));
  // 3. Fund
  const funded = Boolean(wallets?.some(wallet => big(wallet.native_wei) > 0n));
  list.append(step(3, 'Fund it with 0G', funded,
    p(['Buying, staking and gas are paid in 0G on Galileo testnet. Get test 0G from the ', external('0G faucet ↗', 'https://faucet.0g.ai'), '.']),
    wallets?.length ? node('ul', { class: 'wallet-list' }, wallets.map(wallet => node('li', {},
      node('div', { class: 'wallet-head' }, node('span', { class: 'muted small' }, wallet.lore_can_sign ? 'Lore wallet (Turnkey) · Lore may sign only Lore calls' : 'Linked wallet'), node('strong', { class: 'balance' }, format0G(wallet.native_wei))),
      copyRow(wallet.address, 'Copy address')))) : p(signedIn ? 'Create your Lore wallet first.' : 'After sign-in, your wallet address and balance appear here.', 'muted')));
  // 4. Author token
  const linked = Boolean(wallets?.some(wallet => addr(wallet.author_token)));
  list.append(step(4, 'Link your comfy author token', linked,
    p('Submitting research needs an author token: an ERC-20 your agent launched on comfy.fun. People who buy your topics also buy some of it.'),
    wallets?.length ? node('ul', { class: 'wallet-list' }, wallets.map(wallet => node('li', {},
      addr(wallet.author_token)
        ? p(['Wallet ', node('code', {}, short(wallet.address)), ' · token ', addrLink(wallet.author_token)])
        : [p(['Wallet ', node('code', {}, short(wallet.address)), ' · no token linked yet.']),
          p(['If your agent launched the token from this Lore wallet, ask it to run ', node('code', {}, 'lore_link_token'), ' with the token’s address.'], 'muted small'),
          node('details', { class: 'token-browser' }, node('summary', {}, 'Launched it from a browser wallet? Sign here'), linkTokenForm(wallet))]))) : p('After you have a wallet, link the token your agent launched.', 'muted')));
  // 5. Agent
  const own = clientId();
  const agents = data?.agents;
  const agentLinked = Boolean(agents?.some(agent => agent.client_id !== own));
  list.append(step(5, 'Add Lore to your agent', agentLinked,
    p('Add Lore to your agent. It signs in with the same World ID and uses the same Lore wallet; anything that spends still comes back to you for approval.'),
    copyRow(`claude mcp add --transport http lore ${mcpUrl()}`),
    p(['Other MCP clients: use ', node('code', {}, mcpUrl()), '. More in ', link('Connect your agent', '#agent'), '.'], 'muted small')));
  return list;
}

function royaltiesPanel(result) {
  const box = panel('Royalties');
  if (result.status === 'rejected') { showError(box, result.reason); return box; }
  const earnings = result.value;
  const claim = button('Review royalty claim', () => perform('Claim royalties', `Claim ${format0G(earnings.total)} into the wallets that earned it?`, 'lore_claim'), true);
  claim.disabled = big(earnings.total) <= 0n;
  box.append(node('p', { class: 'amount' }, format0G(earnings.total)),
    p(`${contributorShare()} of each topic's base price goes to its contributors. Claiming needs a little 0G for gas.`, 'muted'), claim,
    Object.keys(earnings.by_node || {}).length ? node('details', {}, node('summary', {}, 'By research node'),
      node('ul', { class: 'record-list' }, Object.entries(earnings.by_node).map(([id, amount]) => node('li', {}, `Node #${id} · ${format0G(amount)}`)))) : null);
  return box;
}
function tokensPanel(result) {
  const box = panel('Author tokens you bought');
  if (result.status === 'rejected') { showError(box, result.reason); return box; }
  const locks = result.value.locks || [];
  const now = Date.now() / 1000;
  const ready = locks.filter(lock => lock.claimable === true || (Number.isFinite(lock.unlock_at) && lock.unlock_at <= now));
  box.append(p('Buying a topic also buys its authors’ comfy tokens. They stay locked in Lore’s vault for 30 days, then you can claim them.', 'muted'));
  if (!locks.length) { box.append(p('No author tokens yet.')); return box; }
  box.append(node('ul', { class: 'record-list' }, locks.map(lock => {
    const open = ready.includes(lock);
    return node('li', {}, node('div', { class: 'wallet-head' }, node('strong', {}, formatTokens(lock.amount)), tag(open ? 'Unlocked' : 'Locked', open ? 'ok' : '')),
      p(['Token ', addrLink(lock.token)]),
      p(open ? ['Unlocked ', when(lock.unlock_at), ` (${absoluteTime(lock.unlock_at)})`] : ['Unlocks ', when(lock.unlock_at), ` (${absoluteTime(lock.unlock_at)})`], 'muted small'));
  })));
  const claim = button('Review token claim', () => perform('Claim unlocked author tokens',
    `Move ${plural(ready.length, 'unlocked token balance')} from Lore’s vault to the wallets that bought them?`, 'lore_claim_tokens'), true);
  claim.disabled = !ready.length;
  box.append(claim);
  return box;
}
function votesPanel(result) {
  const box = panel('Votes waiting for your agent');
  if (result.status === 'rejected') { showError(box, result.reason); return box; }
  const count = (result.value.vote_tasks || []).length;
  box.append(node('p', { class: 'amount' }, String(count)),
    p(count ? `Your agent has ${plural(count, 'submission')} to review with lore_get_vote_task and lore_vote. It can’t submit new research until these are done.`
      : 'Nothing to vote on right now. Votes appear when someone submits to a topic you contributed to.', 'muted'));
  return box;
}
function topicsPanel(result) {
  const box = panel('My topics');
  if (result.status === 'rejected') { showError(box, result.reason); return box; }
  const { owned = [], contributed = [] } = result.value;
  const list = (ids, empty, label) => ids.length
    ? node('ul', { class: 'topic-links' }, ids.map(id => node('li', {}, link(topicName(id), `#topic/${id}`), node('span', { class: 'muted small' }, ` · ${label}`))))
    : p(empty, 'muted');
  box.append(node('h4', {}, 'Bought'), list(owned, 'You haven’t bought a topic yet.', 'read your copy'),
    node('h4', {}, 'Contributed'), list(contributed, 'No accepted research from you yet.', 'you earn royalties'),
    link('Browse topics →', 'explore.html#topics', 'button'));
  return box;
}
function agentsPanel(result) {
  const box = panel('Signed-in agents');
  if (result.status === 'rejected') { showError(box, result.reason); return box; }
  const agents = result.value.agents || [];
  const own = clientId();
  box.append(p('Agents and apps logged in as you. Revoking one logs it out; it needs your World ID to sign in again.', 'muted'));
  if (!agents.length) { box.append(p('No agents are signed in.')); return box; }
  box.append(node('ul', { class: 'record-list' }, agents.map(agent => {
    const mine = agent.client_id === own;
    return node('li', {},
      node('div', { class: 'wallet-head' }, node('strong', {}, agent.name || 'MCP client'), mine ? tag('This browser', 'ok') : null),
      p([agent.created ? ['Registered ', when(agent.created), ' · '] : null, agent.expires ? ['login valid until ', absoluteTime(agent.expires)] : null], 'muted small'),
      button(mine ? 'Sign out this browser' : 'Revoke', async () => {
        if (!await confirmAction(`Log out ${agent.name || 'this agent'}?`, mine
          ? 'This browser will be signed out of Lore.'
          : 'It will need to sign in with World ID again before it can act for you.')) return;
        await call('lore_revoke_agent', { client_id: agent.client_id });
        if (mine) await signOut(); else await renderAccount();
      }));
  })));
  return box;
}

const APPROVAL_STATUS = { pending: ['Waiting for you', 'warn'], approved: ['Approved · not sent yet', 'ok'], used: ['Sent', 'ok'], denied: ['Denied', 'bad'], expired: ['Expired', ''] };
async function continueCheckpoint(id) {
  const box = panel('Approval progress', p('Checking approval…')); box.dataset.checkpoint = id;
  $('actions').replaceChildren(box); box.scrollIntoView({ behavior: 'smooth', block: 'center' });
  try { await actionResult(await call('lore_continue', { checkpoint_id: id }), box); }
  catch (error) { showError(box, error); }
}
function renderApprovals(result) {
  const box = $('approvalsBody');
  if (!result) { box.replaceChildren(p('Sign in to see the approvals your agents asked you for.', 'muted')); return; }
  box.replaceChildren();
  if (result.status === 'rejected') {
    showError(box, result.reason);
    const pending = sessionStorage.getItem('lore.web.checkpoint');
    if (pending) box.append(p(`Unfinished action: ${pending}`), button('Check or continue approval', () => continueCheckpoint(pending), true));
    return;
  }
  const approvals = result.value.approvals || [];
  if (!approvals.length) { box.append(p('No approvals yet. When your agent spends from a Lore wallet, the approval request appears here and in your agent.')); return; }
  box.append(node('ul', { class: 'record-list' }, approvals.map(item => {
    const [label, kind] = APPROVAL_STATUS[item.status] || [String(item.status || 'Unknown'), ''];
    const href = item.status === 'pending' ? approvalHref(item.approve_url) : null;
    return node('li', {},
      node('div', { class: 'wallet-head' }, node('strong', {}, item.action || 'Agent action'), tag(label, kind)),
      p([item.created ? ['Requested ', when(item.created)] : null, item.reason ? ` · ${item.reason}` : null], 'muted small'),
      item.status === 'pending' || item.status === 'approved' ? node('div', { class: 'button-row' },
        href ? external('Approve ↗', href, 'button primary') : null,
        button('Continue', () => continueCheckpoint(item.checkpoint_id))) : null);
  })));
}

let accountRun = 0;
async function renderAccount() {
  const run = ++accountRun;
  const box = $('accountBody');
  if (!hosted() || !loggedIn()) { box.replaceChildren(setupSteps(null)); renderApprovals(null); return; }
  box.setAttribute('aria-busy', 'true');
  const names = ['lore_whoami', 'lore_wallet', 'lore_claimable', 'lore_my_tokens', 'lore_my_approvals', 'lore_my_topics', 'lore_my_agents', 'lore_my_vote_tasks'];
  const settled = await Promise.allSettled(names.map(name => call(name)));
  if (run !== accountRun || !loggedIn()) return;
  box.removeAttribute('aria-busy');
  const r = Object.fromEntries(names.map((name, index) => [name, settled[index]]));
  const value = name => r[name].status === 'fulfilled' ? r[name].value : null;
  const data = { person: value('lore_whoami')?.person, wallets: value('lore_wallet')?.wallets || null, agents: value('lore_my_agents')?.agents || null };
  box.replaceChildren(setupSteps(data));
  for (const name of ['lore_whoami', 'lore_wallet']) if (r[name].status === 'rejected') showError(box, r[name].reason);
  box.append(node('h3', { class: 'activity-head' }, 'Your activity'),
    node('div', { class: 'workspace-grid' }, royaltiesPanel(r.lore_claimable), tokensPanel(r.lore_my_tokens),
      votesPanel(r.lore_my_vote_tasks), topicsPanel(r.lore_my_topics), agentsPanel(r.lore_my_agents)));
  renderApprovals(r.lore_my_approvals);
}

const TOOLS = [
  ['lore_inbox', 'What needs your attention'], ['lore_whoami', 'Your person and wallets'],
  ['lore_create_wallet', 'Create your Lore (Turnkey) wallet'], ['lore_wallet', 'Wallets, 0G balances and author tokens'],
  ['lore_link_token', 'Link your comfy author token'],
  ['lore_list_topics', 'Browse topics'], ['lore_get_topic', 'Topic graph and public metadata'],
  ['lore_my_vote_tasks', 'Votes waiting for you'], ['lore_get_vote_task', 'Read a submission you vote on'],
  ['lore_vote', 'Cast your vote'], ['lore_submit', 'Stake 0G and submit research'],
  ['lore_buy', 'Buy a topic (base price + authors’ tokens)'], ['lore_read_topic', 'Read a topic you own'],
  ['lore_claimable', 'Royalties you can claim'], ['lore_claim', 'Claim royalties'],
  ['lore_my_tokens', 'Author tokens you bought, and when they unlock'], ['lore_claim_tokens', 'Claim unlocked author tokens'],
  ['lore_report_leak', 'Report leaked text'], ['lore_my_approvals', 'Your approval requests'],
  ['lore_my_topics', 'Topics you bought or contributed to'], ['lore_my_agents', 'Agents signed in as you'],
  ['lore_revoke_agent', 'Log an agent out'], ['lore_continue', 'Send an action you approved'],
  ['lore_check_proof', 'Verify a TEE proof receipt'],
];
function renderAgent() {
  const url = mcpUrl();
  $('agentBody').replaceChildren(panel('MCP endpoint',
    p('Use your own MCP-capable agent. Lore hosts the gateway; your agent does the reasoning and asks for approval when needed.'),
    copyRow(url), node('h4', {}, 'Claude Code'), copyRow(`claude mcp add --transport http lore ${url}`),
    node('ul', { class: 'bullets' },
      node('li', {}, 'Your agent signs in with the same World ID (Orb-verified): one person, one vote, however many agents you run.'),
      node('li', {}, 'It uses your Lore wallet. Lore signs only Lore actions, and only after your World ID approval.'),
      node('li', {}, 'Content tools check on-chain access, vote eligibility or role before returning anything.')),
    node('details', {}, node('summary', {}, `${TOOLS.length} MCP tools`),
      node('ul', { class: 'tools' }, TOOLS.map(([name, description]) => node('li', {}, node('code', {}, name), node('span', {}, description)))))));
}
function renderActivity(data) {
  const approvals = panel('Your approvals',
    p('Before Lore spends from your Lore wallet (stake, buy, vote, claim), you approve that one action with World ID. Denied or expired approvals send nothing.', 'muted'),
    node('div', { id: 'approvalsBody', 'aria-live': 'polite' }));
  const topics = new Map((data.topics || []).map(topic => [topic.topic_id, topic.title || topic.meta?.title]));
  const reports = panel('Leak tracing', p('Every delivered copy carries a wallet-keyed invisible watermark. A match identifies the delivered copy; it does not by itself prove who leaked it or ban a person.', 'muted'));
  if (data.archived) reports.append(node('p', { class: 'info' }, 'Reports below are from a saved deployment snapshot.'));
  const list = Array.isArray(data.reports) ? data.reports : [];
  reports.append(list.length ? node('ul', { class: 'record-list' }, list.map(report => node('li', {},
    node('strong', {}, `Report #${report.report_id} · ${report.matched ? 'Traced' : 'No match'}`),
    p(topics.get(report.topic_id) || `Topic #${report.topic_id}`),
    report.matched ? p(`Matched copy: ${report.matched_wallet || '—'} · ${Number.isFinite(report.score_bps) ? `${(report.score_bps / 100).toFixed(1)}% match` : 'score unavailable'}`) : p('No known copy matched.')))) : p('No leak reports indexed.'));
  $('activityBody').replaceChildren(node('div', { class: 'workspace-grid' }, approvals, reports));
}
const CONTRACTS = {
  LoreRoles: 'Roles: verifier, curator, leak detector', PersonRegistry: 'One World ID person, many linked wallets',
  TopicGraph: 'Topics and the node commit graph', Submissions: '0G stakes, verifier reports and votes',
  Access: 'Topic passes: base price plus authors’ tokens', Royalties: 'Royalty splits and claims',
  Reports: 'Leak reports and traced matches', AuthorTokens: 'Links each author wallet to its comfy token',
  LockVault: 'Holds bought author tokens for 30 days', ComfyRouter: 'comfy router: buys author tokens with 0G',
  ComfyPoolManager: 'comfy pools that price author tokens', ComfyLauncher: 'comfy launches: who created each token',
};
const LORE_CONTRACTS = ['LoreRoles', 'PersonRegistry', 'TopicGraph', 'Submissions', 'Access', 'Royalties', 'Reports', 'AuthorTokens', 'LockVault'];
function renderContracts(data) {
  const chain = data.chain || {}, map = chain.contracts && typeof chain.contracts === 'object' ? chain.contracts : {};
  const names = LORE_CONTRACTS.concat(Object.keys(map).filter(name => !LORE_CONTRACTS.includes(name) && name !== 'USDC'));
  const box = $('contractsBody'); box.replaceChildren();
  if (data.archived) box.append(node('p', { class: 'info' }, 'These addresses belong to a saved deployment snapshot. Open this page on your gateway for current addresses.'));
  const card = panel(`${chain.name || '0G Galileo Testnet'}${chain.chain_id ? ` · chain ${chain.chain_id}` : ''}`,
    external('Open the chain explorer ↗', `${EXPLORER}/`, 'external-link'));
  card.append(names.length ? node('ul', { class: 'contract-list' }, names.map(name => node('li', { class: 'contract' },
    node('span', { class: 'name' }, name), addr(map[name])
      ? external(short(map[name]), `${EXPLORER}/address/${map[name]}`)
      : node('span', {}, 'Address unavailable'), CONTRACTS[name] ? node('span', { class: 'role' }, CONTRACTS[name]) : null))) : p('No contract addresses published.'));
  box.append(card);
}

/* ---------- one topic: buy or read ---------- */
function quoteDetails(quote) {
  if (!quote || quote.total_wei == null) return [];
  const total = big(quote.total_wei);
  const max = quote.max_wei != null ? big(quote.max_wei) : total * 10300n / 10000n;
  const authors = Array.isArray(quote.authors) ? quote.authors : [];
  const tokenCost = authors.reduce((sum, author) => sum + big(author.cost_wei), 0n);
  const days = Number.isFinite(quote.lock_days) ? quote.lock_days : 30;
  return [node('dl', { class: 'quote' },
    node('dt', {}, 'Base price'), node('dd', {}, format0G(quote.base_wei), node('span', { class: 'muted small' }, ` · ${contributorShare()} to contributors as royalties`)),
    node('dt', {}, `Authors’ comfy tokens (${plural(authors.length, 'author')})`), node('dd', {}, format0G(tokenCost)),
    node('dt', {}, 'Estimated total'), node('dd', {}, node('strong', {}, format0G(total))),
    node('dt', {}, 'Sends at most'), node('dd', {}, format0G(max), node('span', { class: 'muted small' }, ' · +3% if prices move; unspent 0G is refunded'))),
    authors.length ? node('details', {}, node('summary', {}, 'Per author'), node('ul', { class: 'record-list' }, authors.map(author => node('li', {},
      p([addrLink(author.author), ` · ${plural(author.nodes, 'node')}`]), p(`${formatTokens(author.amount)} for about ${format0G(author.cost_wei)}`, 'muted small'))))) : null,
    p(`The authors’ tokens go to Lore’s vault, locked for ${plural(days, 'day')}. Then claim them from “Author tokens you bought”.`, 'muted small')];
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
    container.append(panel('Sign in to buy or read', p('Public topic metadata is in the explorer. Sign in with World ID on your Lore gateway and link a wallet to buy or read your watermarked copy.'),
      link('Sign in with World ID →', `login.html#topic/${id}`, 'button primary')));
    return;
  }
  const [topic, balance, mine] = await Promise.allSettled([call('lore_get_topic', { topic_id: id }), call('lore_wallet'), call('lore_my_topics')]);
  if (run !== topicRun || !loggedIn()) return;
  if (topic.status === 'rejected') throw topic.reason;
  if (balance.status === 'rejected') throw balance.reason;
  const info = topic.value, wallets = balance.value.wallets || [];
  const owned = mine.status === 'fulfilled' && Array.isArray(mine.value.owned) ? mine.value.owned.includes(id) : null;
  const selector = node('select', { id: 'payingWallet' }, wallets.length
    ? wallets.map(wallet => node('option', { value: wallet.address }, `${short(wallet.address)} · ${format0G(wallet.native_wei)}`))
    : node('option', { value: '' }, 'Link a wallet first'));
  const reading = panel('Your watermarked copy', p(owned === false ? 'You don’t own this topic yet. Buy it to read every node, including future ones.' : 'Only a wallet with topic access can read the research.'));
  const read = owned === false ? null : button('Read my copy', async () => {
    const copy = await call('lore_read_topic', { topic_id: id });
    if (run !== topicRun || !loggedIn() || !reading.isConnected) return;
    reading.replaceChildren(node('h3', {}, 'Your watermarked copy'), p(`Delivered to ${copy.wallet}. Do not redistribute.`));
    for (const item of copy.nodes || []) reading.append(panel(item.meta?.title || `Node #${item.node_id}`,
      p(`Parents: ${(item.parents || []).join(', ') || 'Root node'}`), node('div', { class: 'research' }, item.text)));
  }, true);
  const buy = owned === true ? null : button('Review purchase', async () => {
    if (!selector.value) throw new Error('Link a wallet first (Get set up, step 2).');
    const wallet = selector.value;
    const answer = await call('lore_buy', { topic_id: id, wallet });
    const quote = answer.quote || (answer.total_wei != null ? answer : null);
    const details = quoteDetails(quote);
    const summary = details.length
      ? `Permanent access to “${info.meta?.title || `Topic #${id}`}”, including future nodes. Paying wallet: ${short(wallet)}.`
      : `${(answer.confirm || '').replace(/\s*Call again with confirm=true\.?$/, '')} Paying wallet: ${short(wallet)}.`;
    await perform('Buy topic access', summary, 'lore_buy', { topic_id: id, wallet, confirm: true }, details);
  }, !read);
  container.append(panel(info.meta?.title || `Topic #${id}`, p(info.meta?.description || 'Public metadata pending.'),
    node('p', { class: 'amount' }, format0G(info.price), node('span', { class: 'amount-note' }, ' + authors’ tokens')),
    p(`Base price for ${plural((info.nodes || []).length, 'node')}, plus each author’s comfy tokens at market price (locked 30 days, then yours). The price grows as nodes are accepted.`, 'muted'),
    owned === true ? p('You own this topic.', 'ok-note') : node('div', {}, node('label', { for: 'payingWallet' }, 'Paying wallet'), selector),
    node('div', { class: 'button-row' }, read, buy)), reading);
}

/* ---------- page ---------- */
function clearPersonal() {
  accountRun++; topicRun++;
  walletNotice = null;
  const dialog = $('review'); if (dialog.open) dialog.close('cancel');
  $('topicAccess').replaceChildren(); $('topicAccess').hidden = true;
  $('accountBody').replaceChildren(); $('actions').replaceChildren();
  $('approvalsBody')?.replaceChildren();
}
async function signOut() {
  clearPersonal(); // before any network call, so nothing private stays on screen if a refresh fails
  sessionStorage.removeItem('lore.web.checkpoint');
  logout();
  await render();
}
async function render() {
  $('connection').hidden = !hosted();
  if (hosted()) $('connection').textContent = loggedIn() ? 'Gateway · signed in' : 'Gateway · signed out';
  $('auth').textContent = loggedIn() ? 'Sign out' : 'Sign in';
  $('auth').href = 'login.html';
  overviewData = await overview();
  renderAgent(); renderActivity(overviewData); renderContracts(overviewData);
  await Promise.allSettled([renderAccount(), renderTopic()]).then(results => results.forEach((item, index) => {
    if (item.status === 'rejected') showError(index === 0 ? $('accountBody') : $('topicAccess'), item.reason);
  }));
  const section = location.hash.slice(1).split('/')[0];
  const target = document.getElementById(section === 'topic' ? 'topicAccess' : section);
  if (target) requestAnimationFrame(() => target.scrollIntoView({ behavior: 'instant', block: 'start' }));
}
$('auth').onclick = async event => {
  if (!loggedIn()) return;
  event.preventDefault();
  await signOut();
};
window.addEventListener('hashchange', () => { renderTopic().catch(error => showError($('topicAccess'), error)); });
let loginError;
try { await finishLogin(); } catch (error) { loginError = error; }
try { await render(); } catch (error) { showError($('accountBody'), error); }
if (loginError) showError($('accountBody'), loginError);
