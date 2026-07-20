"""Phase 3 entry point — ask a multi-step question, see the agent-hop trace.

    python -m agents.run "Compare the net interest income trend for JPMorgan
        vs Bank of America since 2023, and what risks did management flag?"

State is checkpointed to Postgres (the same finsight-db), so runs are
resumable and the human-in-the-loop interrupt can pause and continue.
Use --reject to simulate a human rejecting a low-confidence answer.
"""
from __future__ import annotations

import argparse
import uuid

from langgraph.types import Command
from rich.console import Console
from rich.panel import Panel

from agents.graph import build_graph
from config import DATABASE_URL

console = Console()


def _print_trace(state: dict) -> None:
    console.print("\n[bold]agent trace[/bold]")
    for line in state.get("trace", []):
        console.print(f"  {line}")


def run(question: str, human_decision: str = "approved") -> None:
    from langgraph.checkpoint.postgres import PostgresSaver

    with PostgresSaver.from_conn_string(DATABASE_URL) as cp:
        cp.setup()  # idempotent: creates checkpoint tables on first use
        app = build_graph(checkpointer=cp)
        cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}

        state = app.invoke({"question": question, "trace": []}, cfg)

        # human-in-the-loop: the graph paused at the interrupt
        if state.get("__interrupt__"):
            intr = state["__interrupt__"][0].value
            _print_trace(state)
            console.print(Panel(
                f"[yellow]LOW-CONFIDENCE — human review requested[/yellow]\n\n"
                f"issues: {intr.get('issues')}\n\n"
                f"proposed draft:\n{intr.get('draft','')[:500]}...",
                title="human-in-the-loop"))
            console.print(f"[dim]resuming with decision: {human_decision}[/dim]")
            state = app.invoke(Command(resume=human_decision), cfg)

    _print_trace(state)
    console.print(Panel(state.get("answer") or "(no answer)", title="FinSight answer"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--reject", action="store_true",
                    help="simulate a human rejecting the answer at the HITL gate")
    args = ap.parse_args()
    run(args.question, human_decision="rejected" if args.reject else "approved")
