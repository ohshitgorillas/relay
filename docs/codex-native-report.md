# Codex-native grounding and evidence

## Grounding

Read date: 2026-10-29. Checkout: `codex-native`. This section records the
read-only inventory in dispatch `s1.d1`; it does not certify hook exclusion.
The initial working tree was clean. No model run, background process, hook
invocation, credential read, or owner-configuration edit was performed.

### Translated hook inventory

Sources: the owner's `~/.codex/hooks.json` and
`~/.codex/hooks/claude_adapter.py`, read on the date above. Paths in the table
are source identifiers, not files modified by Relay. A missing matcher means
all tools/events of that event type. Legacy entries without `--scope` default
to the adapter's `hooks/legacy-scope` file when present, otherwise
`~/dev/gauntlet`; scoped entries also recognize sibling git worktrees through
their common git directory. The legacy-scope file itself was not read.

| Event | Matcher | Invoked source | Verified behavior and proposed native outcome |
|---|---|---|---|
| SessionStart | absent | adapter → `/bin/cat`, argument `~/dev/gauntlet/CLAUDE.md` | Supplies instruction text; dropped session hook, with instruction delivery requiring separate verification. |
| UserPromptSubmit, PreToolUse, PostToolUse | absent | adapter → `/usr/bin/true` | Adapter records translated history; child itself succeeds without enforcement. Dropped bridge bookkeeping. |
| PreToolUse | `^(exec_command\|shell_command\|shell\|Bash)$` | adapter → `~/.codex/hooks/codex-change-budget.py` | Transcript-dependent change/edit budgets and non-temporary `rm` handling; **native rule required, no equivalent found: DESIGN**. |
| SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, PermissionRequest, SessionEnd, Stop, SubagentStop | absent | adapter → `~/.config/iterm2/cc-status`, scope `*` | Source command identified; child behavior unverified. Proposed dropped notification hook, conditional on source confirmation. |
| PreToolUse | `Bash` | adapter → `~/.claude/hooks/no-foreground-tests.py`, scope `*` | Denies foreground test/check/lint command positions, exempting worker/lead identity and background execution. Native asynchronous execution helps but is not an equivalent command-policy proof; native rule outcome unresolved. |
| PreToolUse | `Agent\|Task` | adapter → `~/.claude/hooks/no-foreground-agents.py`, scope `*` | Denies explicit `run_in_background=false`, accepts omitted field. Native Codex agents are asynchronous; native runtime behavior supplies the intended asynchronous outcome, subject to shakedown verification. |
| PreToolUse | `Bash` | adapter → `~/.claude/hooks/gauntlet-change-budget.py`, scope `~/dev/gauntlet` | Counts changes/edits since genuine user reply; **native rule required, no equivalent found: DESIGN**. |
| PostToolUse | `^(apply_patch\|Write\|Edit)$` | adapter → `~/.claude/hooks/gauntlet-doc-budget.py --hook`, legacy scope | Enforces byte/block caps and optional hygiene on governed documents after edits; **native rule required, no equivalent found: DESIGN**. |
| PostToolUse | `Write\|Edit` | adapter → same `gauntlet-doc-budget.py --hook`, scope `*` | Same content policy in a separate configured entry; **DESIGN**, not dropped. |
| PostToolUse | absent | adapter → `~/.claude/hooks/context-watch`, scope `*` | Reminders at 100k/150k context, once per level and session/agent; always succeeds. Dropped lifecycle reminder under the approved design. |

The hook file also contains three non-adapter entries; excluding all hooks
would exclude these too:

| Event | Matcher | Invoked source | Outcome |
|---|---|---|---|
| SessionStart, SubagentStart | absent | `~/.codex/sync-claude.py --rules-hook` | Instruction synchronization command identified; behavior unverified. Dropping requires confirmation that native instruction delivery retains the owner rules. |
| PreToolUse | `^(?:(?:functions\.)?collaboration[._]*)?(?:list_agents\|wait_agent)$` | `~/.codex/hooks/agent-wait-policy.py` | Denies `list_agents`; rewrites `wait_agent` timeout to 3600000. V2 wait-timeout config exists, but does not alone prove list-agent denial or equivalent V1 enforcement; native outcome unresolved. |

The adapter itself translates shell calls, patch operations and JavaScript
exec-cell tools into Claude-shaped calls. It can reject unsupported/opaque
inputs, including some computed JavaScript calls and interactive stdin. That
is a translation limitation, not evidence that the underlying owner policy
can be dropped. Child nonzero exits become denials; adapter exceptions deny
pre-tool requests but produce system messages for several lifecycle/post-tool
events. Transcript-dependent scripts use reconstructed history.

