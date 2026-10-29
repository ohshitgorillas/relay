"""In-process scripted agent, retaining the real stream parser and callbacks."""

import json
import os
import re
import subprocess
import time
from pathlib import Path

from relay.ledger import Spend
from relay.runner import RunResult
from relay.stream import StreamState, feed


class FakeRunner:
    def __init__(self, scenarios: list[Path]):
        self.scenarios = scenarios
        self.calls = []

    def __call__(self, argv, stdin_text, cwd, run_dir, on_event, retire_flag):
        index = len(self.calls)
        call = dict(argv=argv, prompt=stdin_text, cwd=str(cwd), appeared=[])
        paths = {Path(p.rstrip('.,;:)')) for p in re.findall(r"/[^\s`'\"<>]+", stdin_text)}
        before = {p for p in paths if p.exists()}
        self.calls.append(call)
        scenario = None
        second = None
        gate = None
        exit_code = 0
        record = None
        split = 0
        if argv[0] in ('fake-record', 'fake-plan', 'fake-climb'):
            directory = Path(argv[1])
            n = len(list(directory.glob('run-*.json')))
            record = directory / f'run-{n}.json'
            if argv[0] == 'fake-record':
                split = int(argv[2])
                if argv[3]:
                    Path(argv[3]).touch()
            elif argv[0] == 'fake-plan':
                plan = json.loads(argv[2])
                steps = plan['steps']
                step = steps[n % len(steps)] if plan['cycle'] else steps[min(n, len(steps) - 1)]
                scenario = Path(step['scenario'])
                exit_code = step['exit']
                if step.get('write'):
                    source, target = map(Path, step['write'])
                    target.write_bytes(source.read_bytes())
                if step.get('then'):
                    subprocess.run(step['then'], cwd=cwd, stdin=subprocess.DEVNULL, check=True)
            else:
                steps = json.loads(argv[2])
                step = steps[min(n, len(steps) - 1)]
                scenario = Path(step['first'])
                second = Path(step['second']) if step['second'] else None
                gate = Path(step['gate']) if step['gate'] else None
        if scenario is None:
            scenario = self.scenarios[min(index, len(self.scenarios) - 1)] if self.scenarios else Path(os.environ['RELAY_FAKE_SCENARIO'])
        def save():
            if record is not None:
                temporary = record.with_suffix('.part')
                temporary.write_text(json.dumps(call))
                temporary.replace(record)
        save()
        run_dir.mkdir(parents=True, exist_ok=True)
        log = run_dir / f'{index + 1}.jsonl'
        state = StreamState(None, 0, Spend(0, 0.0), None, False)
        killed = False
        with log.open('w') as output:
            def emit(stream):
                nonlocal state, killed, exit_code
                for number, line in enumerate(stream.read_text().splitlines(), 1):
                    try:
                        event = json.loads(line)
                    except ValueError:
                        event = None
                    if isinstance(event, dict) and event.get('fake') == 'await-flag':
                        call['appeared'] = sorted(str(p) for p in paths - before if p.exists())
                        save()
                        continue
                    output.write(line + '\n')
                    output.flush()
                    state = feed(state, line)
                    action = on_event(state)
                    if action == 'retire':
                        retire_flag.touch()
                    if number == split:
                        call['appeared'] = sorted(str(p) for p in paths - before if p.exists())
                        save()
                    if action == 'kill':
                        killed = True
                        exit_code = None
                        break

            emit(scenario)
            if second is not None and not killed:
                if gate is not None:
                    (gate / 'ready').touch()
                    deadline = time.monotonic() + 15
                    while not (gate / 'go').exists():
                        assert time.monotonic() < deadline, 'climbing agent gate never opened'
                        time.sleep(0.02)
                emit(second)
        call['retire-flag-seen'] = retire_flag.exists()
        save()
        return RunResult(exit_code, killed, state, log)
