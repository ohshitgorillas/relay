"""The one place for every Relay error type and process exit code."""


class RelayError(Exception):
    exit_code: int = 1


class ConfigError(RelayError):
    exit_code = 2


class QueueFormatError(RelayError):
    exit_code = 2


class LockedError(RelayError):
    exit_code = 2


class ExitCode:
    QUEUE_EMPTY = 0
    ERROR = 1
    USAGE = 2
    BUDGET = 3
    STOP_FILE = 4
    FAILED_TWICE = 5
    INTERRUPTED = 130
