design /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md | order /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md | main 0cb15f6
landed 1 | 0cb15f6
section s1.1.1 | lead | steps: 2 | size: lead: tokens: 929619.1 seconds: 674.6 overruns: 0 refusals: 0
  s1.1.1.d1 | test-writer | steps: 2 | writes: test_collect.py | size: test-writer: tokens: 534886.7 seconds: 159.9 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s1.1.1.d1
    red
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 2
    behavior: | History | closed nodes, Terminus | big 6 search and fact sheets; small 8 filter Finished; small 13 daily history |
    view: stubgen .pyi of collect.py
    replaces: test_collect.py::NeedsYouOnNodes::test_killed_agent_is_not_in_finished
  s1.1.1.d2 | builder | steps: 2 | writes: sources.py, views.py, collect.py | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s1.1.1.d2
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 2
    paths: sources.py, views.py, collect.py
    behavior: Node model and server: `model.py`, `views.finished`, `collect.py` writing the node-keyed board
    behavior: **`sources.py`.** Readers of the records Claude Code writes, Codex removed.
    behavior: | Reading Claude Code's own files | `sources.py` | Opening `~/.claude` paths in another module |
    behavior: | Project list and project naming | `config.load_projects`, `repos.project_of` | Basename-of-cwd naming; reading `projects.toml` |
    done-check: python3 -m unittest test_model test_collect test_repos test_sources
section s1.1.2 | lead | steps: 2 | size: lead: tokens: 929619.1 seconds: 674.6 overruns: 0 refusals: 0
  s1.1.2.d1 | test-writer | steps: 2 | writes: test_collect.py, test_model.py | size: test-writer: tokens: 534886.7 seconds: 159.9 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s1.1.2.d1
    loosened test_collect.py:243 | atomic-write test passes a write that leaves the path missing or half-written mid-write
    design-pinned test_collect.py:280 | fake transcript_tail returns only title, last_text, cost
    design-pinned test_collect.py:267 | transcript_path fake is positional `lambda r, c, sid`, rejecting the spec's keyword call
    loosened test_collect.py:302 | Needs you row checked as a subset; reason never compared with "question"
    loosened test_collect.py:308 | "no reader, parser or row shape" checks public names only
    loosened test_model.py:89 | "every field with its value" checks six values only
    design-pinned test_model.py:121 | assumes task_id equals the agentId in "a:<agentId>", a join no document states
    loosened test_collect.py:160 | Finished row shape checked only as a subset of FINISHED_KEYS
    loosened test_collect.py:241 | Needs you row shape checked only as a subset of {node, reason, line, at} (also near line 404)
    design-pinned test_model.py:128 | Finished tests pass notes without the `project` key views.finished documents
section s1.2 | lead | steps: 2 | size: lead: tokens: 929619.1 seconds: 674.6 overruns: 0 refusals: 0
  s1.2.d1 | builder | steps: 2 | writes: server.py, launchd/com.atom.workboard.web.plist, launchd/README.md | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s1.2.d1
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 2
    paths: server.py, launchd/com.atom.workboard.web.plist, launchd/README.md
    behavior: `server.py` serving `web/` and `/board.json`
    behavior: launchd web job on `server.py`
    done-check: python3 -m unittest
  s1.2.d2 | builder | steps: 2 | writes: web/core.js, web/index.html, web/style.css, web/app.js | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s1.2.d2
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 2
    paths: web/core.js, web/index.html, web/style.css, web/app.js
    behavior: `web/core.js` with `nodeRow` and the view switch
    behavior: | Page plumbing and node rendering | `web/core.js` | A view building its own node row, expand logic, fetch or timer |
    done-check: node --check web/core.js
  s1.2.d3 | builder | steps: 2 | writes: web/strip.js, web/views/now.js, web/views/history.js, web/index.html | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s1.2.d3
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 2
    paths: web/strip.js, web/views/now.js, web/views/history.js, web/index.html
    behavior: Now, History (Finished) and the Needs you strip rebuilt on it, cost and age per node
    done-check: node --check web/strip.js && node --check web/views/now.js && node --check web/views/history.js
