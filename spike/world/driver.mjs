// Drives the real @worldcoin/idkit-core. No secrets pass through here: RP signatures come from world_rp.py.
//   node driver.mjs vectors           print the SDK's own outputs as JSON (spike/evidence/world-idkit-4.6.0.json)
//   node driver.mjs request < cfg     one request: prints {"connector"} then {"completion"}, one JSON per line
// `fake_reply` in cfg, or vectors mode, answers on a local bridge instead of World App, so proofs there are NOT real.
import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";
import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import { IDKit, deviceLegacy, hashSignal, orbLegacy, proofOfHuman } from "@worldcoin/idkit-core";
import { computeRpSignatureMessage, signRequest } from "@worldcoin/idkit-core/signing";
import { keccak_256 } from "@noble/hashes/sha3";

const PRESETS = { orbLegacy, deviceLegacy, proofOfHuman };
const hex = (b) => "0x" + Buffer.from(b).toString("hex");

function aes(key, iv, data, decrypt) {
  if (decrypt) {
    const d = createDecipheriv("aes-256-gcm", key, iv);
    d.setAuthTag(data.subarray(-16));
    return Buffer.concat([d.update(data.subarray(0, -16)), d.final()]);
  }
  const c = createCipheriv("aes-256-gcm", key, iv);
  return Buffer.concat([c.update(data), c.final(), c.getAuthTag()]);
}

async function localBridge() {
  const state = { sealed: null, response: null };
  const server = createServer(async (req, res) => {
    const chunks = [];
    for await (const c of req) chunks.push(c);
    res.setHeader("content-type", "application/json");
    if (req.method === "POST" && req.url === "/request") {
      state.sealed = JSON.parse(Buffer.concat(chunks));
      return res.end(JSON.stringify({ request_id: "11111111-1111-4111-8111-111111111111" }));
    }
    res.end(JSON.stringify(state.response ? { status: "completed", response: state.response } : { status: "initialized" }));
  });
  await new Promise((ok) => server.listen(0, "127.0.0.1", ok));
  return { state, url: `http://127.0.0.1:${server.address().port}`, close: () => server.close() };
}

function answer(bridge, connectorURI, reply) {
  const key = Buffer.from(new URL(connectorURI).searchParams.get("k"), "base64");
  const { iv, payload } = bridge.state.sealed;
  const asked = JSON.parse(aes(key, Buffer.from(iv, "base64"), Buffer.from(payload, "base64"), true));
  const out = randomBytes(12);
  bridge.state.response = { iv: out.toString("base64"),
    payload: aes(key, out, Buffer.from(JSON.stringify(reply)), false).toString("base64") };
  return asked;
}

async function openRequest(cfg, bridgeUrl) {
  const config = { app_id: cfg.app_id, action: cfg.action, rp_context: cfg.rp_context,
                   allow_legacy_proofs: cfg.allow_legacy_proofs, environment: cfg.environment };
  if (bridgeUrl) config.bridge_url = bridgeUrl;
  return IDKit.request(config).preset(PRESETS[cfg.preset]({ signal: cfg.signal }));
}

async function scenario(base, cfg, reply) {
  const bridge = await localBridge();
  try {
    const request = await openRequest({ ...base, ...cfg }, bridge.url);
    const asked = answer(bridge, request.connectorURI, reply);
    const completion = await request.pollUntilCompletion({ pollInterval: 10, timeout: 5000 });
    return { asked: { verification_level: asked.verification_level, allow_legacy_proofs: asked.allow_legacy_proofs,
                      environment: asked.environment, signal: asked.signal,
                      proof_requests: asked.proof_request?.proof_requests?.map((p) => p.identifier ?? p) },
             completion };
  } finally { bridge.close(); }
}

async function vectors() {
  const key = hex(keccak_256("lore world spike throwaway key, never funded or registered"));
  const signing = ["lore-person", "", "ação"].map((action) => {
    const s = signRequest({ signingKeyHex: key, action });
    const nonce = Buffer.from(s.nonce.slice(2), "hex");
    return { action, ...s, message: hex(computeRpSignatureMessage(nonce, s.createdAt, s.expiresAt, action)) };
  });
  const noAction = signRequest({ signingKeyHex: key, ttl: 60 });
  signing.push({ action: null, ...noAction, message: hex(computeRpSignatureMessage(
    Buffer.from(noAction.nonce.slice(2), "hex"), noAction.createdAt, noAction.expiresAt)) });

  const signals = ["", "0a1b2c3d4e5f60718293a4b5c6d7e8f9", "login-0a1b2c3d", "ação",
                   "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd", "0xABCDEFabcdefABCDEFabcdefABCDEFabcdefABCD", "0xabc", "0x"];
  const signal_hashes = Object.fromEntries(signals.map((s) => [s, hashSignal(s)]));

  const sig = signRequest({ signingKeyHex: key, action: "lore-person" });
  const rp_context = { rp_id: "rp_00000000000000ab", nonce: sig.nonce, created_at: sig.createdAt,
                       expires_at: sig.expiresAt, signature: sig.sig };
  const base = { app_id: "app_staging_0000000000000000000000000000000a", action: "lore-person", rp_context,
                 signal: signals[1], environment: "staging" };

  let page_exact_call;
  try {
    IDKit.request({ app_id: base.app_id, action: base.action, rp_context }).preset(orbLegacy({ signal: base.signal }));
    page_exact_call = "accepted";
  } catch (e) { page_exact_call = e.message; }

  const legacy = (level) => ({ proof: "0x" + "11".repeat(256), merkle_root: "0x" + "22".repeat(32),
                               nullifier_hash: "0x" + "33".repeat(31), verification_level: level });
  const v4 = { proof_response: { id: "req", version: 1, responses: [{ identifier: "proof_of_human", issuer_schema_id: 1,
    proof: "07".repeat(160), nullifier: "nil_00" + "44".repeat(31), expires_at_min: 1 }] } };
  return { idkit_core: "4.6.0", signing, signal_hashes, page_exact_call, scenarios: {
    orb_legacy: await scenario(base, { preset: "orbLegacy", allow_legacy_proofs: true }, legacy("orb")),
    device_legacy: await scenario(base, { preset: "deviceLegacy", allow_legacy_proofs: true }, legacy("device")),
    proof_of_human_v4: await scenario(base, { preset: "proofOfHuman", allow_legacy_proofs: true }, v4),
    proof_of_human_orb_fallback: await scenario(base, { preset: "proofOfHuman", allow_legacy_proofs: true }, legacy("orb")),
  } };
}

async function request() {
  const cfg = JSON.parse(readFileSync(0, "utf8"));
  const say = (o) => console.log(JSON.stringify(o));
  if (cfg.fake_reply) {
    const { completion } = await scenario(cfg, {}, cfg.fake_reply);
    say({ connector: "fake" });
    return say({ completion });
  }
  const pending = await openRequest(cfg);
  say({ connector: pending.connectorURI });
  say({ completion: await pending.pollUntilCompletion() });
}

const mode = process.argv[2];
if (mode === "vectors") console.log(JSON.stringify(await vectors(), null, 2));
else if (mode === "request") await request();
else { console.error("usage: driver.mjs vectors|request"); process.exit(2); }
