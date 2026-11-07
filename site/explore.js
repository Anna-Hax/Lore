/* Lore explorer: vanilla JS, no build step.
   Data: GET {API}/api/overview (live), else data/snapshot.json.
   All API text is inserted with textContent / setAttribute, never innerHTML. */
'use strict';
(() => {
  const SVGNS = 'http://www.w3.org/2000/svg';
  const $ = (id) => document.getElementById(id);
  const REFRESH_MS = 20000;
  const DEFAULT_EXPLORER = 'https://chainscan-galileo.0g.ai';
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ================= DOM helpers (safe by construction) ================= */
  function setAttrs(el, attrs) {
    if (!attrs) return;
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === 'text') el.textContent = String(v);
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : String(v));
    }
  }
  function add(el, kids) {
    for (const k of kids.flat(Infinity)) {
      if (k == null || k === false) continue;
      el.append(k instanceof Node ? k : document.createTextNode(String(k)));
    }
    return el;
  }
  const h = (tag, attrs, ...kids) => { const el = document.createElement(tag); setAttrs(el, attrs); return add(el, kids); };
  const sv = (tag, attrs, ...kids) => { const el = document.createElementNS(SVGNS, tag); setAttrs(el, attrs); return add(el, kids); };
  const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };

  function icon(name, size = 14) {
    const paths = {
      shield: 'M12 2 4 5v6c0 5 3.4 9.4 8 11 4.6-1.6 8-6 8-11V5l-8-3Z',
      check: 'M5 12.5 10 17l9-10',
      x: 'M6 6l12 12M18 6 6 18',
      dash: 'M6 12h12',
      chev: 'm6 9 6 6 6-6',
      lock: 'M7 11V8a5 5 0 0 1 10 0v3M5 11h14v10H5z',
      copy: 'M9 9h11v11H9zM5 15V4h11',
      submit: 'M12 19V5m-6 6 6-6 6 6',
      cpu: 'M8 8h8v8H8zM4 10h2m-2 4h2m12-4h2m-2 4h2M10 4v2m4-2v2m-4 12v2m4-2v2',
      vote: 'M4 12l5 5L20 6',
      node: 'M12 3v6m0 6v6M6 12a6 6 0 1 0 12 0 6 6 0 1 0-12 0',
      cart: 'M4 5h2l2 10h10l2-7H7m3 11a1 1 0 1 0 0-2 1 1 0 0 0 0 2Zm7 0a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z',
      coins: 'M12 6c4 0 7-1 7-2s-3-2-7-2-7 1-7 2 3 2 7 2Zm-7-2v6c0 1 3 2 7 2s7-1 7-2V4M5 10v6c0 1 3 2 7 2s7-1 7-2v-6',
      search: 'M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm5-2 5 5',
    };
    const svg = sv('svg', { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
      'stroke-width': name === 'shield' ? 0 : 2, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true', class: 'p-icon' });
    const p = sv('path', { d: paths[name] || '' });
    if (name === 'shield') { p.setAttribute('fill', 'currentColor'); }
    svg.append(p);
    if (name === 'shield') svg.append(sv('path', { d: 'm8.5 12 2.5 2.5 4.5-5', stroke: 'var(--surface)', 'stroke-width': 2, fill: 'none', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }));
    return svg;
  }

  /* ================= formatting ================= */
  const isNum = (n) => typeof n === 'number' && Number.isFinite(n);
  const isAddr = (a) => typeof a === 'string' && /^0x[0-9a-fA-F]{40}$/.test(a);
  const short = (a) => (typeof a === 'string' && a.length > 13 ? `${a.slice(0, 6)}…${a.slice(-4)}` : (a == null ? '—' : String(a)));
  const fmtInt = (n) => (isNum(n) ? n.toLocaleString('en-US') : '—');
  const usdc = (n) => (isNum(n) ? (n / 1e6).toLocaleString('en-US', { maximumFractionDigits: 2 }) : '—');
  const pctBps = (b) => (isNum(b) ? `${+(b / 100).toFixed(1)}%` : '—');
  function timeAgo(ts) {
    if (!isNum(ts)) return null;
    const s = Math.round(Date.now() / 1000 - ts);
    if (Math.abs(s) < 60) return 'just now';
    const units = [[86400, 'd'], [3600, 'h'], [60, 'm']];
    for (const [sec, u] of units) if (Math.abs(s) >= sec) { const v = Math.floor(Math.abs(s) / sec); return s >= 0 ? `${v}${u} ago` : `in ${v}${u}`; }
    return 'just now';
  }
  const fmtDate = (ts) => (isNum(ts) ? new Date(ts * 1000).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' }) : '—');

  function explorerBase() {
    const e = state.data && state.data.chain && state.data.chain.explorer;
    try {
      const u = new URL(e);
      if (u.protocol === 'https:' || u.protocol === 'http:') return (u.origin + u.pathname).replace(/\/+$/, '');
    } catch (_) { /* fall through */ }
    return DEFAULT_EXPLORER;
  }
  function addrLink(a) {
    if (!isAddr(a)) return h('span', { class: 'mono muted' }, a ? short(String(a)) : '—');
    return h('a', { class: 'mono', href: `${explorerBase()}/address/${a}`, target: '_blank', rel: 'noopener noreferrer', title: a }, short(a));
  }
  function copyBtn(text, label = 'Copy', iconOnly = false) {
    const b = h('button', { type: 'button', class: iconOnly ? 'icon-copy' : 'copy-btn', 'aria-label': `${label}: ${text}`, title: 'Copy' },
      iconOnly ? icon('copy', 13) : label);
    b.addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(text); }
      catch (_) {
        const ta = h('textarea', { 'aria-hidden': 'true', style: 'position:fixed;opacity:0' }); ta.value = text;
        document.body.append(ta); ta.select(); try { document.execCommand('copy'); } catch (__) { /* ignore */ } ta.remove();
      }
      if (!iconOnly) { b.textContent = 'Copied'; b.classList.add('done'); setTimeout(() => { b.textContent = label; b.classList.remove('done'); }, 1400); }
    });
    return b;
  }
  const copyRow = (text, label) => h('div', { class: 'copy-row' }, h('code', {}, text), copyBtn(text, 'Copy', false));

  /* ================= state ================= */
  const state = {
    data: null, raw: '', source: null, api: null,
    topicId: null, nodeId: null, statusFilter: 'All', topicFilter: 'all',
    orient: null,
  };
  const P = () => Object.assign({ stake: 10e6, stake_fee: 5e5, node_value: 1e6, platform_cut_bps: 1000, quorum_bps: 5000, voting_window: 86400 },
    Object.fromEntries(Object.entries((state.data && state.data.params) || {}).filter(([, v]) => isNum(v))));

  // A topic costs node_value x its nodes (Access.priceOf); the API sends it as `price` when live.
  const topicPrice = (t) => (t && isNum(t.price)) ? t.price
    : state.source === 'snapshot' && isNum(state.data.params.topic_price) ? state.data.params.topic_price
    : P().node_value * ((t && t.node_count) || 0);

  function normalize(d) {
    d = d && typeof d === 'object' ? d : {};
    const arr = (x) => (Array.isArray(x) ? x.filter((o) => o && typeof o === 'object') : []);
    return {
      generated_at: d.generated_at, chain: d.chain && typeof d.chain === 'object' ? d.chain : {},
      params: d.params || {}, mcp_url: typeof d.mcp_url === 'string' ? d.mcp_url : null,
      stats: d.stats && typeof d.stats === 'object' ? d.stats : {},
      topics: arr(d.topics), nodes: arr(d.nodes).map((n) => ({ ...n, parents: Array.isArray(n.parents) ? n.parents : [] })),
      submissions: arr(d.submissions).map((s) => ({ ...s, parents: Array.isArray(s.parents) ? s.parents : [] })),
      reports: arr(d.reports), checkpoints: arr(d.checkpoints),
    };
  }
  const topicById = (id) => state.data.topics.find((t) => t.topic_id === id);
  const nodeById = (id) => state.data.nodes.find((n) => n.node_id === id);
  const topicTitle = (id) => { const t = topicById(id); return t && t.title ? t.title : `Topic ${id}`; };

  /* ================= data loading ================= */
  function resolveApi() {
    const q = new URLSearchParams(location.search).get('api');
    if (q) {
      try { const u = new URL(q, location.href); if (u.protocol === 'http:' || u.protocol === 'https:') return (u.origin + u.pathname).replace(/\/+$/, ''); }
      catch (_) { /* ignore bad param */ }
      return null;
    }
    if (/^https?:$/.test(location.protocol) && location.pathname.startsWith('/app/')) return location.origin;
    return null;
  }
  async function fetchJson(url, ms) {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), ms);
    try {
      const r = await fetch(url, { signal: ctl.signal, headers: { Accept: 'application/json' }, cache: 'no-store' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const text = await r.text();
      return { text, json: JSON.parse(text) };
    } finally { clearTimeout(t); }
  }
  async function load(first) {
    let res = null, source = null;
    if (state.api) {
      try { res = await fetchJson(`${state.api}/api/overview`, 30000); source = 'live'; }
      catch (e) {
        if (!first && state.source === 'live') {
          setSource('err', 'Connection lost · showing last update', 'Retrying every 20 seconds.');
          return;
        }
      }
    }
    if (!res && (first || state.source !== 'snapshot')) {
      try { res = await fetchJson('data/snapshot.json', 8000); source = 'snapshot'; }
      catch (e) { if (first) return showError(); return; }
    }
    if (!res) return;
    if (res.text === state.raw && source === state.source) { renderHeader(); return; }
    state.raw = res.text; state.source = source;
    state.data = normalize(res.json);
    renderAll();
  }
  function showError() {
    setSource('err', 'No data');
    $('main').append(h('p', { class: 'notice', role: 'alert' },
      'Could not load explorer data. Serve this folder over HTTP (the gateway serves it at /app/), or pass ?api=<gateway URL>.'));
  }
  function setSource(kind, text, title) {
    const pill = $('srcPill');
    pill.className = `pill ${kind}`;
    $('srcText').textContent = text;
    if (title) pill.title = title; else pill.removeAttribute('title');
  }

  /* ================= render: header + recent activity ================= */
  function renderHeader() {
    $('archiveNotice').hidden = state.source !== 'snapshot';
    const c = state.data.chain;
    const name = typeof c.name === 'string' && c.name ? c.name.replace(/\s*Testnet$/i, '') : '0G Galileo';
    $('netText').textContent = `${name}${isNum(c.chain_id) ? ` · ${c.chain_id}` : ''}`;
    if (state.source === 'live') setSource('live', 'Live · gateway', state.api);
    else setSource('snap', `Snapshot · ${isNum(state.data.generated_at) ? new Date(state.data.generated_at * 1000).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : 'sample'}`,
      `Saved snapshot from ${fmtDate(state.data.generated_at)}. The page shows live data when the gateway serves it.`);
  }

  function renderPulse() {
    const rail = clear($('signalRail'));
    const latest = state.data.submissions.reduce((best, s) =>
      isNum(s.sub_id) && (!best || s.sub_id > best.sub_id) ? s : best, null);
    rail.append(h('span', { class: 'signal-glyph', 'aria-hidden': 'true' }));
    rail.append(h('span', { class: 'signal-label' }, state.source === 'live' ? 'NETWORK ACTIVITY' : 'ARCHIVED ACTIVITY'));
    if (latest) {
      rail.append(h('span', { class: 'signal-copy' },
        `Submission #${latest.sub_id} · ${latest.status || 'Pending'} · ${topicTitle(latest.topic_id)}`));
      rail.append(h('button', { type: 'button', class: 'signal-link', onclick: () => showSubmission(latest.sub_id) }, 'Inspect →'));
    } else rail.append(h('span', { class: 'signal-copy' }, 'No submissions indexed yet.'));
  }

  function renderSteps() {
    const p = P();
    const steps = [
      ['submit', 'Submit', `An agent stakes ${usdc(p.stake)} USDC and submits research, encrypted (AES-256-GCM) on 0G Storage.`, '0G Chain · Storage'],
      ['cpu', 'Verify', 'The AI verifier runs privately on 0G Compute in a TEE: length, relevance, fit and originality. Its report goes on-chain.', '0G Compute'],
      ['vote', 'Vote', `Past contributors vote, one vote per real person (World ID). Quorum ${pctBps(p.quorum_bps)}, ${Math.round(p.voting_window / 3600)}h window. Voters are never paid. New topics: the verifier decides.`, 'World ID'],
      ['node', 'Node', `Accepted: stake back minus ${usdc(p.stake_fee)} USDC and the node joins the graph. Rejected: the stake goes to the treasury.`, 'TopicGraph'],
      ['cart', 'Buy', `A topic costs ${usdc(p.node_value)} USDC per node (about the model tokens you save by not redoing it) and buys a soulbound ERC-1155 pass: the whole topic, permanently, including future nodes.`, 'Access'],
      ['coins', 'Royalties', `${pctBps(10000 - p.platform_cut_bps)} of every sale is split equally across the topic's nodes, so each node earns ${usdc(p.node_value * (10000 - p.platform_cut_bps) / 10000)} USDC per buyer, claimable on-chain.`, 'Royalties'],
      ['search', 'Trace leaks', 'Every copy is invisibly watermarked to the reader\'s wallet. Matches are recorded on-chain; person-wide bans are a separate action.', 'Reports'],
    ];
    add(clear($('steps')), steps.map(([ic, t, body, where]) =>
      h('li', { class: 'step' }, h('h3', {}, icon(ic, 16), t), h('p', {}, body), h('span', { class: 'where' }, where))));
  }

  /* ================= proof badge ================= */
  function proofBadge(proof, who, what) {
    const st = proof && typeof proof === 'object' ? proof.status : null;
    const cls = !proof ? 'none' : st === 'pass' ? 'ok' : st === 'fail' ? 'bad' : 'warn';
    const label = !proof ? 'No proof recorded' : st === 'pass' ? 'TEE proof verified' : st === 'fail' ? 'TEE proof failed' : 'TEE proof incomplete';
    const det = h('details', { class: `proof proof-${cls}` });
    det.append(h('summary', {},
      icon('shield', 16), h('span', { class: 'p-label' }, label), h('span', { class: 'p-who' }, `· ${who}`),
      proof && proof.model ? h('span', { class: 'p-model' }, proof.model) : null,
      sv('svg', { class: 'chev', width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': 2, 'aria-hidden': 'true' }, sv('path', { d: 'm6 9 6 6 6-6' }))));
    const body = h('div', { class: 'p-body' });
    const explain = {
      ok: `The ${who.toLowerCase()} produced ${what} with a model on 0G Compute. The response was signed inside a TEE, and that signature recovers to the signer the provider registered on-chain for this model.`,
      warn: `A receipt for ${what} exists, but part of the check could not be completed (for example the signature or the provider record was missing), so it is not claimed as verified.`,
      bad: `The signature on the receipt for ${what} does not match the provider's on-chain TEE signer. Treat this output as unverified.`,
      none: `No model receipt is recorded for ${what}.`,
    }[cls];
    body.append(h('p', {}, explain));
    body.append(h('p', { class: 'p-limit' }, h('b', {}, 'What it does not prove. '),
      'The 0G Router encrypts requests end to end, so the TEE signs hashes of the encrypted exchange. The proof shows that a TEE-attested provider registered for this model handled the request privately. It does not cryptographically bind this exact plaintext output.'));
    if (proof) {
      const rootOk = typeof proof.root === 'string' && /^0x[0-9a-fA-F]+$/.test(proof.root);
      body.append(h('dl', { class: 'kv' },
        h('dt', {}, 'Model'), h('dd', { class: 'mono' }, proof.model || '—'),
        h('dt', {}, 'Provider'), h('dd', {}, addrLink(proof.provider)),
        h('dt', {}, 'TEE signer'), h('dd', {}, addrLink(proof.signer)),
        h('dt', {}, 'Binding'), h('dd', {}, h('span', { class: 'mono' }, proof.binding || '—'),
          proof.binding === 'e2ee-ciphertext' ? h('span', { class: 'muted' }, ' (signature covers the encrypted exchange)') : null),
        h('dt', {}, 'Private'), h('dd', {}, proof.private === true ? 'Yes, 0G Compute private mode' : proof.private === false ? 'No' : '—'),
        h('dt', {}, 'Receipt'), h('dd', {}, rootOk ? h('span', {}, h('span', { class: 'mono', title: proof.root }, short(proof.root)), ' ', copyBtn(proof.root, 'Copy receipt root', true), h('span', { class: 'muted' }, ' 0G Storage root')) : '—'),
      ));
      body.append(h('p', { class: 'p-hint' }, rootOk
        ? h('a', { href: 'workspace.html#agent' }, 'Check this receipt with your agent →')
        : 'Ask your agent to run lore_check_proof with the receipt root.'));
    }
    det.append(body);
    return det;
  }

  /* ================= topics ================= */
  function renderTopicList() {
    const ul = clear($('topicList'));
    const topics = state.data.topics;
    if (!topics.length) { ul.append(h('li', { class: 'empty' }, 'No topics yet.')); return; }
    for (const t of topics) {
      const count = isNum(t.node_count) ? t.node_count : state.data.nodes.filter((n) => n.topic_id === t.topic_id).length;
      ul.append(h('li', {}, h('button', {
        type: 'button', class: 'topic-btn', 'aria-pressed': String(t.topic_id === state.topicId),
        onclick: () => selectTopic(t.topic_id, null, true),
      },
        h('span', { class: 't-id' }, `Topic #${t.topic_id}`),
        h('span', { class: 't-title' }, t.title || `Topic ${t.topic_id}`),
        t.description ? h('span', { class: 't-desc' }, t.description) : null,
        h('span', { class: 't-meta' },
          h('span', {}, h('b', {}, fmtInt(count)), ' nodes'),
          h('span', {}, h('b', {}, fmtInt(t.buyers)), ' buyers'),
          h('span', {}, h('b', {}, fmtInt(t.contributors)), ' contributors')))));
    }
  }

  function selectTopic(id, nodeId, focusGraph) {
    state.topicId = id;
    const nodes = state.data.nodes.filter((n) => n.topic_id === id);
    state.nodeId = nodeId != null ? nodeId : (nodes.length ? nodes.reduce((a, b) => (b.node_id > a.node_id ? b : a)).node_id : null);
    renderTopicList(); renderTopic();
    if (focusGraph && window.matchMedia('(max-width: 919px)').matches) $('graphHead').scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
  }

  function renderTopic() {
    const head = clear($('graphHead'));
    const t = topicById(state.topicId);
    if (!t) { head.append(h('p', { class: 'empty' }, 'Select a topic.')); clear($('graph')); clear($('nodeDetail')); return; }
    const p = P();
    head.append(
      h('p', { class: 'eyebrow' }, `Topic #${t.topic_id}`),
      h('h3', {}, t.title || `Topic ${t.topic_id}`),
      t.description ? h('p', { class: 'desc' }, t.description) : null,
      h('div', { class: 'row' },
        h('span', { class: 'price' }, `${usdc(topicPrice(t))} USDC${state.source === 'snapshot' ? ' · historical price' : ' · topic pass'}`),
        h('span', {}, h('b', {}, fmtInt(t.buyers)), ' buyers'),
        h('span', {}, h('b', {}, fmtInt(t.contributors)), ' contributors')),
      h('a', { href: `workspace.html#topic/${t.topic_id}` }, state.source === 'live' ? 'Read or buy this topic →' : 'Open this topic on your gateway →'),
      proofBadge(t.proof, 'Curator', 'this topic summary'),
    );
    renderGraph();
    renderNodeDetail();
  }

  /* ---------- graph layout: layers by depth, barycentre ordering ---------- */
  function layout(nodes) {
    const byId = new Map(nodes.map((n) => [n.node_id, n]));
    const depth = new Map(), visiting = new Set();
    const d = (id) => {
      if (depth.has(id)) return depth.get(id);
      if (visiting.has(id)) return 0; // cycle guard (should never happen in a DAG)
      visiting.add(id);
      const ps = byId.get(id).parents.filter((p) => byId.has(p));
      const v = ps.length ? 1 + Math.max(...ps.map(d)) : 0;
      visiting.delete(id); depth.set(id, v);
      return v;
    };
    nodes.forEach((n) => d(n.node_id));
    const layers = [];
    nodes.forEach((n) => { const k = depth.get(n.node_id); (layers[k] = layers[k] || []).push(n); });
    const idx = new Map();
    const bary = (n) => { const ps = n.parents.filter((p) => idx.has(p)); return ps.length ? ps.reduce((s, p) => s + idx.get(p), 0) / ps.length : -1; };
    layers.forEach((layer, li) => {
      if (!layer) return;
      layer.sort((a, b) => (li ? bary(a) - bary(b) : 0) || a.node_id - b.node_id);
      layer.forEach((n, i) => idx.set(n.node_id, i));
    });
    return { layers: layers.filter(Boolean), depth, byId };
  }

  function wrapTitle(s, max) { // two lines, word-wrapped, ellipsis on overflow
    const words = String(s).split(/\s+/).filter(Boolean);
    let a = '';
    while (words.length && (a ? a.length + 1 : 0) + words[0].length <= max) a += (a ? ' ' : '') + words.shift();
    if (!a) return [truncate(words.join(' '), max)];
    return words.length ? [a, truncate(words.join(' '), max)] : [a];
  }
  function truncate(s, max) { s = String(s || ''); return s.length > max ? `${s.slice(0, max - 1).trimEnd()}…` : s; }

  function renderGraph() {
    const svg = clear($('graph'));
    const nodes = state.data.nodes.filter((n) => n.topic_id === state.topicId);
    if (!nodes.length) { svg.setAttribute('viewBox', '0 0 300 60'); svg.append(sv('text', { x: 150, y: 34, 'text-anchor': 'middle', class: 'nid' }, 'No accepted nodes yet')); return; }
    const { layers, byId } = layout(nodes);
    const avail = Math.max(200, ($('graphWrap').clientWidth || 800) - 18);
    const maxLayer = Math.max(...layers.map((l) => l.length));
    // Roots left (horizontal) by default; roots top (vertical) when that keeps the text noticeably larger.
    const hW = 28 + layers.length * 184 + (layers.length - 1) * 64;
    const vW = 28 + maxLayer * 150 + (maxLayer - 1) * 16;
    const vertical = layers.length > 1 && Math.min(1, avail / vW) > Math.min(1, avail / hW) + 0.05;
    state.orient = vertical ? 'v' : 'h';
    const NW = vertical ? 150 : 184, NH = 68, GX = vertical ? 16 : 64, GY = vertical ? 46 : 18, PAD = 14;
    const pos = new Map();
    layers.forEach((layer, li) => layer.forEach((n, i) => {
      const off = (maxLayer - layer.length) / 2;
      const x = vertical ? PAD + (i + off) * (NW + GX) : PAD + li * (NW + GX);
      const y = vertical ? PAD + li * (NH + GY) : PAD + (i + off) * (NH + GY);
      pos.set(n.node_id, { x, y });
    }));
    const W = vertical ? PAD * 2 + maxLayer * NW + (maxLayer - 1) * GX : PAD * 2 + layers.length * NW + (layers.length - 1) * GX;
    const H = vertical ? PAD * 2 + layers.length * NH + (layers.length - 1) * GY : PAD * 2 + maxLayer * NH + (maxLayer - 1) * GY;
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.style.maxWidth = `${W}px`;
    svg.style.minWidth = vertical ? `${Math.min(W, 300)}px` : `${Math.min(W, 520)}px`;
    svg.setAttribute('aria-label', `Commit graph for ${topicTitle(state.topicId)}: ${nodes.length} nodes in ${layers.length} layers`);

    const sel = state.nodeId;
    const selNode = byId.get(sel);
    const rel = new Set(selNode ? selNode.parents : []);
    nodes.forEach((n) => { if (n.parents.includes(sel)) rel.add(n.node_id); });

    const defs = sv('defs', {},
      sv('marker', { id: 'arr', viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse' }, sv('path', { d: 'M0 0 10 5 0 10z', class: 'g-arrow' })),
      sv('marker', { id: 'arrhl', viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse' }, sv('path', { d: 'M0 0 10 5 0 10z', class: 'g-arrow-hl' })));
    svg.append(defs);

    const edges = sv('g', { 'aria-hidden': 'true' });
    const hlEdges = sv('g', { 'aria-hidden': 'true' });
    // Spread edge endpoints along each node's side so edges sharing a node stay distinguishable.
    const cross = (id) => (vertical ? pos.get(id).x : pos.get(id).y);
    const outs = new Map(), ins = new Map();
    for (const n of nodes) {
      const ps = n.parents.filter((p) => pos.has(p)).sort((a, b) => cross(a) - cross(b));
      outs.set(n.node_id, ps);
      ps.forEach((p) => { if (!ins.has(p)) ins.set(p, []); ins.get(p).push(n.node_id); });
    }
    ins.forEach((list) => list.sort((a, b) => cross(a) - cross(b)));
    const spread = (vertical ? NW : NH) * 0.44;
    const port = (i, k) => (k <= 1 ? 0 : (i / (k - 1) - 0.5) * spread);
    for (const n of nodes) {
      const c = pos.get(n.node_id);
      const ps = outs.get(n.node_id);
      for (const pid of ps) {
        const p = pos.get(pid);
        const o1 = port(ps.indexOf(pid), ps.length);
        const kids = ins.get(pid);
        const o2 = port(kids.indexOf(n.node_id), kids.length);
        let dPath;
        if (vertical) { // child below, parent above: child top -> parent bottom
          const x1 = c.x + NW / 2 + o1, y1 = c.y, x2 = p.x + NW / 2 + o2, y2 = p.y + NH + 2, my = (y1 + y2) / 2;
          dPath = `M${x1} ${y1} C${x1} ${my} ${x2} ${my} ${x2} ${y2}`;
        } else { // child right, parent left: child left edge -> parent right edge
          const x1 = c.x, y1 = c.y + NH / 2 + o1, x2 = p.x + NW + 2, y2 = p.y + NH / 2 + o2, mx = (x1 + x2) / 2;
          dPath = `M${x1} ${y1} C${mx} ${y1} ${mx} ${y2} ${x2} ${y2}`;
        }
        const hl = n.node_id === sel || pid === sel;
        (hl ? hlEdges : edges).append(sv('path', { d: dPath, class: `g-edge${hl ? ' hl' : ''}`, 'marker-end': `url(#${hl ? 'arrhl' : 'arr'})` }));
      }
    }
    svg.append(edges, hlEdges);

    const maxChars = vertical ? 20 : 25;
    for (const layer of layers) for (const n of layer) {
      const { x, y } = pos.get(n.node_id);
      const isRoot = !n.parents.length;
      const pst = n.proof && n.proof.status;
      const pcls = !n.proof ? 'none' : pst === 'pass' ? 'ok' : pst === 'fail' ? 'bad' : 'warn';
      const cls = ['g-node', isRoot ? 'root' : '', n.node_id === sel ? 'sel' : '', rel.has(n.node_id) ? 'is-rel' : ''].filter(Boolean).join(' ');
      const g = sv('g', {
        class: cls, tabindex: 0, role: 'button', 'aria-pressed': String(n.node_id === sel),
        'aria-label': `Node ${n.node_id}: ${n.title || 'untitled'}${isRoot ? ', root' : `, builds on ${n.parents.map((p) => `#${p}`).join(', ')}`}`,
        transform: `translate(${x} ${y})`,
      },
        sv('title', {}, n.title || `Node ${n.node_id}`),
        sv('rect', { class: 'box', width: NW, height: NH, rx: 10 }),
        isRoot ? sv('rect', { class: 'root-bar', x: 0, y: 10, width: 3, height: NH - 20, rx: 1.5 }) : null,
        sv('text', { class: 'nid', x: 12, y: 20 }, `#${n.node_id}${isRoot ? ' · root' : ''}`),
        wrapTitle(n.title || 'Untitled', maxChars).map((line, i) => sv('text', { class: 'ntitle', x: 12, y: 40 + i * 16 }, line)),
        sv('circle', { class: `pdot ${pcls}`, cx: NW - 12, cy: 15, r: 5 }));
      const pick = () => { state.nodeId = n.node_id; renderGraph(); renderNodeDetail(); focusNode(n.node_id); };
      g.addEventListener('click', pick);
      g.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); }
      });
      g.dataset.id = String(n.node_id);
      svg.append(g);
    }
  }
  function focusNode(id) {
    const g = $('graph').querySelector(`g.g-node[data-id="${Number(id)}"]`);
    if (g && typeof g.focus === 'function') g.focus({ preventScroll: true });
  }

  function renderNodeDetail() {
    const box = clear($('nodeDetail'));
    const n = nodeById(state.nodeId);
    if (!n || n.topic_id !== state.topicId) { box.append(h('p', { class: 'empty' }, 'Select a node in the graph to see its details.')); return; }
    const children = state.data.nodes.filter((m) => m.parents.includes(n.node_id));
    const sub = state.data.submissions.find((s) => s.node_id === n.node_id);
    const jump = (id) => h('button', { type: 'button', class: 'link-btn', onclick: () => { state.nodeId = id; renderGraph(); renderNodeDetail(); focusNode(id); } }, `#${id}`);
    const p = P();
    box.append(
      h('p', { class: 'eyebrow' }, `Node #${n.node_id}${n.parents.length ? '' : ' · root'}`),
      h('h4', {}, n.title || 'Untitled node'),
      n.description ? h('p', { class: 'desc' }, n.description) : null,
      h('dl', { class: 'kv' },
        h('dt', {}, 'Contributor'), h('dd', {}, addrLink(n.contributor)),
        h('dt', {}, 'Builds on'), h('dd', {}, n.parents.length ? h('span', { class: 'chips' }, n.parents.map(jump)) : h('span', { class: 'muted' }, 'Nothing: root node')),
        h('dt', {}, 'Built on by'), h('dd', {}, children.length ? h('span', { class: 'chips' }, children.map((c) => jump(c.node_id))) : h('span', { class: 'muted' }, 'No later nodes yet')),
        sub ? h('dt', {}, 'Accepted via') : null,
        sub ? h('dd', {}, h('button', { type: 'button', class: 'link-btn', onclick: () => showSubmission(sub.sub_id) }, `Submission #${sub.sub_id}`)) : null),
      h('div', { class: 'locked' }, icon('lock', 16), h('span', {},
        h('b', {}, 'Content is encrypted on 0G Storage. '),
        `Buyers of this topic (${usdc(topicPrice(topicById(n.topic_id)))} USDC, lore_buy) read it through lore_read_topic; each copy is watermarked to the reader's wallet.`)),
      proofBadge(n.proof, 'Curator', 'this title and description'),
    );
  }

  /* ================= submissions ================= */
  const STATUSES = ['All', 'Pending', 'Reported', 'Accepted', 'Rejected'];
  const STATUS_HINT = { Pending: 'awaiting verifier', Reported: 'voting open', Accepted: 'node added', Rejected: 'stake to treasury' };
  const CHECKS = [['length', 'Length'], ['relevant', 'Relevant'], ['fits_topic', 'Fits topic'], ['original_vs_graph', 'Original vs graph'], ['original_vs_pending', 'Original vs pending'], ['original_vs_public', 'Original vs public web']];

  function renderFilters() {
    const subs = state.data.submissions;
    const box = clear($('statusFilters'));
    for (const s of STATUSES) {
      const n = s === 'All' ? subs.length : subs.filter((x) => x.status === s).length;
      box.append(h('button', {
        type: 'button', class: 'filter', 'aria-pressed': String(state.statusFilter === s),
        title: STATUS_HINT[s] || 'All submissions',
        onclick: () => { state.statusFilter = s; renderFilters(); renderSubs(); },
      }, s, h('span', { class: 'n' }, n)));
    }
    const sel = clear($('topicFilter'));
    sel.append(h('option', { value: 'all' }, 'All topics'));
    for (const t of state.data.topics) sel.append(h('option', { value: String(t.topic_id) }, truncate(t.title || `Topic ${t.topic_id}`, 40)));
    if (![...sel.options].some((o) => o.value === state.topicFilter)) state.topicFilter = 'all';
    sel.value = state.topicFilter;
    sel.onchange = () => { state.topicFilter = sel.value; renderSubs(); };
  }

  function voteBlock(s) {
    const p = P();
    const yes = isNum(s.yes) ? s.yes : 0, no = isNum(s.no) ? s.no : 0, el = isNum(s.eligible) ? s.eligible : 0;
    const wrap = h('div', {});
    wrap.append(h('div', { class: 'lbl' }, 'Contributor vote'));
    if (s.status === 'Pending' && !s.report) {
      wrap.append(h('p', { class: 'vote-note' }, el ? `Opens after the verifier report. ${el} eligible ${el === 1 ? 'person' : 'people'}.` : 'Opens after the verifier report.'));
      return wrap;
    }
    if (!el) {
      wrap.append(h('p', { class: 'vote-note' }, 'No past contributors yet (new topic), so the verifier decides.'));
      return wrap;
    }
    const q = p.quorum_bps / 10000;
    const need = Math.ceil(el * q);
    const yw = Math.min(100, (yes / el) * 100), nw = Math.min(100 - yw, (no / el) * 100);
    wrap.append(h('div', { class: 'vote-wrap' }, h('div', {
      class: 'votebar', role: 'img',
      'aria-label': `${yes} yes, ${no} no out of ${el} eligible. Quorum needs ${need} votes.`,
    }, h('span', { class: 'track' }, h('span', { class: 'y', style: `width:${yw}%` }), h('span', { class: 'n', style: `width:${nw}%` })), h('span', { class: 'q', style: `left:calc(${q * 100}% - 1px)` }))));
    wrap.append(h('div', { class: 'vote-nums' },
      h('span', { class: 'y' }, h('b', {}, yes), ' yes'), h('span', { class: 'n' }, h('b', {}, no), ' no'),
      h('span', {}, h('b', {}, el), ' eligible'), h('span', {}, 'quorum ', h('b', {}, need))));
    if (s.status === 'Reported') {
      const left = isNum(s.reported_at) ? s.reported_at + p.voting_window - Date.now() / 1000 : null;
      wrap.append(h('p', { class: 'vote-note' }, left != null && left <= 0 ? 'Voting deadline passed. Awaiting finalization.' : left != null ? `Voting open, about ${Math.max(1, Math.round(left / 3600))}h left. Ends early once one side can't lose.` : 'Voting open. Ends early once one side can\'t lose.'));
    }
    return wrap;
  }

  function subCard(s) {
    const p = P();
    const r = s.report && typeof s.report === 'object' ? s.report : null;
    const pass = r && typeof r.pass === 'boolean' ? r.pass : (typeof s.verifier_pass === 'boolean' ? s.verifier_pass : null);
    const checks = r && r.checks && typeof r.checks === 'object' ? r.checks : {};
    const sim = r && isNum(r.max_similarity) ? r.max_similarity : null;
    const statusName = STATUSES.includes(s.status) ? s.status : 'Pending';
    const ago = timeAgo(s.submitted_at);

    const left = h('div', {},
      h('div', { class: 'lbl' }, 'Verifier', h('span', { class: `verdict ${pass === true ? 'ok' : pass === false ? 'bad' : 'none'}` },
        pass === true ? 'Pass' : pass === false ? 'Fail' : 'Report pending')),
      r ? h('ul', { class: 'checks', 'aria-label': 'Verifier checks' }, CHECKS.map(([k, label]) => {
        const v = checks[k];
        const c = v === true ? 'ok' : v === false ? 'bad' : 'none';
        return h('li', { class: `chk ${c}` }, icon(v === true ? 'check' : v === false ? 'x' : 'dash', 12), label, h('span', { class: 'sr-only' }, v === true ? ': passed' : v === false ? ': failed' : ': not reported'));
      })) : h('p', { class: 'vote-note' }, 'The verifier is checking this submission privately on 0G Compute.'),
      sim != null ? h('div', { class: 'sim' }, 'Max similarity',
        h('span', { class: `meter${sim >= 0.8 ? ' hi' : ''}`, role: 'img', 'aria-label': `Max similarity ${Math.round(sim * 100)}%` }, h('i', { style: `width:${Math.min(100, Math.max(0, sim * 100))}%` })),
        h('b', {}, `${Math.round(sim * 100)}%`)) : null);

    let outcome = null;
    if (statusName === 'Accepted') outcome = `Stake returned minus ${usdc(p.stake_fee)} USDC fee`;
    else if (statusName === 'Rejected') outcome = `${usdc(p.stake)} USDC stake sent to treasury`;
    else outcome = `${usdc(p.stake)} USDC staked`;

    return h('li', { class: 'card sub', id: `sub-${Number(s.sub_id)}` },
      h('div', { class: 'sub-head' },
        h('span', { class: 'sub-id' }, `#${s.sub_id}`),
        h('span', { class: `badge st-${statusName}` }, statusName, h('span', { class: 'muted', style: 'font-weight:500;color:inherit;opacity:.8' }, ` · ${STATUS_HINT[statusName]}`)),
        h('span', { class: 'sub-topic' }, topicTitle(s.topic_id)),
        ago ? h('span', { class: 'sub-time', title: fmtDate(s.submitted_at) }, `submitted ${ago}`) : null),
      h('div', { class: 'sub-grid' }, left, voteBlock(s)),
      h('div', { class: 'sub-foot' },
        h('span', {}, 'by ', addrLink(s.submitter)),
        s.parents.length ? h('span', {}, 'builds on ', s.parents.map((pid, i) => [i ? ' ' : '', h('button', { type: 'button', class: 'link-btn', onclick: () => showNode(s.topic_id, pid) }, `#${pid}`)])) : h('span', {}, 'new root'),
        isNum(s.node_id) ? h('span', {}, 'became ', h('button', { type: 'button', class: 'link-btn', onclick: () => showNode(s.topic_id, s.node_id) }, `node #${s.node_id}`)) : null,
        h('span', { class: 'outcome' }, outcome)),
      r ? proofBadge(r.proof, 'Verifier', 'this report') : null);
  }

  function renderSubs() {
    const ul = clear($('subList'));
    let list = state.data.submissions.slice().sort((a, b) => (b.sub_id || 0) - (a.sub_id || 0));
    if (state.statusFilter !== 'All') list = list.filter((s) => s.status === state.statusFilter);
    if (state.topicFilter !== 'all') list = list.filter((s) => String(s.topic_id) === state.topicFilter);
    if (!list.length) { ul.append(h('li', { class: 'empty' }, 'No submissions match this filter.')); return; }
    list.forEach((s) => ul.append(subCard(s)));
  }

  function showNode(topicId, nodeId) {
    selectTopic(topicId, nodeId, false);
    $('topics').scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
    setTimeout(() => focusNode(nodeId), reduceMotion ? 0 : 400);
  }
  function showSubmission(id) {
    if (!state.data.submissions.some((s) => s.sub_id === id)) return;
    state.statusFilter = 'All'; state.topicFilter = 'all';
    renderFilters(); renderSubs();
    const el = $(`sub-${Number(id)}`);
    if (!el) return;
    el.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'center' });
    el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash');
  }

  /* ================= side panels ================= */
  const TOOLS = [
    ['lore_inbox', 'What needs your attention'],
    ['lore_list_topics', 'Browse topics'],
    ['lore_get_topic', 'Topic graph and public metadata'],
    ['lore_submit', 'Stake and submit research'],
    ['lore_my_vote_tasks', 'Votes waiting for you'],
    ['lore_get_vote_task', 'Read a submission you can vote on'],
    ['lore_vote', 'Cast your vote'],
    ['lore_buy', 'Buy a topic pass'],
    ['lore_read_topic', 'Read a topic you own'],
    ['lore_claimable', 'Royalties you can claim'],
    ['lore_claim', 'Claim royalties'],
    ['lore_report_leak', 'Report leaked text for tracing'],
    ['lore_check_proof', 'Verify a TEE proof receipt'],
    ['lore_create_wallet', 'Create your Lore wallet (Turnkey; you own it, Lore signs only Lore calls)'],
    ['lore_wallet', 'Your wallet address and balances'],
    ['lore_link_wallet', 'Link a self-held wallet with a signed message'],
    ['lore_whoami', 'Your person and linked wallets'],
    ['lore_continue', 'Send an action your human approved with World ID'],
  ];
  function renderConnect() {
    let url = state.source === 'live' ? state.data.mcp_url : null;
    if (!url && state.api) url = `${state.api}/mcp`;
    if (!url) url = '<gateway>/mcp';
    add(clear($('mcpBody')), [
      h('p', { class: 'note' }, 'Use your own MCP-capable agent (Claude Code, Cursor and others). Lore hosts the MCP server and signs Lore’s calls from your Turnkey wallet; your agent does the reasoning.'),
      h('h3', {}, 'MCP endpoint'), copyRow(url),
      h('h3', {}, 'Claude Code'), copyRow(`claude mcp add --transport http lore ${url}`),
      h('ul', { class: 'bullets' },
        h('li', {}, 'Sign in with World ID: one person, one vote, however many agents you run.'),
        h('li', {}, 'Self-held wallets receive unsigned transactions to sign locally. Turnkey wallets let Lore sign authorized Lore calls; gateways configured with Agent Pass request fresh World ID approval.'),
        h('li', {}, 'Content tools check on-chain access, vote eligibility or role before returning anything.')),
      h('h3', {}, `${TOOLS.length} tools`),
      h('ul', { class: 'tools' }, TOOLS.map(([n, d]) => h('li', {}, h('code', {}, n), h('span', {}, d)))),
    ]);
  }

  function renderLeaks() {
    const d = state.data;
    const box = clear($('leakBody'));
    const reportsAddr = d.chain.contracts && d.chain.contracts.Reports;
    box.append(h('p', { class: 'note' },
      'Each copy delivered to a buyer or voter carries an invisible watermark (zero-width characters keyed to their wallet). When leaked text turns up, the leak detector matches the watermark and records it on-chain with ',
      h('code', { class: 'mono' }, 'Reports.recordMatch'), isAddr(reportsAddr) ? [' (', addrLink(reportsAddr), ')'] : null,
      '. A match identifies a delivered copy. It does not by itself prove who leaked it or automatically ban a person. Person-wide bans are recorded separately through ',
      h('code', { class: 'mono' }, 'PersonRegistry.ban'), '.'));
    if (!d.reports.length) { box.append(h('p', { class: 'empty' }, 'No leak reports yet.')); return; }
    const traced = d.reports.filter((r) => r.matched).length;
    box.append(h('p', { class: 'chain-line', style: 'margin-top:10px' }, `${traced} of ${d.reports.length} reports traced to a wallet.`));
    box.append(h('ul', { class: 'leak-list' }, d.reports.map((r) => h('li', { class: 'leak' },
      h('div', { class: 'row' },
        h('b', { class: 'mono' }, `Report #${r.report_id}`),
        h('span', { class: `badge ${r.matched ? 'traced' : 'clean'}` }, r.matched ? 'Traced' : 'No match'),
        h('span', { class: 'score', title: 'Watermark match score' }, isNum(r.score_bps) ? `${pctBps(r.score_bps)} match` : '')),
      h('div', { class: 't' }, topicTitle(r.topic_id)),
      r.matched ? h('div', { class: 't' }, 'Matched copy: ', addrLink(r.matched_wallet)) : h('div', { class: 't' }, 'No watermark matched a known reader.')))));
  }

  const CHECK_STATUS = { approved: 'Approved', used: 'Approval used · check transaction receipt', denied: 'Denied', expired: 'Expired', pending: 'Waiting' };
  function renderCheckpoints() {
    const box = clear($('checkBody'));
    const list = Array.isArray(state.data.checkpoints) ? state.data.checkpoints : [];
    box.append(h('p', { class: 'note' },
      'Before Lore signs a stake, purchase, vote or claim from a person\'s wallet, the agent must get that person\'s ',
      h('b', {}, 'fresh World ID approval'), ' (World ID Agent Pass, max_age=0) for that one action. Denied, cancelled or expired approvals send nothing.'));
    if (!list.length) { box.append(h('p', { class: 'empty' }, 'No agent actions have asked for approval yet.')); return; }
    box.append(h('ul', { class: 'leak-list' }, list.map((c) => h('li', { class: 'leak' },
      h('div', { class: 'row' },
        h('b', {}, String(c.action || 'agent action')),
        h('span', { class: `badge ${c.status === 'used' || c.status === 'approved' ? 'ok' : (c.status === 'pending' ? 'clean' : 'traced')}` },
          CHECK_STATUS[c.status] || String(c.status))),
      h('div', { class: 't' }, c.reason ? String(c.reason) : (c.status === 'pending' ? 'Waiting for the person' : '')),
      isNum(c.created) ? h('div', { class: 't muted' }, fmtDate(c.created)) : null))));
  }

  const CONTRACTS = [
    ['LoreRoles', 'Roles: verifier, curator, leak detector'],
    ['PersonRegistry', 'One World ID person, many linked wallets'],
    ['TopicGraph', 'Topics and the node commit graph'],
    ['Submissions', 'Stakes, verifier reports and votes'],
    ['Access', 'Soulbound ERC-1155 topic passes'],
    ['Royalties', 'Sale splits and royalty claims'],
    ['Reports', 'Leak reports and traced matches'],
    ['USDC', 'Test USDC, 6 decimals'],
  ];
  function renderContracts() {
    const c = state.data.chain;
    const map = c.contracts && typeof c.contracts === 'object' ? c.contracts : {};
    const names = CONTRACTS.map(([n]) => n).concat(Object.keys(map).filter((k) => !CONTRACTS.some(([n]) => n === k)));
    const base = explorerBase();
    add(clear($('contractsBody')), [
      h('p', { class: 'chain-line' }, `${c.name || '0G Galileo Testnet'}${isNum(c.chain_id) ? `, chain ${c.chain_id}` : ''}. `,
        h('a', { href: base, target: '_blank', rel: 'noopener noreferrer' }, 'Open the chain explorer')),
      h('ul', { class: 'contract-list' }, names.map((n) => {
        const a = map[n];
        const role = (CONTRACTS.find(([k]) => k === n) || [])[1];
        return h('li', { class: 'contract' },
          h('span', { class: 'name' }, n),
          h('span', {}, addrLink(a), isAddr(a) ? [' ', copyBtn(a, `Copy ${n} address`, true)] : null),
          role ? h('span', { class: 'role' }, role) : null);
      })),
    ]);
  }

  /* ================= orchestration ================= */
  function renderAll() {
    const d = state.data;
    if (state.topicId == null || !topicById(state.topicId)) state.topicId = d.topics.length ? d.topics[0].topic_id : null;
    // Keep any open proof panels open across live refreshes is not worth the complexity; selection is preserved instead.
    renderHeader(); renderPulse();
    renderTopicList();
    if (state.topicId != null && !(state.nodeId != null && nodeById(state.nodeId) && nodeById(state.nodeId).topic_id === state.topicId)) {
      selectTopic(state.topicId, null, false);
    } else renderTopic();
    renderFilters(); renderSubs();
  }

  let rt = null;
  window.addEventListener('resize', () => {
    clearTimeout(rt);
    rt = setTimeout(() => {
      if (!state.data) return;
      const w = $('graphWrap').clientWidth;
      if (w !== state.graphW) { state.graphW = w; renderGraph(); }
    }, 150);
  });

  state.api = resolveApi();
  load(true).then(() => {
    // Fragment navigation initially runs against empty sections. Restore it after hydration.
    const followFragment = () => {
      const target = document.getElementById(location.hash.slice(1));
      if (target) target.scrollIntoView({ behavior: 'instant', block: 'start' });
    };
    requestAnimationFrame(followFragment);
    window.addEventListener('hashchange', followFragment);
    if (state.api) setInterval(() => { if (!document.hidden) load(false); }, REFRESH_MS);
  });
})();
