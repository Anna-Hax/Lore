"""BUILD_PLAN workstream E: three agents drive Lore using only lore-mcp, then we assert the chain.

PAUSED: lore-mcp was replaced by the hosted MCP server (World ID login, unsigned transactions until the
signing step). This runner must be redone against the hosted server once signing exists; main() refuses to
run until then. The helpers below and their tests still stand.

Needs the hosted gateway, verifier and curator running, plus gas on three wallets:
    E2E_AGENT1_KEY, E2E_AGENT2_KEY, E2E_AGENT3_KEY, LORE_GATEWAY_URL
    E2E_MCP_COMMAND (default "uvx lore-mcp"), LORE_CHAIN_ID (default 16602), LORE_RPC (optional)

    uv run --project shared --locked --group platform python e2e/run.py
    ... python e2e/run.py --check    # only start lore-mcp and compare its tool list; no chain writes

Only MockUSDC funding happens outside MCP, as the plan allows. Each run uses fresh text,
because the contract refuses an exact contentHash twice.
"""

import argparse
import asyncio
from contextlib import AsyncExitStack
import json
import os
import re
import secrets
import shlex
import time

from eth_account import Account
from mcp import ClientSession, StdioServerParameters, stdio_client

from lore_shared.chain import ChainReader
from lore_shared.watermark import FRAME, ONE, ZERO

TOOLS = {
    "lore_list_topics", "lore_get_topic", "lore_my_vote_tasks", "lore_get_vote_task", "lore_vote", "lore_submit",
    "lore_buy", "lore_read_topic", "lore_claimable", "lore_claim", "lore_report_leak", "lore_check_proof",
}
PENDING, REPORTED, ACCEPTED, REJECTED = range(4)
TIMEOUT = float(os.environ.get("E2E_TIMEOUT", 900))


def research(subject: str, tag: str) -> str:
    """Synthetic text above MIN_CHARS; never real research."""
    lines = [f"Finding {i} on {subject} from run {tag} measured a distinct effect in sample {i * 7}." for i in range(1, 12)]
    return " ".join(lines)


def visible(text: str) -> str:
    return text.translate(str.maketrans("", "", FRAME + ZERO + ONE))


def three_sentences(text: str) -> str:
    """A marked 3-sentence excerpt from the middle of a delivered copy."""
    ends = [match.end() for match in re.finditer(re.escape(FRAME) + f"[{ZERO}{ONE}]{{64}}" + re.escape(FRAME), text)]
    if len(ends) < 5:
        raise AssertionError("delivered copy has too few watermark marks")
    return text[ends[0]:ends[3]].strip()


class Agent:
    def __init__(self, name: str, key: str, session: ClientSession):
        self.name, self.key, self.session = name, key, session
        self.address = Account.from_key(key).address

    async def tool(self, name: str, **arguments):
        result = await self.session.call_tool(name, arguments)
        text = "".join(getattr(item, "text", "") for item in result.content)
        if result.is_error:
            raise RuntimeError(f"{self.name} {name}: {text}")
        if result.structured_content is not None:
            data = result.structured_content
            return data.get("result", data) if set(data) == {"result"} else data
        return text


async def start(stack: AsyncExitStack, name: str, key: str, gateway: str) -> Agent:
    command = shlex.split(os.environ.get("E2E_MCP_COMMAND", "uvx lore-mcp"))
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp"), "LORE_PRIVATE_KEY": key,
           "LORE_GATEWAY_URL": gateway, "LORE_CHAIN_ID": os.environ.get("LORE_CHAIN_ID", "16602"),
           "LORE_STATE": f"/tmp/lore-e2e-{name}.json"}
    if os.environ.get("LORE_RPC"):
        env["LORE_RPC"] = os.environ["LORE_RPC"]
    params = StdioServerParameters(command=command[0], args=command[1:], env=env)
    streams = await stack.enter_async_context(stdio_client(params))
    session = await stack.enter_async_context(ClientSession(*streams))
    await session.initialize()
    return Agent(name, key, session)


