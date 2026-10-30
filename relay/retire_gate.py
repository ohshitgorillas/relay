"""PreToolUse hook that refuses a new dispatch once the retire flag is up."""

REFUSAL = "Relay's retire flag is up: dispatch nothing new, wait for running agents, end with RETIRED."


def main(argv: list[str]) -> int:
    """argv[0] is the retire flag's path. Reads and discards the hook's stdin. Prints REFUSAL to
    stderr and returns 2 when the flag exists; otherwise returns 0."""
    raise NotImplementedError
