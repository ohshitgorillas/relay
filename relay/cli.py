"""The `relay` console script."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from relay import loop
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
        }
    )
    return loop.run(args.queue.resolve(), cfg)


def _stop(args: argparse.Namespace) -> int:
    state = State.open(args.queue.resolve(), _config({}))
    state.stop_file.touch()
    return ExitCode.QUEUE_EMPTY


def _answer(args: argparse.Namespace) -> int:
    queue = args.queue.resolve()
    if args.section not in {section.id for section in parse_queue(queue)}:
        raise QueueFormatError(f"{queue}: no section {args.section!r}")
    State.open(queue, _config({})).set_answer(args.section, args.text)
    return ExitCode.QUEUE_EMPTY


def _status(args: argparse.Namespace) -> int:
    queue = args.queue.resolve()
    cfg = _config({})
    state = State.open(queue, cfg)
    for section in parse_queue(queue):
        print(f"{section.id}  {state.section(section.id).status}")
    path = state.ledger_path
    ledger = Ledger(path)
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
