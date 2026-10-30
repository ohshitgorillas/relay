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
  s2.d1 | test-writer | steps: 4 | writes: tests/test_prompts.py, tests/test_progress.py | size: test-writer: tokens: 621972.3 seconds: 196.4 overruns: 0 refusals: 0
    queue docs/research-reuse-queue.md s2.d1
    red
    design: docs/superpowers/specs/relay-research-reuse-design.md, Order step 4
    behavior: Section body, research.block(kept), the changed paths sorted, and the order to map only the code
    view: stubgen .pyi of relay/prompts.py
    behavior: in those paths that the section touches. It may name new paths, but no entry may name a file a kept
    view: stubgen .pyi of relay/prompts.py
    behavior: entry names. Gives the room left under the caps after kept, the MAP form and the flag rule.
    view: stubgen .pyi of relay/prompts.py
    behavior: `research_brief` and `refresh_brief` share one private helper for the MAP form text and the flag rule. That text is not written twice.
    view: stubgen .pyi of relay/prompts.py
    behavior: A brief never carries a digest.
    view: stubgen .pyi of relay/prompts.py
    behavior: red: refresh brief and progress line
    view: stubgen .pyi of relay/progress.py
    behavior: `map_reused`, `research_started` and `research_finished` keep their wording.
    view: stubgen .pyi of relay/progress.py
  s2.d2 | builder | steps: 5 | writes: relay/prompts.py, relay/progress.py | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/research-reuse-queue.md s2.d2
    design: docs/superpowers/specs/relay-research-reuse-design.md
    step: 5
    paths: relay/prompts.py, relay/progress.py
    check: uv run pytest tests/test_prompts.py tests/test_progress.py
section s3 | lead | steps: 6, 7, 8 | size: lead: tokens: 1395004.9 seconds: 743.7 overruns: 0 refusals: 0
  s3.d1 | test-writer | steps: 6 | writes: tests/test_loop.py, tests/fixtures/ | size: test-writer: tokens: 621972.3 seconds: 196.4 overruns: 0 refusals: 0
    queue docs/research-reuse-queue.md s3.d1
    red
    design: docs/superpowers/specs/relay-research-reuse-design.md, Order step 6
    behavior: A fresh lead after RETIRED reuses the map when no mapped file changed.
    view: stubgen .pyi of relay/loop.py
    behavior: A map drawn in the main checkout is reused in the new `lead/<sid>` worktree when the mapped files match.
    view: stubgen .pyi of relay/loop.py
    behavior: A changed mapped file, including an uncommitted or untracked one, gets a refresh run that covers only the changed files, and the lead gets the merged map.
    view: stubgen .pyi of relay/loop.py
    behavior: A failed or invalid refresh leaves the lead without a map and keeps the saved file for the next pass.
    view: stubgen .pyi of relay/loop.py
    behavior: A stale file on disk is never used, because `changed` runs on every load.
    view: stubgen .pyi of relay/loop.py
    behavior: `tests/test_loop.py:3895-3933` is rewritten to expect a refresh.
    view: stubgen .pyi of relay/loop.py
  s3.d2 | builder | steps: 7 | writes: relay/loop.py | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/research-reuse-queue.md s3.d2
    design: docs/superpowers/specs/relay-research-reuse-design.md
    step: 7
    paths: relay/loop.py
    check: uv run pytest tests/test_loop.py
