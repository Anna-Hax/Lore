"""What's new for this user on Lore, kept fresh by polling the gateway.

lore-mcp refreshes it once at startup (so the agent sees pending work as soon as it
connects) and then in the background while it runs. MCP can't make an idle agent act,
so updates are surfaced in the server instructions at startup and as a short notice on
every tool result; `lore_inbox` returns the full list.

State (last node seen, last known status of each submission) is saved to disk, so
"new" means new since the previous session too.
"""

import json
import logging
import threading
import time
from pathlib import Path

log = logging.getLogger("lore_mcp.inbox")


class Inbox:
    def __init__(self, fetch, state_path: str | Path):
        """fetch(since_node) -> the gateway's /inbox JSON."""
        self.fetch, self.lock = fetch, threading.Lock()
        self.refreshing = threading.Lock()  # one refresh at a time: the poller and lore_inbox can overlap
        self.vote_tasks, self.updates = [], []
        self.load(state_path)

    def load(self, state_path: str | Path) -> None:
        """Use (and read) the state file at this path; a missing or corrupt file starts fresh."""
        self.path = Path(state_path)
        try:
            self.state = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.state = {}

    def refresh(self) -> None:
        with self.refreshing:
            self._refresh()

    def _refresh(self) -> None:
        first_run = "since_node" not in self.state  # don't flood a brand-new user with history
        data = self.fetch(self.state.get("since_node", 0))
        with self.lock:
            self.vote_tasks = data["vote_tasks"]
            known = self.state.get("subs", {})
            for s in data["submissions"]:
                before = known.get(str(s["sub_id"]))
                if not first_run and before != s["status"] and not (before is None and s["status"] == "Pending"):
                    node = f" as node #{s['node_id']}" if s["node_id"] else ""
                    self.updates.append(f"Your submission #{s['sub_id']} is now {s['status']}{node}.")
            if not first_run:
                for n in data["new_nodes"]:
                    self.updates.append(f"New node #{n['node_id']} in topic {n['topic_id']}: {n['title'] or '(title pending)'}")
            nodes = data["new_nodes"]
            # If the page was full, resume after the last node we saw rather than skipping the rest.
            self.state["since_node"] = nodes[-1]["node_id"] if len(nodes) >= 100 else data["latest_node"]
            self.state["subs"] = {str(s["sub_id"]): s["status"] for s in data["submissions"]}
            self._save()

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.state))
        except OSError as e:
            log.warning("could not save inbox state: %s", e)

    def notice(self) -> str | None:
        """One line for the end of every tool result, or None when there's nothing pending."""
        with self.lock:
            v, u = len(self.vote_tasks), len(self.updates)
        if not v and not u:
            return None
        parts = []
        if v:
            parts.append(f"{v} open vote task{'s' * (v != 1)} (you must vote before you can submit)")
        if u:
            parts.append(f"{u} new update{'s' * (u != 1)}")
        return "Lore inbox: " + " and ".join(parts) + ". Call lore_inbox to see them."

    def take(self) -> dict:
        """The full inbox. Updates are cleared once shown; vote tasks stay until you vote."""
        with self.lock:
            out = {"vote_tasks": list(self.vote_tasks), "updates": list(self.updates)}
            self.updates.clear()
        return out

    def poll_forever(self, every: int) -> None:
        while True:
            time.sleep(every)
            try:
                self.refresh()
            except Exception as e:  # gateway down: keep the last known inbox, try again next round
                log.warning("inbox poll failed: %s", e)
