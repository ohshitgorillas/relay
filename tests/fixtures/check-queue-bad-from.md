design /tmp/relay-check-fixture/docs/superpowers/specs/check-fixture-design.md | order /tmp/relay-check-fixture/docs/superpowers/specs/check-fixture-design.md | main 1234567
section s1 | lead | steps: 1 | size: lead: tokens: 900000.0 seconds: 600.0 overruns: 0 refusals: 0
  s1.d1 | builder | steps: 1 | writes: one.py | size: builder: tokens: 300000.0 seconds: 150.0 overruns: 0 refusals: 0
    queue /tmp/relay-check-fixture/docs/queue.md s1.d1
    check: true
section s2a | lead | steps: 2 | from: not an id! | size: lead: tokens: 900000.0 seconds: 600.0 overruns: 0 refusals: 0
  s2a.d1 | builder | steps: 2 | writes: two.py | size: builder: tokens: 300000.0 seconds: 150.0 overruns: 0 refusals: 0
    queue /tmp/relay-check-fixture/docs/queue.md s2a.d1
    check: true
