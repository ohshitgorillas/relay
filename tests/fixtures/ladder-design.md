Status: approved.

# Ladder fixture: one, two and three

## Why

The queue at `tests/fixtures/ladder-queue.md` runs this design. Its sections name the Order steps below in their `steps:` fields, so a design change for any section amends an Order step this file holds.

## Modules

### `one.py` (new)

```python
def one() -> int:
    """1."""
```

### `two.py` (new)

```python
def two() -> int:
    """one() + one()."""
```

### `three.py` (new)

```python
def three() -> int:
    """two() + one()."""
```

## Homes

| Concern | Home | Forbidden elsewhere |
|---|---|---|
| The number one | `one.py` `one` | a literal 1 anywhere else |
| Adding up | `two.py`, `three.py` | a sum built from literals |

## Order

1. One: red tests. `test-writer` writes `tests/test_one.py`.
2. One: build. `builder` writes `one.py`.
3. Two: build. `builder` writes `two.py`. The step ends with `tests/test_two.py` green.
4. Three: build. `builder` writes `three.py`.
