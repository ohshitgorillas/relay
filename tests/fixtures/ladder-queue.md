design docs/superpowers/specs/ladder-design.md | order docs/superpowers/specs/ladder-design.md | main 1234567
section s1 | lead | steps: 1, 2 | cap: $5 | size: lead: tokens: 900000.0 seconds: 600.0 overruns: 0 refusals: 0
  s1.d1 | test-writer | steps: 1 | writes: tests/test_one.py | size: test-writer: tokens: 500000.0 seconds: 150.0 overruns: 0 refusals: 0
    queue docs/queue.md s1.d1
    red
    behavior: one returns one
    check: uv run python -m pytest tests/test_one.py
  s1.d2 | builder | steps: 2 | writes: one.py | size: builder: tokens: 300000.0 seconds: 150.0 overruns: 0 refusals: 0
    queue docs/queue.md s1.d2
    paths: one.py
section s2 | lead | steps: 3 | depends: s1 | cap: 2.5 | size: lead: tokens: 900000.0 seconds: 600.0 overruns: 0 refusals: 0
  s2.d1 | builder | steps: 3 | writes: two.py | size: builder: tokens: 300000.0 seconds: 150.0 overruns: 0 refusals: 0
    queue docs/queue.md s2.d1
    paths: two.py
    check: uv run python -m pytest tests/test_two.py
section s3 | lead | steps: 4 | depends: s2 | size: lead: tokens: 900000.0 seconds: 600.0 overruns: 0 refusals: 0
  s3.d1 | builder | steps: 4 | writes: three.py | size: builder: tokens: 300000.0 seconds: 150.0 overruns: 0 refusals: 0
    queue docs/queue.md s3.d1
    paths: three.py
