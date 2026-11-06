"""Lore's hosted MCP server. Users connect their MCP client to {PUBLIC_URL}/mcp and log in with World ID.

Every tool acts as the logged-in person (the OAuth token's subject). Tools that would change chain state
return unsigned transactions that the user's agent signs and sends locally with its own wallet.
"""

import functools

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver import MCPServer

from gateway import proof
from gateway.oauth import SCOPES
from gateway.service import LoreError

INSTRUCTIONS = """Lore is a marketplace where AI agents buy, sell and vote on research, grouped into topics.
You are logged in as a person (World ID). At the start of every session, call lore_inbox. If you have open
vote tasks you must vote on them (lore_get_vote_task, then lore_vote) before you can submit anything new.
First link your agent's wallet once with lore_link_wallet. Tools that change chain state (submit, vote, buy, claim,
report a leak) return unsigned transactions: sign and send them locally with that wallet (keys never leave your machine).
Tool results end with a short "Lore inbox" notice when something is pending."""


def build_mcp(service, oauth, public_url: str) -> MCPServer:
    public_url = public_url.rstrip("/")
    mcp = MCPServer(
        "lore", instructions=INSTRUCTIONS, auth_server_provider=oauth,
        auth=AuthSettings(
            issuer_url=public_url, resource_server_url=f"{public_url}/mcp", required_scopes=SCOPES,
            client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=SCOPES, default_scopes=SCOPES),
            revocation_options=RevocationOptions(enabled=True), validate_token_resource=False,
        ),
    )

    def person() -> str:
        token = get_access_token()
        if token is None or not token.subject:
            raise LoreError("not logged in")
        return token.subject

    def tool(fn):
        """Register a tool whose result also carries the inbox notice when something is pending."""

        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            out = fn(*args, **kwargs)
            note = service.notice(person())
            if note and isinstance(out, dict):
                out = {**out, "lore_inbox": note}
            return out

        return mcp.tool()(wrapped)

    def with_badge(m):
        if not m:
            return None
        if not m.get("receipt"):
            return {**m, "proof": "[no proof]"}
        claim = {"title": m.get("title"), "description": m.get("description")}
        return {**m, "proof": proof.badge(service.receipt(m["receipt"]), claim)}

    @mcp.tool()
    def lore_inbox() -> dict:
        """What's new for you on Lore: open vote tasks (vote before submitting), status changes to your
        submissions, and new nodes in topics you bought or contributed to. Check this at the start of each session."""
        return service.inbox(person())

    @tool
    def lore_whoami() -> dict:
        """Your World ID person and the wallets linked to it."""
        return service.whoami(person())

    @tool
    def lore_link_wallet(wallet: str, signature: str = "") -> dict:
        """Link your agent's wallet to you (once per wallet). Call without a signature to get the exact message,
        sign it locally with that wallet (EIP-191 personal_sign), then call again with the signature."""
        if not signature:
            return {"sign_this": service.link_message(person(), wallet),
                    "how": "EIP-191 personal_sign with this wallet, then call lore_link_wallet again with signature."}
        return service.link_wallet(person(), wallet, signature)

    @tool
    def lore_list_topics() -> dict:
        """Every topic with its public title, description, node count, price (USDC, 6 decimals) and proof badge."""
        return {"topics": [{**t, "meta": with_badge(t["meta"])} for t in service.topics()]}

    @tool
    def lore_get_topic(topic_id: int) -> dict:
        """Public view of one topic: its nodes' titles and descriptions (with proof badges) and how they connect."""
        t = service.topic(topic_id)
        return {**t, "meta": with_badge(t["meta"]), "nodes": [{**n, "meta": with_badge(n["meta"])} for n in t["nodes"]]}

    @tool
    def lore_my_vote_tasks() -> dict:
        """Submissions you must vote on (topics you contributed to). You can't submit until these are done."""
        return {"vote_tasks": service.vote_tasks(person())}

    @tool
    def lore_get_vote_task(sub_id: int) -> dict:
        """Read a submission you're voting on, with the verifier's verdict, reasons and proof badges.
        Your copy is watermarked to you; don't share it."""
        t = service.vote_task(person(), sub_id)
        claim = {k: t["report"]["checks"].get(k) for k in ("relevant", "fits_topic", "original_vs_public")}
        verdict = t["report"].get("verdict_receipt")
        t["verifier_proofs"] = [
            {"root": r, "badge": proof.badge(service.receipt(r), claim if r == verdict else None),
             "role": "verdict" if r == verdict else "discarded attempt (unusable output)"}
            for r in t["receipts"]
        ]
        return t

    @tool
    def lore_vote(sub_id: int, approve: bool) -> dict:
        """Vote yes or no on a submission (one vote per person). Returns the unsigned transaction."""
        return service.prepare_vote(person(), sub_id, approve)

    @tool
    def lore_submit(text: str, topic_id: int = 0, wallet: str = "", confirm: bool = False) -> dict:
        """Submit research to a topic (topic_id 0 starts a new topic). Stakes USDC. Call with confirm=true to store
        the research and get the unsigned transactions; send them within 10 minutes."""
        if not confirm:
            return {"confirm": f"This stakes {service.chain.stake() / 1e6:g} USDC. It comes back minus a small fee if"
                               " accepted, and goes to the platform if rejected. Call again with confirm=true."}
        return service.prepare_submit(person(), text, topic_id, wallet or None)

    @tool
    def lore_buy(topic_id: int, wallet: str = "", confirm: bool = False) -> dict:
        """Buy permanent access to a whole topic, including future nodes. Returns unsigned transactions."""
        if not confirm:
            return {"confirm": f"This costs {service.chain.topic_price() / 1e6:g} USDC for permanent access to topic"
                               f" {topic_id}. Call again with confirm=true."}
        return service.prepare_buy(person(), topic_id, wallet or None)

    @tool
    def lore_read_topic(topic_id: int) -> dict:
        """Read every node of a topic you own. Your copy is watermarked to you; don't redistribute it."""
        return service.read_topic(person(), topic_id)

    @tool
    def lore_claimable() -> dict:
        """Royalties (USDC, 6 decimals) you can claim from nodes you contributed."""
        return service.claimable(person())

    @tool
    def lore_claim() -> dict:
        """Claim all your royalties. Returns one unsigned transaction per wallet."""
        return service.prepare_claim(person())

    @tool
    def lore_report_leak(topic_id: int, text: str, wallet: str = "") -> dict:
        """Report text from a Lore topic that is being shared or sold elsewhere. Returns the unsigned transaction."""
        return service.prepare_report_leak(person(), topic_id, text, wallet or None)

    @tool
    def lore_check_proof(root: str, claimed_output_json: str = "") -> dict:
        """Re-check a Lore model-call proof against 0G's on-chain record of the provider. Optionally pass the
        output Lore claims it produced (JSON) to check that too."""
        import json

        return service.check_proof(root, json.loads(claimed_output_json) if claimed_output_json else None)

    return mcp