The lead supplied read-only hook evidence, preserving this builder's source
read boundary: `no-foreground-tests.py:69-88`,
`no-foreground-agents.py:18-26`, `gauntlet-change-budget.py:7-24`,
`command-burst-guard.py:68-70,394-428`, `codex-change-budget.py:12-67`,
`gauntlet-doc-budget.py:15-30,44-53,83-111,121-131`,
`context-watch:12,51-101`, and `agent-wait-policy.py:9-41`.
These anchors are supplied evidence, not claims of direct builder reads.

The command-burst guard counts since a genuine user reply, rejecting a
pending call above its limits. Host defaults are 10 changes, 30 in-tree
edits and 10 out-of-tree edits. The Gauntlet variant raises ordinary limits
to 25 changes/60 edits while retaining host limits for
`sudo/docker/podman/systemctl/rm`; a lone `ping-me` is free. The Codex variant
raises ordinary limits to 75/180/30 unless non-temporary `rm` is detected,
and exempts read-only waits/views while metering spawning and messaging.
The document hook governs named Gauntlet documents and two
`~/dev/gauntlet-harness-*` files, excluding `docs/queue.md` and
`.claude/worktrees` paths, and exits 2 for post-edit findings.

Filesystem/network sandboxing cannot implement these history-sensitive
counters or post-edit content checks. The inspected native prefix-rule
surface matches command prefixes, with no transcript counter or document
byte/block predicate. No equivalent installed native configuration interface
was established. Dropping those owner-rule hooks would lose enforcement.
Notification-source internals and synchronized instruction equivalence
remain unverified; neither uncertainty cancels the confirmed policy gap.

### Installed CLI surface

`codex --version` returned `codex-cli 0.165.0`.
`/opt/homebrew/bin/codex` resolves through the Homebrew cask at
`/opt/homebrew/Caskroom/codex/0.165.0/bin/codex`.

`codex exec --help` advertises `resume`, `fork` and `review`; dotted TOML
overrides via `-c/--config`; `--enable/--disable`; `--strict-config`;
`--model`; `--profile`; `--sandbox` with `read-only`, `workspace-write` and
`danger-full-access`; `--add-dir`; `--cd`; `--json`; `--output-last-message`;
`--skip-git-repo-check`; and `--ephemeral`. It also advertises
`--ignore-user-config`, `--ignore-rules`, and
`--dangerously-bypass-hook-trust`. The latter runs enabled hooks without
persisted trust and does not exclude them. The bypass-sandbox flag exists
but is outside the approved launch design. Top-level help exposes
`--ask-for-approval` with `on-request` and `never`; config overrides can
deliver approval policy to `exec`.