section s2 | lead | steps: 3 | size: lead: tokens: 929619.1 seconds: 674.6 overruns: 0 refusals: 0
  s2.d1 | builder | steps: 3 | writes: events.py, hook.py, statusline.py | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s2.d1
    stub
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 3
    paths: events.py, hook.py, statusline.py
    behavior: Event store and writers: `events.py`, `hook.py`, `statusline.py`, `install/README.md`
    done-check: python3 -c 'import events, hook, statusline'
  s2.d2 | test-writer | steps: 3 | writes: test_events.py, testkit.py | size: test-writer: tokens: 534886.7 seconds: 159.9 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s2.d2
    red
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 3
    behavior: **`events.py`.** The event store: one normalized shape, one append path with `flock`, daily files under `EVENTS_DIR`, prune past `event_keep_days`, and per-session status-line snapshots.
    view: stubgen .pyi of events.py
    behavior: every reader of them treats an absent store as "no events"
    view: stubgen .pyi of events.py
    behavior: **`hook.py`.** The `workboard-hook` command for Claude Code hooks: reads the hook JSON on stdin, keeps event, session, agent, tool-use id, notification type and time, calls `events.append`, prints nothing, exits 0 on any error.
    view: stubgen .pyi of hook.py
    behavior: No prompt or tool text is stored.
    view: stubgen .pyi of hook.py
    behavior: **`statusline.py`.** The status-line command: reads the status-line JSON, calls `events.put_snapshot` with `rate_limits`, context window size and use, cost and model, prints nothing, and exits 0 on any error.
    view: stubgen .pyi of statusline.py
  s2.d3 | builder | steps: 3 | writes: events.py, hook.py, statusline.py | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s2.d3
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 3
    paths: events.py, hook.py, statusline.py
    behavior: Event store and writers: `events.py`, `hook.py`, `statusline.py`, `install/README.md`
    behavior: | New records (hooks, OTel, status line) | `events.py` under `STATE_DIR` | Any other file format or path for them; any writer but `hook.py`, `statusline.py`, `server.py` |
    done-check: python3 -m unittest
  s2.d4 | builder | steps: 3 | writes: install/README.md | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s2.d4
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 3
    paths: install/README.md
    behavior: **`install/README.md`.** The settings the owner applies to `~/.claude/settings.json`: the `hooks` entries running `hook.py`, the `statusLine` command running `statusline.py`, and the `env` block turning on telemetry with OTLP `http/json` to `http://127.0.0.1:8765` with prompt and tool-detail logging off; plus the launchd reinstall for the new server.
    behavior: No agent edits `settings.json`.
    done-check: test -s install/README.md
section s3 | lead | steps: 4 | size: lead: tokens: 929619.1 seconds: 674.6 overruns: 0 refusals: 0
  s3.d1 | builder | steps: 4 | writes: otel.py | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s3.d1
    stub
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 4
    paths: otel.py
    behavior: OTel intake: `otel.py`, `/v1/*` in `server.py`
    done-check: python3 -c 'import otel'
  s3.d2 | test-writer | steps: 4 | writes: test_otel.py | size: test-writer: tokens: 534886.7 seconds: 159.9 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s3.d2
    red
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 4
    behavior: **`otel.py`.** Pure OTLP/HTTP JSON decoding into `Event`s
    view: stubgen .pyi of otel.py
    behavior: Prompt and tool text stay redacted
    view: stubgen .pyi of otel.py
    behavior: POST /v1/logs                -> events.append for each otel.logs_to_events(body)
    view: stubgen .pyi of server.py
    behavior: POST /v1/traces              -> events.append for each otel.traces_to_events(body)
    view: stubgen .pyi of server.py
    behavior: POST /v1/metrics             -> 200, discarded
    view: stubgen .pyi of server.py
  s3.d3 | builder | steps: 4 | writes: otel.py, server.py | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s3.d3
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 4
    paths: otel.py, server.py
    behavior: OTel intake: `otel.py`, `/v1/*` in `server.py`
    behavior: | HTTP serving and OTLP intake | `server.py` | A second server or port |
    done-check: python3 -m unittest