async def wait_for(description: str, check, every: float = 5):
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        value = await asyncio.to_thread(check)
        if value:
            return value
        await asyncio.sleep(every)
    raise TimeoutError(f"timed out waiting for {description}")


class Scenario:
    def __init__(self, reader: ChainReader, agents: list[Agent]):
        self.reader, self.agents, self.tag = reader, agents, secrets.token_hex(4)
        self.subs = reader.call("Submissions", "submissionCount")

    def submission(self, sub_id: int) -> dict:
        return self.reader.record("Submissions", "getSubmission", sub_id)

    def usdc(self, agent: Agent) -> int:
        return self.reader.call("USDC", "balanceOf", agent.address)

    async def submit(self, agent: Agent, text: str, topic_id: int = 0) -> int:
        await agent.tool("lore_submit", text=text, topic_id=topic_id, confirm=True)
        self.subs += 1
        return self.subs

    async def status(self, sub_id: int, *wanted: int) -> dict:
        return await wait_for(f"submission {sub_id} status {wanted}",
                              lambda: (s := self.submission(sub_id))["status"] in wanted and s)

    def fund(self, amount: int) -> None:
        web3 = self.reader.web3
        for agent in self.agents:
            account = Account.from_key(agent.key)
            call = self.reader.contracts["USDC"].functions.mint(account.address, amount)
            tx = call.build_transaction({"from": account.address, "nonce": web3.eth.get_transaction_count(account.address)})
            receipt = web3.eth.wait_for_transaction_receipt(web3.eth.send_raw_transaction(account.sign_transaction(tx).raw_transaction))
            assert receipt.status == 1, "MockUSDC mint failed"

    async def run(self) -> dict:
        one, two, three = self.agents
        stake = self.reader.call("Submissions", "stake")
        fee = self.reader.call("Submissions", "stakeFee")
        price = self.reader.call("Access", "topicPrice")
        await asyncio.to_thread(self.fund, 10 * stake)

        # 1. Agent 1 creates a topic and the verifier accepts it.
        start_one = self.usdc(one)
        first = await self.submit(one, research("sequencer fees", self.tag))
        record = await self.status(first, ACCEPTED, REJECTED)
        assert record["status"] == ACCEPTED, "new topic was rejected"
        assert self.usdc(one) == start_one - fee, "accepted stake was not returned minus fee"
        topic = self.reader.call("TopicGraph", "topicCount")
        node = (await wait_for("node 1", lambda: self.reader.call("TopicGraph", "topicNodes", topic)))[0]
        assert self.reader.call("TopicGraph", "contributorSince", topic, one.address) > 0

        # 2. Agent 2 buys and reads; Agent 1 claims royalties.
        await two.tool("lore_buy", topic_id=topic, confirm=True)
        copy = (await two.tool("lore_read_topic", topic_id=topic))["nodes"][0]["text"]
        assert visible(copy) == research("sequencer fees", self.tag) and copy != visible(copy)
        before = self.usdc(one)
        await one.tool("lore_claim")
        assert self.usdc(one) > before, "royalties were not paid"

        # 3. Agent 2 has no vote tasks, so its follow-up goes through.
        assert (await two.tool("lore_my_vote_tasks"))["vote_tasks"] == []
        follow = await self.submit(two, research("blob pricing", self.tag), topic)
        await self.status(follow, REPORTED)

        # 4. Agent 1 must vote before submitting again.
        try:
            await one.tool("lore_submit", text=research("blocked", self.tag), topic_id=topic, confirm=True)
        except RuntimeError as error:
            assert "vote" in str(error).lower(), error
        else:
            raise AssertionError("vote gate did not stop Agent 1")
        task = await one.tool("lore_get_vote_task", sub_id=follow)
        await one.tool("lore_vote", sub_id=follow, approve=True)
        await self.status(follow, ACCEPTED)
        nodes = await wait_for("second node", lambda: (n := self.reader.call("TopicGraph", "topicNodes", topic)) and len(n) == 2 and n)
        assert list(self.reader.call("TopicGraph", "parentsOf", nodes[1])) == [node], "edge does not point to node 1"

        # 5. Agent 3's near-copy of a pending submission is rejected and slashed.
        original = research("data availability", self.tag)
        pending = await self.submit(one, original, topic)
        await self.status(pending, REPORTED)
        start_three = self.usdc(three)
        copycat = await self.submit(three, original + " Minor edit.", topic)
        record = await self.status(copycat, REPORTED)
        assert record["pass"] is False, "verifier passed a near-copy"
        await two.tool("lore_vote", sub_id=pending, approve=True)
        await two.tool("lore_vote", sub_id=copycat, approve=False)
        await one.tool("lore_vote", sub_id=copycat, approve=False)
        await self.status(pending, ACCEPTED)
        await self.status(copycat, REJECTED)
        assert self.usdc(three) == start_three - stake, "rejected stake was not slashed"

        # 6. Agent 3 buys and leaks; the lookup names Agent 3.
        await three.tool("lore_buy", topic_id=topic, confirm=True)
        leaked = three_sentences((await three.tool("lore_read_topic", topic_id=topic))["nodes"][0]["text"])
        reports = self.reader.call("Reports", "nextReportId")
        await one.tool("lore_report_leak", topic_id=topic, text=leaked)
        match = await wait_for("leak match", lambda: (r := self.reader.record("Reports", "getReport", reports))["matched"] and r)
        assert match["matchedWallet"].lower() == three.address.lower(), "leak matched the wrong wallet"

        # 7. Every receipt passes; a false claim fails.
        roots = set(task["receipts"])
        public = await one.tool("lore_get_topic", topic_id=topic)
        roots.update(n["meta"]["receipt"] for n in public["nodes"] if n.get("meta"))
        assert roots, "no receipts were produced"
        for root in sorted(roots):
            checked = await one.tool("lore_check_proof", root=root)
            assert checked["status"] == "pass", (root, checked)
        false_claim = json.dumps({"title": "not what the model signed"})
        assert (await one.tool("lore_check_proof", root=sorted(roots)[0], claimed_output_json=false_claim))["status"] == "fail"

        # 8. Final graph shape.
        final = self.reader.call("TopicGraph", "topicNodes", topic)
        assert len(final) == 3 and self.reader.call("Access", "hasAccess", topic, three.address)
        assert price > 0
        return {"passed": True, "run": self.tag, "topic": topic, "nodes": list(final), "receipts_checked": len(roots)}


async def main(check_only: bool) -> dict:
    raise SystemExit("e2e/run.py is paused: it drove the local lore-mcp, which is replaced by the hosted MCP "
                     "server. It needs the signing step before it can send transactions; see BUILD_PLAN workstream E.")
    gateway = os.environ["LORE_GATEWAY_URL"]
    async with AsyncExitStack() as stack:
        if check_only:
            agent = await start(stack, "check", "0x" + secrets.token_hex(32), gateway)
            tools = {tool.name for tool in (await agent.session.list_tools()).tools}
            return {"tools_ok": TOOLS <= tools, "missing": sorted(TOOLS - tools)}
        keys = [os.environ[f"E2E_AGENT{i}_KEY"] for i in (1, 2, 3)]
        agents = [await start(stack, f"agent{i}", key, gateway) for i, key in enumerate(keys, 1)]
        chain_id = int(os.environ.get("LORE_CHAIN_ID", 16602))
        return await Scenario(ChainReader(chain_id, rpc_url=os.environ.get("LORE_RPC")), agents).run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    report = asyncio.run(main(parser.parse_args().check))
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report.get("passed") or report.get("tools_ok") else 2)
