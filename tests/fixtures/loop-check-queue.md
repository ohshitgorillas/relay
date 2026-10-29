design /tmp/relay-loop-check-fixture/docs/superpowers/specs/loop-check-fixture-design.md | order /tmp/relay-loop-check-fixture/docs/superpowers/specs/loop-check-fixture-design.md | main 1234567
section s1 | lead | steps: 1, 2 | size: lead: tokens: 900000.0 seconds: 600.0 overruns: 0 refusals: 0
  s1.d1 | builder | steps: 1 | writes: one.py | size: builder: tokens: 300000.0 seconds: 150.0 overruns: 0 refusals: 0
    queue /tmp/relay-loop-check-fixture/docs/queue.md s1.d1
    paths: one.py
    check: sh "$RELAY_CHECK_SCRIPT" first
  s1.d2 | builder | steps: 2 | writes: two.py | size: builder: tokens: 300000.0 seconds: 150.0 overruns: 0 refusals: 0
    queue /tmp/relay-loop-check-fixture/docs/queue.md s1.d2
    paths: two.py
    done-check: sh "$RELAY_CHECK_SCRIPT" second
section s2 | lead | steps: 3 | size: lead: tokens: 900000.0 seconds: 600.0 overruns: 0 refusals: 0
  s2.d1 | general-purpose | steps: 3 | writes: notes.txt | size: general-purpose: tokens: 100000.0 seconds: 60.0 overruns: 0 refusals: 0
    queue /tmp/relay-loop-check-fixture/docs/queue.md s2.d1
    paths: notes.txt