section s4 | lead | steps: 5 | size: lead: tokens: 929619.1 seconds: 674.6 overruns: 0 refusals: 0
  s4.d1 | builder | steps: 5 | writes: state.py | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s4.d1
    stub
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 5
    paths: state.py
    behavior: **`state.py`.** The pure live-state machine.
    done-check: python3 -c 'import state'
  s4.d2 | test-writer | steps: 5 | writes: test_state.py, test_sources.py | size: test-writer: tokens: 534886.7 seconds: 159.9 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s4.d2
    red
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 5
    behavior: Hook and OTel events decide the state when present; the transcript fallback applies to sessions with no events since their start.
    view: stubgen .pyi of state.py
    behavior: `state.py` from events with transcript fallback (open `tool_use` past `approval_wait_s`)
    view: stubgen .pyi of state.py
    behavior: `needs_you` gives a reason for a node in `needs_approval` or `failed`, and for a `waiting` node whose last assistant text ends in a question; every other `waiting` node gets `None`, stays out of Needs you
    view: stubgen .pyi of state.py
    behavior: `transcript_tail` adds the last assistant `message.usage`, the model, and open `tool_use` ids with their times
    view: stubgen .pyi of sources.py
  s4.d3 | builder | steps: 5 | writes: state.py, sources.py, collect.py | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s4.d3
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 5
    paths: state.py, sources.py, collect.py
    behavior: Needs you from `state.needs_you`
    behavior: | Live state and Needs you rule | `state.py` | Status inference anywhere else, the page included |
    done-check: python3 -m unittest
  s4.d4 | builder | steps: 5 | writes: web/core.js, web/strip.js | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s4.d4
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 5
    paths: web/core.js, web/strip.js
    behavior: state dot in `nodeRow` with other `waiting` nodes yellow
    done-check: node --check web/core.js && node --check web/strip.js
section s5 | lead | steps: 6 | size: lead: tokens: 929619.1 seconds: 674.6 overruns: 0 refusals: 0
  s5.d1 | builder | steps: 6 | writes: lineage.py | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s5.d1
    stub
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 6
    paths: lineage.py
    behavior: Lineage tree: `lineage.py`, role and uptime per node, chain stages, rule flags
    done-check: python3 -c 'import lineage'
  s5.d2 | test-writer | steps: 6 | writes: test_lineage.py, test_sources.py | size: test-writer: tokens: 534886.7 seconds: 159.9 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s5.d2
    red
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 6
    behavior: **`lineage.py`.** Builds the tree: `ppid` chain of live pids to nest sessions under the session that started them, subagent meta and `parent_agent_id` for subagents, design-chain job directories for chain stages, and the owner-chat filter.
    view: stubgen .pyi of lineage.py
    behavior: Flags rule breaks from roles: a worker with worker children, a lead holding a review itself, a builder diff with no reviewer child.
    view: stubgen .pyi of lineage.py
    behavior: `live_sessions` adds `agent`, `kind`, `entrypoint`, `startedAt`, `name`
    view: stubgen .pyi of sources.py
    behavior: `subagents` adds start time from the first transcript record
    view: stubgen .pyi of sources.py
  s5.d3 | builder | steps: 6 | writes: lineage.py | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s5.d3
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 6
    paths: lineage.py
    behavior: `_ps`, `parent_command` and `owner_chat` move to `lineage.py`.
    behavior: | Lineage, `ps`, owner-chat filter, rule flags | `lineage.py` | `ppid` lookups or parent nesting elsewhere |
    done-check: python3 -m unittest test_lineage
  s5.d4 | test-writer | steps: 6 | writes: test_sources.py, test_lineage.py | size: test-writer: tokens: 534886.7 seconds: 159.9 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s5.d4
    port
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 6
    files: test_sources.py, test_lineage.py
    view: stubgen .pyi of lineage.py
    view: stubgen .pyi of sources.py
  s5.d5 | builder | steps: 6 | writes: sources.py, collect.py | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s5.d5
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 6
    paths: sources.py, collect.py
    behavior: Lineage tree: `lineage.py`, role and uptime per node, chain stages, rule flags
    behavior: `_ps`, `parent_command` and `owner_chat` move to `lineage.py`.
    done-check: python3 -m unittest
  s5.d6 | builder | steps: 6 | writes: web/views/now.js | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s5.d6
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 6
    paths: web/views/now.js
    behavior: collapsible tree in Now
    behavior: live tree with subagents and chain stages
    done-check: node --check web/views/now.js
