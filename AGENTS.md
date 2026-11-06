# AGENTS.md

Instructions for any coding agent working in this repo.

## What this is

Lore is a decentralized marketplace where AI agents sell research to each other. Each topic is a commit graph of encrypted research nodes.
- **On 0G:** the contracts run on 0G Chain, the encrypted content lives on 0G Storage, and every model call goes through 0G Compute as a verified, private run with a stored proof.
- **On our own host:** Lore's agents: the gateway (which is also the hosted MCP server users connect to), the verifier and the curator.
- **Users** connect their own MCP clients to the hosted MCP server and log in with World ID. There is no other login.

- **`BUILD_PLAN.md` is the source of truth.** Read it fully before starting. Section 0 says who owns what, and section 3 holds the frozen interfaces.
- Product spec: https://claude.ai/artifact/KvzhXcdgHuhuBvokj7iKbf
- Human-readable plan: https://claude.ai/artifact/JrdBV6YKxMdCrf73hBKqV4

## Ownership

Work only inside the paths your person owns (`BUILD_PLAN.md` section 0). Changing someone else's paths, or anything in section 3 of the plan, needs their approval. Raise it with them instead of doing it.

| Person | Paths |
|---|---|
| P1 (agents) | `agents/*` |
| P2 (contracts) | `contracts/`, `shared/lore_shared/{abi,deployments,network.py}` |
| P3 (platform) | `spike/`, `deploy/`, `e2e/`, the rest of `shared/` |

## Stack

- **Contracts:** Solidity ^0.8.24, Foundry, OpenZeppelin v5.
- **Off-chain:** Python 3.12 in a `uv` workspace, tested with `pytest`.
- **Chain:** `web3.py` v7 and `eth-account`.
- **Gateway API:** FastAPI.
- **MCP:** the official `mcp` Python SDK (`MCPServer`, streamable HTTP, OAuth 2.1 with World ID login), hosted inside the gateway.
- **Models:** the 0G Compute Router via the `openai` client, used only through `agents/zg` (`BUILD_PLAN.md` section 2.1).

## Rules

- **Never return plaintext content** from any endpoint unless the on-chain access, vote-eligibility or role check has passed. Every endpoint that returns content has a test proving the check is there.
- **Every model call goes through `agents/zg`,** in private mode with `verify_tee: true`, and its receipt is verified and stored. Never fall back to a lower trust tier, and never send submission or node text outside 0G private mode.
- **Secrets** (`MASTER_KEY`, `WM_SECRET`, wallet keys, API keys) live only in the host's secret store or a local `.env`. Never commit them, print them or log them. How users' transactions get signed (a password manager) is still being designed: don't build signing until it is.
- **Don't invent network values.** RPC URLs, chain IDs and storage endpoints come from the official 0G docs and go in `shared/lore_shared/network.py`.
- **Keep it lean.** Don't add a framework, abstraction, dependency or service that the plan doesn't call for. If something seems missing, ask instead of building it.
- **Leave one runnable check behind** for any non-trivial logic: a Foundry test for contracts, and a `pytest` test for Python.

## Git

### Branches

- **Never commit to or push to `main` directly.** Each person works on their own long-lived branch and pushes only there:

  | Person | Branch |
  |---|---|
  | P1 (agents) | `p1/agents` |
  | P2 (contracts) | `p2/contracts` |
  | P3 (platform) | `p3/platform` |

- **Sync with `main` at least once a day,** and always before opening a PR: `git fetch origin && git merge origin/main`. Merge, don't rebase, so a branch that's already pushed never needs a force-push. Resolve conflicts on your own branch, never on `main`.
- **Get work into `main` with a PR** from your branch, at least once per finished unit (a contract plus its tests, an MCP tool, a library). One of the other two people reviews and merges it. Small, frequent PRs beat one big one at the end.
- **When a teammate's work you depend on lands in `main`** (for example ABIs from P2, or libraries from P3), sync right away rather than waiting for your daily sync.

### Commits

- **One unit of work per commit.** Each feature, fix or chore gets its own commit; don't batch unrelated changes.
- **Show the diff before committing.** Let your human review it, preferably in chat; otherwise open it in VS Code or give them a command to run in a terminal.
- **Follow [Conventional Commits](https://www.conventionalcommits.org/):** `<type>(<optional scope>): <description>`.
  - Types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `perf`, `build`, `ci`, `style`, `revert`.
  - Write the description in the imperative mood: `fix: handle null user id`, not `fixed ...`.
  - Add a body or footer when context helps, and `BREAKING CHANGE:` in the footer for breaking changes.
  - Suggested scopes: `contracts`, `gateway`, `verifier`, `curator`, `zg`, `mcp`, `shared`, `spike`, `deploy`, `e2e`, `plan`.
- **Commit as your human.** Use the git identity configured on the machine (`user.name` / `user.email`), and never override the author or committer.
- **No AI attribution.** No `Co-Authored-By: Claude` (or any other AI) trailers, and no "Generated with ..." lines in commits or PR descriptions.
- **Only commit or push when your human asks.** Never force-push to `main` or to another person's branch.
