design docs/superpowers/specs/relay-research-reuse-design.md | order docs/superpowers/specs/relay-research-reuse-design.md | main db259df
section s1 | lead | steps: 1, 2, 3 | size: lead: tokens: 1395004.9 seconds: 743.7 overruns: 0 refusals: 0
  s1.d1 | builder | steps: 1 | writes: relay/research.py, relay/prompts.py, relay/progress.py | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/research-reuse-queue.md s1.d1
    stub
    design: docs/superpowers/specs/relay-research-reuse-design.md
    step: 1
    paths: relay/research.py, relay/prompts.py, relay/progress.py
    check: uv run python -c 'import relay.research, relay.prompts, relay.progress'
  s1.d2 | test-writer | steps: 2 | writes: tests/test_research.py, tests/test_git.py | size: test-writer: tokens: 621972.3 seconds: 196.4 overruns: 0 refusals: 0
    queue docs/research-reuse-queue.md s1.d2
    resume 01a18a51-9ebf-70f0-83dd-afc27a34b757
    red
    design: docs/superpowers/specs/relay-research-reuse-design.md, Order step 2
    behavior: A map file records a digest of every file it names.
    view: stubgen .pyi of relay/research.py
    behavior: Freshness is decided file by file from those digests, with no commit and no git.
    view: stubgen .pyi of relay/research.py
    behavior: A stale map is split into the part that still holds and the files that changed, and a refresh is merged back into it.
    view: stubgen .pyi of relay/research.py
    behavior: `save` writes the header line, then one `file <digest> <path>` line for each file, then the body.
    view: stubgen .pyi of relay/research.py
    behavior: A file saved before this change has no `file` lines, so it loads with `digests=()`, and `changed` reports every file, which means one full remap.
    view: stubgen .pyi of relay/research.py
    behavior: A `file` line that does not parse, or whose path set differs from the body's `files`, makes `load` return None.
    view: stubgen .pyi of relay/research.py
    behavior: Covers per-file freshness, unknown and missing files, files changed during a run, an old map file without `file` lines, and merge rules and caps.
    view: stubgen .pyi of relay/research.py
    behavior: `stale` is removed.
    view: stubgen .pyi of relay/research.py
    behavior: `changed` (`relay/git.py:50-55`) is removed, because no caller is left. Nothing is added.
    view: stubgen .pyi of relay/git.py
  s1.d3 | builder | steps: 3 | writes: relay/research.py, relay/git.py, relay/loop.py | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/research-reuse-queue.md s1.d3
    design: docs/superpowers/specs/relay-research-reuse-design.md
    step: 3
    paths: relay/research.py, relay/git.py, relay/loop.py
    check: uv run pytest tests/test_research.py tests/test_git.py
section s2 | lead | steps: 4, 5 | size: lead: tokens: 1395004.9 seconds: 743.7 overruns: 0 refusals: 0
  s2.d1 | test-writer | steps: 4 | writes: tests/test_prompts.py | size: test-writer: tokens: 621972.3 seconds: 196.4 overruns: 0 refusals: 0
    queue docs/research-reuse-queue.md s2.d1
    resume 01a18a46-4452-77c3-9881-6ea9fac95d01
    moved
    lines: docs/superpowers/specs/relay-research-reuse-design.md:85 | before: "" | after: "`refresh_brief` emits these exact sentences as its stable scope instruction contract:"
    lines: docs/superpowers/specs/relay-research-reuse-design.md:88 | before: "" | after: "Map only code in the changed paths that this section touches."
    lines: docs/superpowers/specs/relay-research-reuse-design.md:89 | before: "" | after: "You may name new paths."
    lines: docs/superpowers/specs/relay-research-reuse-design.md:90 | before: "" | after: "No entry may name a file that a kept entry names."
    files: tests/test_prompts.py
    view: stubgen .pyi of relay/prompts.py
    view: stubgen .pyi of relay/research.py
    view: stubgen .pyi of relay/config.py
    view: stubgen .pyi of relay/queue.py
    check: uv run pytest tests/test_prompts.py
  s2.d2 | builder | steps: 5 | writes: relay/prompts.py, relay/progress.py | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/research-reuse-queue.md s2.d2
    design: docs/superpowers/specs/relay-research-reuse-design.md
    step: 5
    paths: relay/prompts.py, relay/progress.py
    check: uv run pytest tests/test_prompts.py tests/test_progress.py
section s3 | lead | steps: 6, 7, 8 | size: calibration: verify retained worker results, complete the two pending reviews and the full suite, then commit; lead: tokens: 1395004.9 seconds: 743.7 overruns: 0 refusals: 0
  queue docs/research-reuse-queue.md s3
  resume 01a18a88-c54a-7cd1-bd02-46991e870a53
  check: uv run pytest tests/test_loop.py
  check: uv run pytest
  s3.d4 | test-reviewer | steps: 6 | writes: none | size: calibration: resume the retained whole-diff review; 872 reported unread lines of tests/test_loop.py plus remaining referenced helpers and documentation, then the formal findings report; test-reviewer: tokens: 200474.9 seconds: 67.5 overruns: 0 refusals: 0
    queue docs/research-reuse-queue.md s3.d4
    resume 01a18aa1-140e-7793-85dd-a85ffe2dd24b
    working tree
    spec: docs/superpowers/specs/relay-research-reuse-design.md
  s3.d5 | diff-reviewer | steps: 7 | writes: none | size: diff-reviewer: tokens: 169598.3 seconds: 49.3 overruns: 0 refusals: 0
    queue docs/research-reuse-queue.md s3.d5
    working tree
