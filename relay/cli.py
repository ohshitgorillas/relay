"""The `relay` console script."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from relay import agents, loop
from relay.backends import replay
from relay.config import Config, load_config
from relay.errors import ExitCode, QueueFormatError, RelayError
from relay.ledger import Ledger
from relay.queue import parse_queue
from relay.state import State

_WEEK = 7 * 24 * 60 * 60


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"relay: {message}", file=sys.stderr)
        raise SystemExit(ExitCode.USAGE)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="relay")
    commands = parser.add_subparsers(
        dest="command", required=True, parser_class=_Parser
    )
    go = commands.add_parser("go")
    go.add_argument("queue", type=Path)
    go.add_argument("--token-budget", type=int)
    go.add_argument("--dollar-budget", type=float)
    go.add_argument("--context-limit", type=int)
    go.add_argument("--backend")
    commands.add_parser("stop").add_argument("queue", type=Path)
    answer = commands.add_parser("answer")
    answer.add_argument("queue", type=Path)
    answer.add_argument("section")
    answer.add_argument("text")
    commands.add_parser("status").add_argument("queue", type=Path)
    return parser


def _config(overrides: dict[str, object]) -> Config:
    return load_config(None, overrides)


def _go(args: argparse.Namespace) -> int:
    cfg = _config(
        {
            "token_budget": args.token_budget,
            "dollar_budget": args.dollar_budget,
            "context_limit": args.context_limit,
            "backend": args.backend,
        }
    )
    return loop.run(args.queue.resolve(), cfg)


def _stop(args: argparse.Namespace) -> int:
    state = State.open(args.queue.resolve(), _config({}))
    state.stop_file.touch()
    return ExitCode.QUEUE_EMPTY


def _answer(args: argparse.Namespace) -> int:
    queue = args.queue.resolve()
    section = next((s for s in parse_queue(queue) if s.id == args.section), None)
    if section is None:
        raise QueueFormatError(f"{queue}: no section {args.section!r}")
    if not section.open or not State.open(queue, _config({})).set_answer(args.section, args.text):
        print(f"relay: section {args.section} is done; answer dropped", file=sys.stderr)
    return ExitCode.QUEUE_EMPTY


def _section_activity(state: State, ledger: Ledger) -> dict[str, agents.Activity]:
    """Each section's agents, from the run logs whose session the ledger files under it.

    Runs are numbered and ledgered in the order they ran, so a session the ledger names
    more than once pairs its logs with its ledger lines in that order.
    """
    sections: dict[str, list[str]] = {}
    for section, session in ledger.sessions():
        sections.setdefault(session, []).append(section)
    logs = sorted(
        (p for p in state.run_dir.glob("*.jsonl") if p.stem.isdigit()), key=lambda p: int(p.stem)
    )
    found: dict[str, agents.Activity] = {}
    for log in logs:
        try:
            stream = replay(log)
        except OSError:
            continue
        owners = sections.get(stream.session_id or "")
        if not owners:
            continue
        section = owners.pop(0) if len(owners) > 1 else owners[0]
        found[section] = agents.merge(found.get(section, agents.Activity()), stream.activity)
    return found


def _agent_summary(activity: agents.Activity | None) -> str:
    if activity is None or not activity.agents:
        return ""
    summary = agents.summarise(activity)
    plural = "" if summary.count == 1 else "s"
    text = f"; {summary.count} agent{plural}, {agents.duration(summary.duration_ms)}"
    big = summary.biggest
    if big is not None and big.context:
        text += f", biggest {big.name} at context {big.context}: {big.description}"
    return text


def _status(args: argparse.Namespace) -> int:
    queue = args.queue.resolve()
    cfg = _config({})
    state = State.open(queue, cfg)
    path = state.ledger_path
    ledger = Ledger(path)
    activity = _section_activity(state, ledger)
    for section in parse_queue(queue):
        line = f"{section.id}  {state.section(section.id).status}"
        print(line + _agent_summary(activity.get(section.id)))
    week = ledger.total(time.time() - _WEEK)
    total = ledger.total(None)
    print(f"7 days: {week.tokens} tokens, ${week.dollars}")
    print(f"all time: {total.tokens} tokens, ${total.dollars}")
    bad = ledger.unreadable()
    if bad:
        numbers = ", ".join(str(n) for n in bad)
        print(f"{path}: skipped unreadable lines {numbers}")
    return ExitCode.QUEUE_EMPTY


_COMMANDS = {"go": _go, "stop": _stop, "answer": _answer, "status": _status}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return _COMMANDS[args.command](args)
    except RelayError as exc:
        print(f"relay: {exc}", file=sys.stderr)
        return exc.exit_code