section s6 | lead | steps: 7 | size: lead: tokens: 929619.1 seconds: 674.6 overruns: 0 refusals: 0
  s6.d1 | builder | steps: 7 | writes: budget.py, sources.py | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s6.d1
    stub
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 7
    paths: budget.py, sources.py
    behavior: Budget: `budget.py`, `sources.session_totals`
    done-check: python3 -c 'import budget, sources'
  s6.d2 | test-writer | steps: 7 | writes: test_budget.py, test_sources.py | size: test-writer: tokens: 534886.7 seconds: 159.9 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s6.d2
    red
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 7
    behavior: **`budget.py`.** Context, tokens, cost and limits.
    view: stubgen .pyi of budget.py
    behavior: Role means come from `foreman stats` through `shell.cached`.
    view: stubgen .pyi of budget.py
    behavior: burn rate and projected limit time are arithmetic over the last hour.
    view: stubgen .pyi of budget.py
    behavior: tokens in/out/cache, tool calls, compactions
    view: stubgen .pyi of sources.py
  s6.d3 | builder | steps: 7 | writes: budget.py, sources.py, collect.py | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s6.d3
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 7
    paths: budget.py, sources.py, collect.py
    behavior: Budget: `budget.py`, `sources.session_totals`
    behavior: the builder of steps 7 and 10 reads it before writing the parser and stops if no machine-readable form exists.
    behavior: | Context, tokens, cost, limits, role means | `budget.py` | Summing usage or cost elsewhere; unlabelled estimates |
    done-check: python3 -m unittest
  s6.d4 | builder | steps: 7 | writes: web/core.js, web/strip.js | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s6.d4
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 7
    paths: web/core.js, web/strip.js
    behavior: context gauge, cost and flags in `nodeRow`, header usage strip
    done-check: node --check web/core.js && node --check web/strip.js
section s7 | lead | steps: 8 | size: lead: tokens: 929619.1 seconds: 674.6 overruns: 0 refusals: 0
  s7.d1 | builder | steps: 8 | writes: repos.py | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s7.d1
    stub
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 8
    paths: repos.py
    behavior: Worktrees: `repos.worktree_board`
    done-check: python3 -c 'import repos'
  s7.d2 | test-writer | steps: 8 | writes: test_repos.py | size: test-writer: tokens: 534886.7 seconds: 159.9 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s7.d2
    red
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 8
    behavior: **`repos.py`.** All git access: commit logs, merged commits, worktrees, branch, ahead and behind, shortstat, files touched since the branch point, collisions between live worktrees, and `git merge-tree --write-tree` conflicts.
    view: stubgen .pyi of repos.py
  s7.d3 | builder | steps: 8 | writes: repos.py, collect.py | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s7.d3
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 8
    paths: repos.py, collect.py
    behavior: Worktrees: `repos.worktree_board`
    behavior: | Git | `repos.py` | `git` commands elsewhere |
    done-check: python3 -m unittest
  s7.d4 | builder | steps: 8 | writes: web/views/worktrees.js, web/views/now.js, web/index.html | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s7.d4
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 8
    paths: web/views/worktrees.js, web/views/now.js, web/index.html
    behavior: branch and shortstat in Now, Worktrees view with collisions, conflicts and heat
    done-check: node --check web/views/worktrees.js && node --check web/views/now.js
section s8 | lead | steps: 9 | size: lead: tokens: 929619.1 seconds: 674.6 overruns: 0 refusals: 0
  s8.d1 | builder | steps: 9 | writes: progress.py | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s8.d1
    stub
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 9
    paths: progress.py
    behavior: Step board: `progress.step_states`, `join_nodes`, Steps view
    done-check: python3 -c 'import progress'
  s8.d2 | test-writer | steps: 9 | writes: test_progress.py | size: test-writer: tokens: 534886.7 seconds: 159.9 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s8.d2
    red
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 9
    behavior: Plan readers as today, plus the project rows moved from `collect.py:84-123` and the step board
    view: stubgen .pyi of progress.py
    behavior: joined to nodes only on recorded ids (session `name` against queue group and step names, Foreman event fields); a step with no recorded join shows as unlinked.
    view: stubgen .pyi of progress.py
  s8.d3 | builder | steps: 9 | writes: progress.py, collect.py | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s8.d3
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 9
    paths: progress.py, collect.py
    behavior: Step board: `progress.step_states`, `join_nodes`, Steps view
    behavior: | Plan progress, step states, step joins | `progress.py` | Step matching in `collect.py`; joins guessed from brief text |
    done-check: python3 -m unittest
  s8.d4 | builder | steps: 9 | writes: web/views/steps.js, web/index.html | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s8.d4
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 9
    paths: web/views/steps.js, web/index.html
    behavior: step board columns, cards linking nodes, commit, tokens against estimate
    done-check: node --check web/views/steps.js