No standalone installed config-schema artifact was found in the cask's file
inventory. The [official config schema](https://developers.openai.com/codex/config-schema.json)
was fetched on the read date; it is a current web schema, **not a proven
version-pinned schema for this installed binary**. Its relevant surface is:

| Concern | Keys/types in official schema |
|---|---|
| Sandbox | `sandbox_mode`: `read-only`, `workspace-write`, `danger-full-access`; `sandbox_workspace_write.network_access`: boolean, default false; `.writable_roots`: absolute-path array; `.exclude_slash_tmp`, `.exclude_tmpdir_env_var`: booleans, default false. |
| Approval | `approval_policy`: `on-request`, `never`, or a granular policy object; the design selects `never`. |
| Native roles | `agents.<name>.config_file`: role config path; `.description`: string; `.nickname_candidates`: string array. `agents.enabled`, `.max_depth`, `.max_concurrent_threads_per_session`, `.default_subagent_model`, `.default_subagent_reasoning_effort` also exist. |
| Role contents | Role config layers can carry `developer_instructions`, `model`, `model_reasoning_effort`, sandbox, approval and feature configuration. Native delivery uses role config files, not `--agent`. |
| Exec cells | `features.code_mode`: boolean or configuration object with `enabled`, namespace exclusions/direct-only lists and exec yield settings; `features.code_mode_host`: boolean or configuration object. This differs from removed `js_repl` flags. |
| Hooks | `features.hooks`: boolean; inline `[hooks]` event tables plus `[hooks.state]` enablement/trust records. |
| Exec policy | Native `.rules` files hold `prefix_rule(pattern, decision, justification, match, not_match)`; this is a separate policy language, not an arbitrary transcript-policy callback. |

Installed `codex features list` independently reported `hooks` stable/true,
`multi_agent` stable/true, `multi_agent_v2` stable/false,
`code_mode` under-development/false, `code_mode_host` stable/true,
`code_mode_only` under-development/false, `js_repl` removed/false,
`unified_exec` stable/true, and `shell_tool` stable/true.

A model-free installed-binary validation using `codex --strict-config`, the
keys `sandbox_mode="workspace-write"`, `approval_policy="never"`,
`sandbox_workspace_write.network_access=false`,
`sandbox_workspace_write.writable_roots=[]`,
`agents.probe.description="probe"`, `features.code_mode=true` and
`features.hooks=true`, followed by `app-server --print-startup-config`,
exited 0 with empty stderr. This proves those keys are accepted, not that
every requested role field or runtime behavior is enforced.

### Hook layers and exclusion candidates

[Official hook documentation](https://developers.openai.com/codex/hooks)
says hooks are discovered next to active config layers, from `hooks.json`
and inline TOML; sources merge instead of replacing lower layers. Enabled
plugins can supply manifest/default `hooks/hooks.json` hooks. Managed hooks
can come from system, MDM, cloud or requirements sources and cannot be
disabled in the user hook browser.

| Layer | Source/lifetime | Exclusion evidence |
|---|---|---|
| User | `$CODEX_HOME/hooks.json` and inline user config | Candidate `-c features.hooks=false` / `--disable hooks`; no runtime proof in this dispatch. `--ignore-user-config` promises only to omit user config TOML, not every hook source. |
| Project cwd and ancestors | Trusted `.codex/` config layers from project root through cwd; inline hooks and adjacent hook JSON | Same global candidate; no per-layer runtime proof. Project distrust skips local layers but is not the approved exclusion mechanism. |
| Profile | `$CODEX_HOME/<name>.config.toml` when selected | Hooks follow active layers; omit profiles where possible and prove global exclusion. |
| System | `/etc/codex/config.toml` and hooks next to active system layers | Same candidate, unproven. No dedicated exclude-system-hooks option in `exec --help`. |
| Managed | MDM, cloud configuration and requirements-delivered policy | Same candidate, unproven; managed policy can constrain settings. No help-listed override guarantees bypass of requirements. |
| Plugin | Enabled plugin lifecycle declarations/default hook files | Same candidate, unproven; plugin hook flag is removed on this version. |

The [configuration precedence documentation](https://developers.openai.com/codex/config-basic)
places CLI overrides above ordinary project/profile/user/cloud/system
defaults while requirements constrain behavior. The
[exec-policy documentation](https://developers.openai.com/codex/rules)
describes prefix-based command rules loaded from active config-layer `rules/`
directories. Prefix rules are not evidence of transcript-sensitive budgets,
agent wait policy, or document-size enforcement. `--ignore-rules` excludes
user/project execpolicy files; it does not exclude hooks.

No `PROVEN` entry is justified yet. Scratch/home runtime exclusion and rollout
field/resume evidence belong to the remaining Grounding dispatch, not this
read-only inventory. No exclusion attempt or model spend occurred here.

### Model inventory and rates

The owner's `~/.codex/agents/*.toml` model fields were read without printing
their instruction bodies. `architect`, `divvyer` and `role-author` select
`gpt-6-astra`; `builder`, `core-builder`, `diff-reviewer`, `gatesmith`,
`juror`, `lead`, `mutant-hunter`, `reader`, `seamstress`, `spiker`,
`test-reviewer` and `test-writer` select `gpt-6.1-sol`.
`researcher.toml` has **no model field**. The approved `roles.load` contract
requires one, so that file cannot satisfy it without an explicit model.
No model is silently assigned here. The shakedown's generated role files do
not exist yet; the rates below cover the two explicit owner-role models,
and any additional shakedown model will require a priced entry.

Rates fetched from the [official API pricing page](https://developers.openai.com/api/docs/pricing)
on **2026-10-29**, in USD per one million tokens:

| Model | Standard input | Standard cached input | Standard output |
|---|---:|---:|---:|
| `gpt-6-astra` | 10.00 | 1.00 | 50.00 |
| `gpt-6.1-sol` | 2.00 | 0.10 | 10.00 |

The source labels its table columns input/output/cached input; the table
above reorders them to the design's `Rate` field order. These are standard
API-equivalent rates, not subscription billing or Batch/Fast/Ultrafast rates.
The pricing page separately lists cache-write prices; the approved design
prices cached input rather than cache creation. This inventory makes no
claim that a particular run used the standard service tier.

DESIGN: Owner-rule change/edit budgets and document-content caps have no
equivalent in the inspected native sandbox, config and exec-policy surfaces.
The launch design must retain their enforcement through an approved native
mechanism before excluding these hooks. Hook exclusion is not proven here;
no `PROVEN` entry or real-model exclusion run is claimed.
