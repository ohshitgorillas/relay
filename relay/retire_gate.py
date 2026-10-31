"""PreToolUse hook that refuses a new dispatch once the retire flag is up."""

import sys
from pathlib import Path

REFUSAL = (
    "Relay's retire flag is up: dispatch nothing new, wait for running agents, end with RETIRED."
)


def main(argv: list[str]) -> int:
    """argv[0] is the retire flag's path. Reads and discards the hook's stdin. Prints REFUSAL to
    stderr and returns 2 when the flag exists; otherwise returns 0."""
    sys.stdin.read()
    if Path(argv[0]).exists():
        print(REFUSAL, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