section s9 | lead | steps: 10 | size: lead: tokens: 929619.1 seconds: 674.6 overruns: 0 refusals: 0
  s9.d1 | builder | steps: 10 | writes: terminus.py | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s9.d1
    stub
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 10
    paths: terminus.py
    behavior: Terminus history: `terminus.py`, facts on Finished, `/api/search`
    done-check: python3 -c 'import terminus'
  s9.d2 | test-writer | steps: 10 | writes: test_terminus.py | size: test-writer: tokens: 534886.7 seconds: 159.9 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s9.d2
    red
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 10
    behavior: **`terminus.py`.** The one adapter for Terminus: `observations`, `search` and `show` through `shell`, each JSON document parsed once, observations cached by `session_key`.
    view: stubgen .pyi of terminus.py
    behavior: Terminus history: `terminus.py`, facts on Finished, `/api/search`
    view: stubgen .pyi of views.py
    behavior: GET  /api/search?q=&project= -> terminus.search(...)
    view: stubgen .pyi of server.py
  s9.d3 | builder | steps: 10 | writes: terminus.py, views.py, server.py | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s9.d3
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 10
    paths: terminus.py, views.py, server.py
    behavior: Terminus history: `terminus.py`, facts on Finished, `/api/search`
    behavior: the builder of steps 7 and 10 reads it before writing the parser and stops if no machine-readable form exists.
    behavior: | Terminus | `terminus.py` | Calling `terminus` elsewhere |
    done-check: python3 -m unittest
  s9.d4 | builder | steps: 10 | writes: web/views/history.js | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s9.d4
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 10
    paths: web/views/history.js
    behavior: History chips, text filter and search
    done-check: node --check web/views/history.js
section s10 | lead | steps: 11 | size: lead: tokens: 929619.1 seconds: 674.6 overruns: 0 refusals: 0
  s10.d1 | builder | steps: 11 | writes: transcript.py | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s10.d1
    stub
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 11
    paths: transcript.py
    behavior: Drill-down: `transcript.py`, `/api/node/<id>`
    done-check: python3 -c 'import transcript'
  s10.d2 | test-writer | steps: 11 | writes: test_transcript.py | size: test-writer: tokens: 534886.7 seconds: 159.9 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s10.d2
    red
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 11
    behavior: **`transcript.py`.** The turn model behind the drill-down: brief, turns, tool calls collapsed to one-line summaries, file edits as diffs, subagent dispatches as child references, final report, and an index of owner prompts and agent reports.
    view: stubgen .pyi of transcript.py
    behavior: It renders prose and diffs, never raw JSON.
    view: stubgen .pyi of transcript.py
    behavior: Also the per-session timeline of tool calls and subagents.
    view: stubgen .pyi of transcript.py
    behavior: GET  /api/node/<node_id>     -> transcript.reader(...) for live, terminus.show(...) for closed
    view: stubgen .pyi of server.py
  s10.d3 | builder | steps: 11 | writes: transcript.py, server.py | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s10.d3
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 11
    paths: transcript.py, server.py
    behavior: Drill-down: `transcript.py`, `/api/node/<id>`
    behavior: | Transcript turn model | `transcript.py` | Rendering transcripts in the page from raw records |
    done-check: python3 -m unittest
  s10.d4 | builder | steps: 11 | writes: web/drill.js, web/core.js, web/index.html | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s10.d4
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 11
    paths: web/drill.js, web/core.js, web/index.html
    behavior: `web/drill.js`, per-session timeline, copy resume command
    done-check: node --check web/drill.js && node --check web/core.js
