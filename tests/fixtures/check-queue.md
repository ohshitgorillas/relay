design /tmp/relay-check-fixture/docs/superpowers/specs/check-fixture-design.md | order /tmp/relay-check-fixture/docs/superpowers/specs/check-fixture-design.md | main 1234567
section s1 | lead | steps: 1, 2 | size: lead: tokens: 900000.0 seconds: 600.0 overruns: 0 refusals: 0
  s1.d1 | test-writer | steps: 1 | writes: tests/test_one.py | size: test-writer: tokens: 500000.0 seconds: 150.0 overruns: 0 refusals: 0
    queue /tmp/relay-check-fixture/docs/queue.md s1.d1
    red
    behavior: the lead runs the check: never this line's text
    check: uv run python -m pytest tests/test_one.py
  s1.d2 | builder | steps: 2 | writes: one.py | size: builder: tokens: 300000.0 seconds: 150.0 overruns: 0 refusals: 0
    queue /tmp/relay-check-fixture/docs/queue.md s1.d2
    paths: one.py
    ```
    check: echo inside a fence
    done-check: echo inside a fence too
    ```
    done-check: make check && echo ok
check: python3 -c 'print(1)'
section s2 | lead | steps: 3 | size: lead: tokens: 900000.0 seconds: 600.0 overruns: 0 refusals: 0
  s2.d1 | general-purpose | steps: 3 | writes: notes.txt | size: general-purpose: tokens: 100000.0 seconds: 60.0 overruns: 0 refusals: 0
    queue /tmp/relay-check-fixture/docs/queue.md s2.d1
    paths: notes.txt
section s4a | lead | steps: 4 | from: s4 | size: lead: tokens: 900000.0 seconds: 600.0 overruns: 0 refusals: 0
  s4a.d1 | builder | steps: 4 | writes: four.py | size: builder: tokens: 300000.0 seconds: 150.0 overruns: 0 refusals: 0
    queue /tmp/relay-check-fixture/docs/queue.md s4a.d1
    paths: four.py
    check: uv run python -m pytest tests/test_four.py
