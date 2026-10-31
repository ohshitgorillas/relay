"""The `relay` console script."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from relay import agents, history, loop, runner, stats
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
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    go = commands.add_parser("go")
    go.add_argument("queue", type=Path)
    go.add_argument("--token-budget", type=int)
    go.add_argument("--dollar-budget", type=float)
    go.add_argument("--context-limit", type=int)
    go.add_argument("--backend")
    go.add_argument("--idle-ceiling", type=int)
    go.add_argument("--section-dollar-cap", type=float)
    commands.add_parser("stop").add_argument("queue", type=Path)
    answer = commands.add_parser("answer")
    answer.add_argument("queue", type=Path)
    answer.add_argument("section")
    answer.add_argument("text")
    ask = commands.add_parser("ask")
    ask.add_argument("--backend")
    ask.add_argument("queue", type=Path)
    ask.add_argument("section")
    ask.add_argument("question")
    commands.add_parser("status").add_argument("queue", type=Path)
    commands.add_parser("stats")
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
            "idle_ceiling": args.idle_ceiling,
            "section_dollar_cap": args.section_dollar_cap,
        }
    )
    return loop.run(args.queue.resolve(), cfg)


def _stop(args: argparse.Namespace) -> int:
    state = State.open(args.queue.resolve(), _config({}))
    live = state.live_run()
    if live is not None and live.pid != os.getpid():
        runner.signal_drain(live.pid)
    else:
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


def _ask(args: argparse.Namespace) -> int:
    print(
        loop.ask(
            args.queue.resolve(), _config({"backend": args.backend}), args.section, args.question
        )
    )
    return ExitCode.QUEUE_EMPTY


def _ran_at(run: history.Run) -> float:
    """When the run's log was last written, the time it finished; 0 if the log cannot be stat'd."""
    try:
        return run.log.stat().st_mtime
    except OSError:
        return 0.0


def _stats(args: argparse.Namespace) -> int:
    cfg = _config({})
    states = State.all(cfg)
    if not states:
        print(f"no runs under {cfg.state_root}")
        return ExitCode.QUEUE_EMPTY
    runs: list[history.Run] = []
    skipped = 0
    for state in states:
        found = history.read(state, Ledger(state.ledger_path))
        runs.extend(found.runs)
        skipped += found.skipped_logs
    runs.sort(key=_ran_at)  # stable: runs of one queue keep their order when times tie
    merged = history.History(runs=tuple(runs), skipped_logs=skipped)
    for line in stats.lines(stats.by_role(stats.sized(merged, cfg))):
        print(line)
    if skipped:
        print(f"skipped {skipped} unreadable run logs")
    return ExitCode.QUEUE_EMPTY


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
    activity = history.activity_by_section(history.read(state, ledger))
    live = state.live_run()
    if live is not None and live.draining and live.draining_since is not None:
        since = time.strftime("%H:%M", time.localtime(live.draining_since))
        print(f"run: draining since {since} (pid {live.pid})")
    for section in parse_queue(queue):
        record = state.section(section.id)
        line = f"{section.id}  {record.status}"
        if record.status == "waiting":
            line += f" on {record.waits_on}"
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


_COMMANDS = {
    "go": _go,
    "stop": _stop,
    "answer": _answer,
    "status": _status,
    "ask": _ask,
    "stats": _stats,
}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return _COMMANDS[args.command](args)
    except RelayError as exc:
        print(f"relay: {exc}", file=sys.stderr)
        return exc.exit_code