section s11 | lead | steps: 12 | size: lead: tokens: 929619.1 seconds: 674.6 overruns: 0 refusals: 0
  s11.d1 | builder | steps: 12 | writes: views.py | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s11.d1
    stub
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 12
    paths: views.py
    behavior: Timeline and pulse: `views.timeline`, `views.pulse`
    done-check: python3 -c 'import views'
  s11.d2 | test-writer | steps: 12 | writes: test_views.py | size: test-writer: tokens: 534886.7 seconds: 159.9 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s11.d2
    red
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 12
    behavior: Timeline and pulse: `views.timeline`, `views.pulse`
    view: stubgen .pyi of views.py
    behavior: Timeline lanes and markers
    view: stubgen .pyi of views.py
    behavior: the per-project pulse
    view: stubgen .pyi of views.py
  s11.d3 | builder | steps: 12 | writes: views.py, collect.py | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s11.d3
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 12
    paths: views.py, collect.py
    behavior: Timeline and pulse: `views.timeline`, `views.pulse`
    behavior: | Aggregate lenses | `views.py` | Aggregation in `collect.py` or `web/` |
    done-check: python3 -m unittest
  s11.d4 | builder | steps: 12 | writes: web/views/timeline.js, web/index.html | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s11.d4
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 12
    paths: web/views/timeline.js, web/index.html
    behavior: SVG lanes, bars and markers; per-project pulse sparklines
    done-check: node --check web/views/timeline.js
section s12 | lead | steps: 13 | size: lead: tokens: 929619.1 seconds: 674.6 overruns: 0 refusals: 0
  s12.d1 | builder | steps: 13 | writes: views.py | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s12.d1
    stub
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 13
    paths: views.py
    behavior: Failures: `views.failures`, Failures view
    done-check: python3 -c 'import views'
  s12.d2 | test-writer | steps: 13 | writes: test_views.py | size: test-writer: tokens: 534886.7 seconds: 159.9 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s12.d2
    red
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 13
    behavior: Failures by role, project and kind
    view: stubgen .pyi of views.py
  s12.d3 | builder | steps: 13 | writes: views.py, collect.py | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s12.d3
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 13
    paths: views.py, collect.py
    behavior: Failures: `views.failures`, Failures view
    behavior: | Aggregate lenses | `views.py` | Aggregation in `collect.py` or `web/` |
    done-check: python3 -m unittest
  s12.d4 | builder | steps: 13 | writes: web/views/failures.js, web/index.html | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s12.d4
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 13
    paths: web/views/failures.js, web/index.html
    behavior: table by role, project and kind with sparklines
    done-check: node --check web/views/failures.js
section s13 | lead | steps: 14 | size: lead: tokens: 929619.1 seconds: 674.6 overruns: 0 refusals: 0
  s13.d1 | builder | steps: 14 | writes: history.py | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s13.d1
    stub
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 14
    paths: history.py
    behavior: Daily history: `history.py`, day-change append in `collect.py`, trends in History
    done-check: python3 -c 'import history'
  s13.d2 | test-writer | steps: 14 | writes: test_history.py | size: test-writer: tokens: 534886.7 seconds: 159.9 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s13.d2
    red
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 14
    behavior: **`history.py`.** The daily history file: one line per day and project (cost, finished, failures, tokens by role), appended once per day by `collect.py`, read back for trends past Claude's 30-day cleanup.
    view: stubgen .pyi of history.py
    behavior: idempotent per day
    view: stubgen .pyi of history.py
  s13.d3 | builder | steps: 14 | writes: history.py, collect.py, model.py | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s13.d3
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 14
    paths: history.py, collect.py, model.py
    behavior: Daily history: `history.py`, day-change append in `collect.py`, trends in History
    behavior: | Persistent history | `history.py` | Other files written under `STATE_DIR` |
    done-check: python3 -m unittest
  s13.d4 | builder | steps: 14 | writes: web/views/history.js | size: builder: tokens: 338231.3 seconds: 194.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/workboard-features-roster/docs/queue.md s13.d4
    design: /Users/atom/dev/workboard-features-roster/docs/superpowers/specs/workboard-features-design.md, Order step 14
    paths: web/views/history.js
    behavior: daily trends
    done-check: node --check web/views/history.js
