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

### Expanded policy grounding: partial dispatch s1.d1

The following evidence was supplied by the coordinator through the lead on
2026-10-29. This builder did not open `~/.codex` or `~/.claude`; those source
anchors identify supplied evidence, not direct builder reads. This supplements
the earlier inventory without completing the expanded Grounding scope.

**Adapter arguments and scope.** `~/.codex/hooks/claude_adapter.py:796-803`
requires `--script`, accepts integer `--script-timeout` (default 20), repeated
`--python-arg` and `--script-arg`, `--scope` (default `ROOT`), and
`--sync-source`. The script target and its arguments are therefore separate
options; a positional target-and-arguments form is not established. Lines
21-23 select `hooks/legacy-scope` when present, otherwise `~/dev/gauntlet`.
The coordinator found the legacy-scope file absent, so it has no contents to
record and the fallback applies. Lines 662-674 cover scope `*`, a cwd under
the resolved scope, or a cwd sharing the scope's git common directory.

**Change and edit budgets.** Limits below are changes / in-tree edits /
out-of-tree edits, applied to the pending call once; denial is strictly above
the limit (`~/.claude/hooks/command-burst-guard.py:394-428`).

| Source and anchors | Ordinary limits | Host limits and selection |
|---|---|---|
| `command-burst-guard.py:68-79` | 10 / 30 / 10 | Default host limits. |
| `~/.claude/hooks/gauntlet-change-budget.py:12-24` | 25 / 60 / 10 | 10 / 30 / 10 for `sudo`, `docker`, `podman`, `systemctl`, or `rm`. A lone `ping-me` is free. |
| `~/.codex/hooks/codex-change-budget.py:12-67` | 75 / 180 / 30 | 10 / 30 / 10 for `sudo`, `docker`, `podman`, `systemctl`, or host `rm`. Free calls include `sleep`, `wait_agent`, `wait`, `list_agents`, `view_image`, and a lone unchained `ping-me`. |

The Codex host-`rm` detector recurses through shell heads `sh`, `bash`, and
`zsh` with `-c`. Temporary removal must normalize under `/tmp/` or
`/private/tmp/`; arguments containing `$`, backticks, or braces do not qualify
as temporary (`codex-change-budget.py:12-50`). These are the supplied scratch
roots; no additional `$TMPDIR` exemption was established.

The common classifier treats `Read`, `Grep`, `Glob`, `WebFetch`, and
`WebSearch` as free; takes `Write`/`Edit` paths from `file_path` and
`NotebookEdit` paths from `notebook_path`; and exempts exact Agent types
`Explore`, `Plan`, and `caveman:cavecrew-investigator`
(`command-burst-guard.py:68-79`). Root selection is `CLAUDE_PROJECT_DIR`,
otherwise cwd. An in-tree edit must be under that root and git-restorable;
ignored paths or git failures count outside (`:225-290`). Unknown calls are
changes; a Bash call is free only when sibling `free_bash.py` says so
(`:108-115,293-307`). **The sibling classifier was not read.** Exact Bash
change/edit classes and all free-command cases remain unverified.

**Foreground execution.** `~/.claude/hooks/no-foreground-tests.py:69-89`
exempts any truthy `agent_id` or `agent_type`, rather than a named-agent
allowlist, and exempts `run_in_background=true`. Lines 13-66 identify command
positions, wrappers, and test/check/lint commands after stripping data-only
quotes and heredocs. The supplied evidence does not enumerate those command
classes and wrappers, so their exact native equivalents remain unverified.
The truthy-identity rule must not be replaced silently by a finite `EXEMPT`
name set when the native policy is designed.

**Governed documents.** `~/.claude/hooks/gauntlet-doc-budget.py:19-31`
supplies the following caps. The block cap is characters per block, not a
count of blocks. Hygiene is a separate enabled check.

| Governed path | UTF-8 byte cap | Block character cap | Hygiene |
|---|---:|---:|---|
| `CLAUDE.md` | 4000 | 600 | yes |
| `.claude/agents/*.md` | 16000 | 1500 | yes |
| `.gauntlet/jobs/HANDOFF.md` | 6000 | 600 | yes |
| `.gauntlet/jobs/queue.md` | 5000 | 300 | yes |
| `.gauntlet/jobs/rulings.md` | 3000 | 600 | yes |
| `docs/*.md`, `docs/superpowers/specs/*.md` | 40000 | 2000 | no |
| `~/dev/gauntlet-harness-rules.md` | 12000 | 600 | yes |
| `~/dev/gauntlet-harness-plan.md` | 16000 | 600 | yes |

The coordinator confirmed the exact queue/rulings path prefixes at
`~/.claude/hooks/gauntlet-doc-budget.py:23-24`. Frontmatter descriptions
have a 600-character cap. The hook excludes
`docs/queue.md` and paths containing `/.claude/worktrees/` (`:44-53`). Fenced
blocks are ignored; headings and blank lines delimit paragraphs; each list
item or table row is a block (`:56-80`). Byte checks use UTF-8, frontmatter is
skipped for block checks, and hygiene patterns apply where enabled
(`:83-111`). **The exact hygiene patterns remain unverified.** Hook mode
uses `tool_input.file_path`, checks existing governed files, writes findings
to stderr, and exits 2 (`:121-131`).

**Instruction synchronization.** `~/.codex/sync-claude.py:576-600` shows
`--rules-hook` reading stdin/cwd, finding the git root, and walking ancestor
to descendant directories. It injects existing `CLAUDE.md` text where native
discovery misses it: outside the native root or alongside `AGENTS.md` or its
override. It prints `hookSpecificOutput.additionalContext` and returns
without writes. Its native instruction delivery is therefore separate from
the adapter's SessionStart `cat`; runtime delivery is still unproven.

**Status command.** Direct `file` and symlink inspection found
`~/.config/iterm2/cc-status` points to
`/Applications/iTerm.app/Contents/Resources/utilities/cc-status`, a Mach-O
universal executable for x86_64 and arm64. It was not executed. No source or
behavior evidence was supplied, so the behavior of `cc-status` remains
unverified and its proposed notification-only outcome is not certified.

Dispatch s1.d1 remains incomplete: exact Bash classifiers, foreground
test/check/lint command classes and wrappers, hygiene patterns, and
`cc-status` behavior still need evidence. No feasibility probe, model run,
hook invocation, configuration edit, or background process was performed in
this dispatch. F1-F9 and rollout/resume evidence remain for later Grounding
dispatches. No `HookSurface` or `PROVEN` entry is justified by this supplement.

### Policy grounding completion: s1.d1a

**Provenance and historical limits.** The coordinator directly read the
sources below on 2026-10-29 and supplied their contents through the lead.
This builder did not read, import, or execute those hook sources. Source
anchors below refer to that supplied evidence. The preceding partial s1.d1
section remains a historical record: its statements that the sibling Bash
classifier, foreground command classes, and exact hygiene patterns were
unverified are superseded by this section. Its existing budget, scope,
scratch-root, and document-cap tables still apply. This completes the policy
part of that dispatch; `cc-status` belongs to separate dispatch s1.d1b.
Native runtime feasibility and rollout/resume proof remain separate work.

**Budget classifier and counters.** The earlier limits remain changes /
in-tree edits / out-of-tree edits: common defaults 10/30/10, Gauntlet
ordinary 25/60/10, Codex ordinary 75/180/30, and host limits 10/30/10.
The Gauntlet host set includes every `rm`; the Codex variant distinguishes
host removal from removal normalized under `/tmp/` or `/private/tmp/`.
Those roots are removal exemptions, distinct from the narrower scratch
output-redirection rule below. The earlier budget source anchors and
genuine-user-reply reset boundary still apply.

The common Bash classifier is binary: FREE when `is_free_bash` succeeds,
otherwise CHANGE. A Bash mutation never increments structured edit counts,
even when it changes an in-tree file. `Write`, `Edit`, and `NotebookEdit`
use the separate path classifier already recorded above
(`~/.claude/hooks/command-burst-guard.py:293-307`). Thus a shell edit must
not be converted into an in-tree structured edit merely from its target.

**Bash normalization and composition.** All anchors in the following Bash
inventory refer to `~/.claude/hooks/free_bash.py`.

- `:196-205` unwraps only the DOTALL form
  `^\s*bwrap\s.*?\s--\s+(?:bash|sh)\s+-s\s+<<'([A-Za-z_]\w*)'\n(.*)\n\1[ \t]*$`.
- `:557-590` replaces only `$(pwd)` and
  `$(git rev-parse --show-toplevel)` with `/SAFESUBST`, strips heredoc bodies,
  masks quoted interiors, then rejects unquoted backticks, `$(`, `<(`,
  `>(`, `||`, `--fix`, `--write`, `--in-place`, and `--output`.
  Every segment split at `&&` or semicolon and every stage split at pipe
  must be free. Newline is not a segment separator in this classifier.
  Empty commands, separator-only commands, and parse exceptions are metered.
- `:135-181` masks single/double quote interiors while preserving length;
  unbalanced quoting fails. Heredoc stripping supports `<<` and `<<-`, an
  optionally quoted `[A-Za-z_]\w*` delimiter, recursive stripping, and
  drops the remaining tail when a heredoc is unterminated.
- `:250-310` removes initial assignments, repeated `nice`, `ionice`, and
  `timeout` wrappers, assignments again, one `uv run`, `poetry run`, or
  `npx` prefix, then `python[0-9.]* -m`. `nice` accepts `-n` or
  `--adjustment` plus a value, or `^-(-adjustment=)?-?\d+$`.
  `ionice` remains unstripped when any remaining token equals or starts
  `-p`, or starts `--pid`; otherwise `-c`, `-n`, `--class`, and
  `--classdata` consume a value and other flags consume only themselves.
  `timeout` consumes option values for `-k`, `--kill-after`, `-s`, and
  `--signal`, then a duration; a missing duration leaves it unstripped.
- `:124-132,313-334` rejects lone background `&`. Output operators
  `(\d*)(&>>|&>|>>|>&|>)` require exact `/dev/null` or a target with no
  `..` substring matching `/tmp/claude[^/]*/.+/scratchpad(?:/|$)`.
  There is no `/private/tmp` exemption for output. `>&` followed by digits
  or `-` permits fd duplication/closure. Accepted redirections are removed
  before `shlex.split(comments=False, posix=True)`; empty/unparseable stages
  fail and assignment-only stages are free (`:407-470`). Command matching
  uses the basename, so a directory prefix does not change the class.

**Bash free classes.** The fixed sets come from `free_bash.py:24-104`;
dispatch and operand restrictions come from `:337-554`. These are the
classifier's syntactic permissions, not claims that each permitted command
is semantically read-only for all possible operands.

| Position | Command class | Exact restriction or set |
|---|---|---|
| Head or downstream | Readers | `grep, egrep, fgrep, rg, ls, cat, head, tail, wc, stat, file, diff, comm, cut, uniq, nl, column, tr, fold, rev, tac, less, more, jq, which, whereis, echo, printf, sha256sum, md5sum, b2sum, cksum, uptime, ps, nproc, pwd, du, df, free, basename, dirname, realpath` |
| Head or downstream | `sed` | Requires `--quiet`, `--silent`, or `n` anywhere in a short option; rejects `--in-place` prefix or `i` anywhere in a short option. |
| Head or downstream | `date`, `find`, `sort` | `date` rejects args exact/starting `-s` or `--set`; `find` rejects exact `-exec,-execdir,-delete,-ok,-okdir,-fprint,-fprint0,-fprintf,-fls`; `sort` rejects `-o`/`--output` prefixes. |
| Head or downstream | `rpm` | Requires `-q` prefix or `--query`; rejects exact `-i,-U,-F,-e,--install,--upgrade,--freshen,--erase,--import,--rebuilddb,--setperms,--setugids`. |
| Head or downstream | `command`, `pip`, `pip3` | `command` requires `-v` or `-V`; pip's first non-option must be `list,show,freeze,check,inspect`. |
| Head or downstream | `curl` (`:337-367`) | Rejects short prefixes `-d,-F,-T,-o,-O` and long prefixes `--data,--form,--upload,--output,--remote-name`. `-X`/`--request` plus value or concatenated `-X` permits only GET/HEAD, case-insensitive. Requires at least one HTTP(S) URL and all must match `^https?://(127\.0\.0\.1|localhost|\[::1\]|0\.0\.0\.0)(:\d+)?([/?].*)?$`, case-insensitive. |
| Head only | `cd`, `set`, `source`, `.` | `cd` has at most one arg; every `set` arg matches `^[-+][aeux]$` (empty allowed); source/dot has exactly one arg with basename `hqpcreds`. |
| Head only | `make` | Skips flags and `-C`/`--directory` plus value; requires at least one target and every target in `check,test,test-live,lint,typecheck,fmt-check,format-check,lint-js,test-js,check-css`. |
| Head only | JS/Python commands | `eslint,knip,jscpd,prettier` and `pytest,py.test,unittest,mypy,xenon,flake8,pyright,pylint` are free. `tsc` requires exact `-p`, `--project`, or `--noEmit`. `ruff`/`black` require `--check`, or ruff's first arg `check`. |
| Head only | `pdftotext`, `pair.sh` | Last positional pdftotext arg must be `-` or scratch; pair's first arg must be `list`. |
| Head only | `systemctl` | Rejects `-H,--host,-M,--machine`, `--host=`, `--machine=`; first non-option must be `status,show,cat,list-units,list-unit-files,list-timers,list-sockets,list-dependencies,is-active,is-enabled,is-failed,get-default`. |
| Head only | `journalctl` | Same remote-option rejection; rejects `--rotate,--flush,--sync,--relinquish-var,--smart-relinquish-var,--setup-keys,--update-catalog` or any `--vacuum` prefix. |
| Head only | `ss` | Every short-option character is in `tuxlnaemios46H`; long names before `=` must be `--tcp,--udp,--unix,--listening,--numeric,--all,--extended,--memory,--info,--options,--summary,--ipv4,--ipv6,--no-header,--family`. Non-option operands are unchecked. |
| Head only | `git` (`:370-395`) | Skips `-C` plus value, `--no-pager,-P,--literal-pathspecs,--no-replace-objects,--bare`, `--git-dir=`, `--work-tree=`. `worktree` permits only first arg `list`; `branch` rejects exact `-d,-D,-m,-M,-c,-C,-f,--delete,--move,--copy,--force,--set-upstream-to,-u,--unset-upstream,--edit-description` and `--set-upstream-to=` prefix. Other permitted subcommands are `log,show,diff,status,blame,shortlog,rev-parse,rev-list,ls-files,ls-tree,cat-file,describe,name-rev,whatchanged,check-ignore`. |
| Head only | `node` (`:398-404`) | Requires exact `--test`; rejects `-e,--eval,-p,--print,-i,--interactive`, `--eval=`, `--print=`. |

Any other downstream stage is denied free status (`:472-554`), including a
head-only class reused downstream. Any unknown head is also metered. These
FREE decisions affect the change budget only; they do not override the
separate foreground-test policy.

**Foreground command positions, exemptions, and background form.** All
anchors in this inventory refer to
`~/.claude/hooks/no-foreground-tests.py`. Lines 69-89 apply only to `Bash`,
returning success for any truthy `agent_id` or `agent_type`, or literal
`run_in_background is True`. No finite exempt-agent name list exists in
this hook. The exact common-budget Agent exemptions (`Explore`, `Plan`,
`caveman:cavecrew-investigator`) above are a different policy. A matching
foreground command otherwise denies with exit 2. A native Codex background
form is not established by this Claude-shaped field; F9 remains unproved.

Lines 13-45 define this command-position separator:

```text
(?:^|[;&|(`\n]|\$\()
```

They allow a path prefix `[\w.~+-]*/` and a quote only immediately after
`-c `. The command end accepts end-of-string or
whitespace, `;`, `&`, `|`, `)`, backtick, single quote, or double quote.
Lines 47-66 strip data-only quoted text and heredoc bodies, retaining quoted
commands after `-c` or `ssh` plus host (including option tokens), and
heredocs on a line containing `bash`, `sh`, `zsh`, or `ssh`.

The wrappers at lines 14-19 are assignments `[A-Za-z_]\w*=\S*`;
`sudo,env,time,nice,command,exec`; `xargs` with repeated `-\w+` options;
`timeout` plus one nonspace token; `npx,bunx,pnpx,uvx`;
`(uv|poetry|pipenv|pdm|hatch|rye|pixi) run`; `bundle exec`;
optional-path `python[\d.]*` with repeated `-\w+` options;
`bash,sh,zsh` with the same repeated options; and `node`.
These foreground wrappers differ from the free-Bash normalizer above.

The command patterns at lines 20-36 are:

- Bare `pytest,py.test,unittest,tox,nox,mypy,pyright,ruff,flake8,pylint`;
  `black --check`; `isort --check` or `--check-only`.
- `jest,vitest,mocha`; `playwright test`; `eslint,tsc`;
  `prettier --check`; `biome check,ci,lint`.
- `bats,shellcheck,hadolint,mutmut,cosmic-ray,rspec,ctest,phpunit`;
  `pre-commit run`; `deno test,lint,check`.
- `npm,pnpm,yarn,bun` followed by optional `run ` then
  `(test|check|lint|typecheck|verify)[\w:-]*`, or `run ` then
  `[\w:-]*(test|check|lint|verify|gate|ci)[\w:-]*`.
- `cargo test,check,clippy,nextest`; `go test,vet`; `golangci-lint`.
- `make` targets `[\w-]*(test|check|lint|verify|ci|gate)[\w-]*`;
  `just` targets `[\w-]*(test|check|lint|gate)[\w-]*`.
- `swift test`; `xcodebuild` with a `test` word;
  `mvn,gradle,\S*gradlew` with a `test`, `check`, or `verify` word.
- `foreman` plus a nonspace prefix ending `test`, `check`, `gate`, or
  `verify`; scripts
  `[\w.-]*(test|check|gate|verify|lint)[\w.-]*.(sh|bash|zsh|py)`.

**Document hygiene.** The governed paths, UTF-8 byte caps, block character
caps, frontmatter-description cap, exclusions, and block parsing in the
preceding document table remain current. In addition,
`~/.claude/hooks/gauntlet-doc-budget.py:33-41` defines exactly these seven
regexes (case-sensitive except the last):

```text
^\s*(- )?Log\b
^\s*- 20\d\d-\d\d-\d\d 
\b(PIDs?|pid|shell|sleep)\s+\d{4,}\b
/private/tmp/claude-|/tmp/claude-\d+
\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b
\b\d+(\.\d+)? ?(s|min)\b.*\b\d+(\.\d+)? ?(s|min)\b
(?i)\bread\b.*gauntlet-log/
```

The second regex ends with a literal space after the date. Lines 105-110
apply these to every raw source line, including fenced content and
frontmatter, reporting only the first match per line where hygiene is
enabled. The earlier statement that fences are ignored refers to block
checks, not hygiene; byte caps are also independent.

**DESIGN: policy interface mismatches, without a design edit.**

- `policy.EXEMPT` and `pre` specify finite named-agent membership. The
  source exempts any truthy identity, and `Call.agent` alone does not
  explicitly preserve the distinction between a root role label and a
  source caller carrying an agent identity. Mapping all known helper names
  would not prove source-equivalent treatment of an unknown named helper.
- `DOCS: dict[str, tuple[int,int]]` and `post` describe byte/block caps but
  not per-path hygiene enablement, the raw-line patterns, the separate
  600-character frontmatter-description cap, or external harness paths.
  The complete source policy needs those distinctions in its policy home.
- The launch goal requires retaining every carried owner policy. These
  source checks cannot silently be dropped merely because the current
  interface mentions only caps. All command classification belongs in
  `relay/policy.py` under the design's Homes table; this report supplies
  evidence rather than another implementation of that classifier.

No native `HookSurface`, `PROVEN` entry, background equivalent, or F1-F9
runtime result is claimed by s1.d1a. No hook/configuration source was changed
and no policy source script or model probe was run for this policy inventory.

### Status-command grounding completion: s1.d1b

**Provenance.** This section supersedes the earlier unverified `cc-status`
entries for the payloads exercised below. Installed-binary static evidence
was supplied by the coordinator, read directly on 2026-10-29. The explicit
`codex`-argument observations and their cleanup were supplied in predecessor
session `01a18a96-0e59-7c03-beaf-aa42813a04db`'s handoff. This builder ran
the fresh no-argument probe below on the same date. No owner configuration,
hook source, adapter, or real-model run was executed or changed by this
dispatch; only an isolated executable copy and fake dependency were run.

**Binary resolution and static evidence.** The configured path
`~/.config/iterm2/cc-status` is a symlink to
`/Applications/iTerm.app/Contents/Resources/utilities/cc-status`, a universal
Mach-O arm64/x86_64 executable. The coordinator's `nm -arch arm64` located
`resolveIt2` at `0x1000013e4`. Supplied `otool -arch arm64 -tvV` evidence
shows `CommandLine.arguments[0]` converted through `URL(fileURLWithPath)`,
`resolvingSymlinksInPath` at `0x1000014f0`,
`deletingLastPathComponent` at `0x10000150c`, and
`appendingPathComponent("it2")` at `0x100001524`, followed by
`isExecutableFileAtPath` at `0x100001558`. An executable sibling wins;
otherwise it uses `/usr/bin/env` and fallback arguments. A PATH-only fake
beside the original binary would therefore miss its bundled sibling.

Supplied strings include `UserPromptSubmit`, `PermissionRequest`,
`notification_type`, `permission_prompt`, `last_assistant_message`, agent
names `claude`/`codex`, `get-status`, `set-status`, `get-background-tasks`,
`--json`, `--quiet-if-unresolved`, `--background-tasks-delta`,
`--then-dot-color`, `--then-text-color`, `--if-background-tasks`,
`--background-tasks`, and statuses idle/working/done/waiting/error. Strings
establish vocabulary only, not control flow or exhaustive behavior.

**Predecessor observations.** An exact regular-file copy beside a fake
executable `it2`, invoked with argument `codex`, used a minimal environment
with `TERM_SESSION_ID=w0:probe-session`, a scratch `IT2_SOCK` path, and
scratch HOME/TMPDIR. SessionStart/SessionEnd requested idle with
background-tasks=0; UserPromptSubmit/PreToolUse/PostToolUse requested working;
PermissionRequest and permission-prompt Notification requested waiting;
Stop requested done with `last_assistant_message`; SubagentStop made no
call. Handled events called only fake `it2 set-status
--session=probe-session`; working/waiting included progress-end to idle
transitions. All exited 0 with empty stdout/stderr. Initial no-argument
attempts lacking the colon-address/socket environment made no calls, so
they did not establish the configured no-argument behavior.

**Fresh configured no-argument probe.** Authorized diagnostic scratch
`/private/tmp/relay-cc-status-1kp9nhdg` held a regular-file copy verified
byte-for-byte equal to the installed executable, SHA-256
`3c4448beebc4cdbd20dc1a17478e0cf0121996b57c0dd3d9bcc796c8b0773ac9`.
The executable's sole sibling `it2` was a fake that recorded PID and argv
as JSON lines and always returned
`{"status":"idle","background_tasks":0,"session_id":"probe-session"}`.
No query operation was actually requested in these cases, so this fixed
response does not prove compatibility with real query results.

The copied command received no arguments. Its entire supplied environment
was PATH pointing to the scratch, scratch HOME and TMPDIR directories,
`TERM_SESSION_ID=w0:probe-session`, and IT2_SOCK pointing to the nonexistent
scratch `fake.socket`. Every JSON input included `hook_event_name`,
`session_id=probe-session`, scratch cwd, `tool_name=Bash`,
`tool_input.command=true`, and `last_assistant_message=probe-complete`.
Notification additionally had `notification_type=permission_prompt`.
Each invocation had a separate process group and a ten-second timeout;
none timed out. All nine exited 0 with empty stdout and stderr.

| Input event | Captured fake `it2` request |
|---|---|
| SessionStart, SessionEnd | One `set-status --session=probe-session --status=idle`, empty detail, `--background-tasks=0`; green dot `#00d75f`, gray text `#888888`. |
| UserPromptSubmit, PreToolUse, PostToolUse | One `set-status --session=probe-session --quiet-if-unresolved --status=working`, empty detail; orange dot/text `#ff9500`. |
| PermissionRequest | One `set-status --session=probe-session --quiet-if-unresolved --status=waiting --detail=Allow Bash: true?`; blue dot/text `#5f87ff`. |
| Notification, permission_prompt | One `set-status --session=probe-session --quiet-if-unresolved --status=waiting`; blue dot/text `#5f87ff`. This event was an extra classification probe beyond the configured inventory. |
| Stop | One `set-status --session=probe-session --quiet-if-unresolved --status=done --detail=probe-complete`; green dot/text `#00d75f`. |
| SubagentStop | No fake invocation. |

Working/waiting calls also carried `--expires-on=progress-end`,
`--then-status=idle`, `--then-dot-color=#00d75f`,
`--then-text-color=#888888`, and empty `--then-detail`. The requested
transitions were recorded; no real terminal applied them. No real iTerm
service or other service was contacted by the isolated command: all eight
observed child calls reached the fake executable, whose body only recorded
arguments and printed the fixed JSON.

**Bounded conclusion and design fit.** The exercised configured invocation
requests terminal status, presentation, detail, and background-task reset;
it neither denied the sample tool nor emitted policy context. These
observations support the design's dropped bookkeeping/notification outcome
for those payloads. They do not establish behavior for other payloads,
malformed input, helper identities, query branches, dependency failures,
or every binary path. No `cc-status` design mismatch was found in this
sample; no claim of exhaustive policy absence or native-hook equivalence
is made. The policy-interface mismatches in s1.d1a remain unresolved.
F1-F9, rollout/resume evidence, and any `PROVEN` entry remain outside this
dispatch; completing this subsection does not complete all of Grounding.

**Cleanup proof.** Fresh probe PIDs (command and fake children) were
54169, 54250, 54277, 54279, 54291, 54292, 54304, 54306, 54316,
54317, 54333, 54335, 54360, 54362, 54371, 54373, 54374. All command
children were reaped; a single `ps -p` over all recorded PIDs exited 1
with empty stdout/stderr. Scratch removal completed and its absence was
verified. The predecessor separately supplied absence proof for its PIDs
27976, 28019, 28021, 31231, 31251, 31258, 31260, 31264, 31266,
31268, 31270, 31271, 31232, 31253, 31259, 31261, 31265, 31267,
31269, 31272: `ps -p` exited 1 with empty output, and its scratch was
removed with absence verified. This dispatch created no persistent process.

## F1 — batch 1: model-free hook discovery (2026-10-30)

`git merge main` exited 0: `Merge made by the ort strategy.` Merge commit: `e3120923aff73cc5e0067ea2d20e2b864847506f`. Initial branch `codex-native` was clean; no conflicts.

Scratch: `/var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4`. Created with `tempfile.mkdtemp(prefix="relay-codex-native-", dir=os.environ["TMPDIR"])`; `git init -q /var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/parent/repo` exited 0, empty output. Copied only `/Users/atom/.codex/config.toml` and `hooks.json` with `shutil.copyfile` into `/var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/home`. Originals are read only for this copy; no hook source is read or executed. All CLI probes below set `CODEX_HOME=/var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/home` and run in `/var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/parent/repo`. No credential/session databases were copied. No model call is authorized or attempted.

Scope: F1 plus the model-free listing half of F2; F3–F9 and F2 runtime execution are deliberately skipped. No `PROVEN` entry can be certified by this batch.

### version

```sh
codex --version
```

```text
codex-cli 0.166.0
```

Exit 0; stderr: `(empty)`.

### exec-help

```sh
codex exec --help
```

```text
Run Codex non-interactively

Usage: codex exec [OPTIONS] [PROMPT]
       codex exec [OPTIONS] <COMMAND> [ARGS]

Commands:
  resume  Resume a previous session by id or pick the most recent with --last
  fork    Fork a previous session by id into a new session
  review  Run a code review against the current repository
  help    Print this message or the help of the given subcommand(s)

Arguments:
  [PROMPT]
          Initial instructions for the agent. If not provided as an argument (or if `-` is used),
          instructions are read from stdin. If stdin is piped and a prompt is also provided, stdin
          is appended as a `<stdin>` block

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

      --strict-config
          Error out when config.toml contains fields that are not recognized by this version of
          Codex

  -i, --image <FILE>...
          Optional image(s) to attach to the initial prompt

  -m, --model <MODEL>
          Model the agent should use

      --oss
          Use open-source provider

      --local-provider <OSS_PROVIDER>
          Specify which local provider to use (lmstudio or ollama). If not specified with --oss,
          will use config default or show selection

  -p, --profile <CONFIG_PROFILE_V2>
          Layer $CODEX_HOME/<name>.config.toml on top of the base user config

  -s, --sandbox <SANDBOX_MODE>
          Select the sandbox policy to use when executing model-generated shell commands
          
          [possible values: read-only, workspace-write, danger-full-access]

      --approve-for-me
          Route approval requests through automatic review using the workspace-write sandbox

      --dangerously-bypass-approvals-and-sandbox
          Skip all confirmation prompts and execute commands without sandboxing. EXTREMELY
          DANGEROUS. Intended solely for running in environments that are externally sandboxed

      --dangerously-bypass-hook-trust
          Run enabled hooks without requiring persisted hook trust for this invocation. DANGEROUS.
          Intended only for automation that already vets hook sources

  -C, --cd <DIR>
          Tell the agent to use the specified directory as its working root

      --worktree
          Run the session in a new managed Git worktree

      --add-dir <DIR>
          Additional directories that should be writable alongside the primary workspace

      --thread-source <SOURCE>
          Source classification for newly created or forked threads

      --cyber-access-program <PROGRAM>
          Request an experimental Cyber access program for this turn (OpenAI provider only). Omit to
          use server defaults. Not supported with review; fork requires a prompt
          
          [possible values: standard, daybreak_blue, daybreak_red]

      --skip-git-repo-check
          Allow running Codex outside a Git repository

      --ephemeral
          Run without persisting session files to disk

      --ignore-user-config
          Do not load `$CODEX_HOME/config.toml`; auth still uses `CODEX_HOME`

      --ignore-rules
          Do not load user or project execpolicy `.rules` files

      --output-schema <FILE>
          Path to a JSON Schema file describing the model's final response shape

      --color <COLOR>
          Specifies color settings for use in the output
          
          [default: auto]
          [possible values: always, never, auto]

      --json
          Print events to stdout as JSONL

  -o, --output-last-message <FILE>
          Specifies file where the last message from the agent should be written

  -h, --help
          Print help (see a summary with '-h')

  -V, --version
          Print version
```

Exit 0; stderr: `(empty)`.

### startup-baseline

```sh
codex app-server --print-startup-config
```

Exit 0. Full output captured in scratch `startup-baseline.stdout`; relevant hook fields will be transcribed below. Stderr: `(empty)`.

**Version gap / FAILED for the requested 0.165 target:** the installed executable reports `codex-cli 0.166.0`, superseding the earlier report’s 0.165.0 inventory. No 0.165 executable was supplied in the permitted inputs. These probes can establish only 0.166.0 behavior; they cannot prove 0.165 behavior. No alternate installation or repository is explored.

Baseline startup listing exact stdout:

```json
{"appServerVersion":"0.166.0","configRequirements":{"supportsIndependentSpeedModes":true,"requirements":null}}
```

This contains app-server version and config requirements, with no hook inventory, state keys, source layers, matchers, or commands. Exit 0 is not F1 proof.

### F1 copied-source inventory (configured, not proven loaded)

Exact extraction: `tomllib.loads((home/"config.toml").read_text()).get("hooks")` and `json.loads((home/"hooks.json").read_text())["hooks"]`, using the scratch copies only. Copied config has `features.hooks=true`; its `[hooks]` contains state records, no inline hook definitions.

The rows below exhaust the copied `hooks.json`, not all hooks loaded by `exec`. State-key spelling is corroborated by matching original-path records in the copied config; relocating the file changes the path portion, which remains a candidate until runtime discovery exists. `enabled` is only persisted state; missing means unspecified. Per-run disableability is **unproved for every row**.

| Candidate key suffix after `<home>/hooks.json:` | Layer | Event | Matcher | Exact configured command | Original persisted enabled |
|---|---|---|---|---|---|
| `session_start:0:0` | user | SessionStart | `(absent)` | `python3 -B /Users/atom/.codex/hooks/claude_adapter.py --script /bin/cat --script-arg=/Users/atom/dev/gauntlet/CLAUDE.md --script-timeout=30` | unspecified |
| `session_start:1:0` | user | SessionStart | `(absent)` | `/opt/homebrew/opt/python@3.15/bin/python3.15 -B /Users/atom/.codex/hooks/claude_adapter.py --sync-source /Users/atom/.claude/settings.json --scope '*' --script /Users/atom/.config/iterm2/cc-status --script-timeout 30` | unspecified |
| `session_start:2:0` | user | SessionStart | `(absent)` | `/opt/homebrew/opt/python@3.15/bin/python3.15 -B /Users/atom/.codex/sync-claude.py --rules-hook` | unspecified |
| `user_prompt_submit:0:0` | user | UserPromptSubmit | `(absent)` | `python3 -B /Users/atom/.codex/hooks/claude_adapter.py --script /usr/bin/true --script-timeout=30` | unspecified |
| `user_prompt_submit:1:0` | user | UserPromptSubmit | `(absent)` | `/opt/homebrew/opt/python@3.15/bin/python3.15 -B /Users/atom/.codex/hooks/claude_adapter.py --sync-source /Users/atom/.claude/settings.json --scope '*' --script /Users/atom/.config/iterm2/cc-status --script-timeout 30` | unspecified |
| `pre_tool_use:0:0` | user | PreToolUse | `(absent)` | `python3 -B /Users/atom/.codex/hooks/claude_adapter.py --script /usr/bin/true --script-timeout=30` | True |
| `pre_tool_use:1:0` | user | PreToolUse | `^(exec_command\|shell_command\|shell\|Bash)$` | `python3 -B /Users/atom/.codex/hooks/claude_adapter.py --script /Users/atom/.codex/hooks/codex-change-budget.py --script-timeout=30` | unspecified |
| `pre_tool_use:2:0` | user | PreToolUse | `(absent)` | `/opt/homebrew/opt/python@3.15/bin/python3.15 -B /Users/atom/.codex/hooks/claude_adapter.py --sync-source /Users/atom/.claude/settings.json --scope '*' --script /Users/atom/.config/iterm2/cc-status --script-timeout 30` | unspecified |
| `pre_tool_use:3:0` | user | PreToolUse | `Bash` | `/opt/homebrew/opt/python@3.15/bin/python3.15 -B /Users/atom/.codex/hooks/claude_adapter.py --sync-source /Users/atom/.claude/settings.json --scope '*' --script /Users/atom/.claude/hooks/no-foreground-tests.py --script-timeout 30 --python-arg=-I` | unspecified |
| `pre_tool_use:4:0` | user | PreToolUse | `Agent\|Task` | `/opt/homebrew/opt/python@3.15/bin/python3.15 -B /Users/atom/.codex/hooks/claude_adapter.py --sync-source /Users/atom/.claude/settings.json --scope '*' --script /Users/atom/.claude/hooks/no-foreground-agents.py --script-timeout 30 --python-arg=-I` | unspecified |
| `pre_tool_use:5:0` | user | PreToolUse | `Bash` | `/opt/homebrew/opt/python@3.15/bin/python3.15 -B /Users/atom/.codex/hooks/claude_adapter.py --sync-source /Users/atom/dev/gauntlet/.claude/settings.json --scope /Users/atom/dev/gauntlet --script /Users/atom/.claude/hooks/gauntlet-change-budget.py --script-timeout 30` | unspecified |
| `pre_tool_use:6:0` | user | PreToolUse | `^(?:(?:functions\.)?collaboration[._]*)?(?:list_agents\|wait_agent)$` | `/opt/homebrew/opt/python@3.15/bin/python3.15 -I -B /Users/atom/.codex/hooks/agent-wait-policy.py` | unspecified |
| `post_tool_use:0:0` | user | PostToolUse | `(absent)` | `python3 -B /Users/atom/.codex/hooks/claude_adapter.py --script /usr/bin/true --script-timeout=30` | unspecified |
| `post_tool_use:1:0` | user | PostToolUse | `^(apply_patch\|Write\|Edit)$` | `python3 -B /Users/atom/.codex/hooks/claude_adapter.py --script /Users/atom/.claude/hooks/gauntlet-doc-budget.py --script-arg=--hook --python-arg=-I --script-timeout=30` | unspecified |
| `post_tool_use:2:0` | user | PostToolUse | `(absent)` | `/opt/homebrew/opt/python@3.15/bin/python3.15 -B /Users/atom/.codex/hooks/claude_adapter.py --sync-source /Users/atom/.claude/settings.json --scope '*' --script /Users/atom/.config/iterm2/cc-status --script-timeout 30` | unspecified |
| `post_tool_use:3:0` | user | PostToolUse | `Write\|Edit` | `/opt/homebrew/opt/python@3.15/bin/python3.15 -B /Users/atom/.codex/hooks/claude_adapter.py --sync-source /Users/atom/.claude/settings.json --scope '*' --script /Users/atom/.claude/hooks/gauntlet-doc-budget.py --script-timeout 30 --python-arg=-I --script-arg=--hook` | unspecified |
| `post_tool_use:4:0` | user | PostToolUse | `(absent)` | `/opt/homebrew/opt/python@3.15/bin/python3.15 -B /Users/atom/.codex/hooks/claude_adapter.py --sync-source /Users/atom/.claude/settings.json --scope '*' --script /Users/atom/.claude/hooks/context-watch --script-timeout 30` | unspecified |
| `permission_request:0:0` | user | PermissionRequest | `(absent)` | `/opt/homebrew/opt/python@3.15/bin/python3.15 -B /Users/atom/.codex/hooks/claude_adapter.py --sync-source /Users/atom/.claude/settings.json --scope '*' --script /Users/atom/.config/iterm2/cc-status --script-timeout 30` | unspecified |
| `session_end:0:0` | user | SessionEnd | `(absent)` | `/opt/homebrew/opt/python@3.15/bin/python3.15 -B /Users/atom/.codex/hooks/claude_adapter.py --sync-source /Users/atom/.claude/settings.json --scope '*' --script /Users/atom/.config/iterm2/cc-status --script-timeout 30` | unspecified |
| `stop:0:0` | user | Stop | `(absent)` | `/opt/homebrew/opt/python@3.15/bin/python3.15 -B /Users/atom/.codex/hooks/claude_adapter.py --sync-source /Users/atom/.claude/settings.json --scope '*' --script /Users/atom/.config/iterm2/cc-status --script-timeout 30` | unspecified |
| `subagent_stop:0:0` | user | SubagentStop | `(absent)` | `/opt/homebrew/opt/python@3.15/bin/python3.15 -B /Users/atom/.codex/hooks/claude_adapter.py --sync-source /Users/atom/.claude/settings.json --scope '*' --script /Users/atom/.config/iterm2/cc-status --script-timeout 30` | unspecified |
| `subagent_start:0:0` | user | SubagentStart | `(absent)` | `/opt/homebrew/opt/python@3.15/bin/python3.15 -B /Users/atom/.codex/sync-claude.py --rules-hook` | unspecified |

All listed source commands are text only. No adapter, rules sync, status command, or original-path hook is invoked. Project/inline entries from the actual worktree are not inspected under this batch’s read boundary; runtime completeness cannot be inferred from this copied source.

### F1 seeded multi-layer listing, second attempt

Setup commands were Python standard-library writes, in the scratch only: append a `PreToolUse` group to the copied user JSON; append the following inline TOML to the copied user config; write matching TOML and adjacent JSON in `parent/.codex/`, `parent/repo/.codex/`, and `parent/repo/child/.codex/`; add scratch-only `[projects."<absolute path>"] trust_level="trusted"` records for parent, repo, and child. The git root is `parent/repo`, cwd is its `child`; the outer ancestor fixture is included to test root-boundary discovery, not assumed active.

Representative exact fixture (root project):

```toml
[[hooks.PreToolUse]]
matcher = "relay_probe_project_root_inline"
[[hooks.PreToolUse.hooks]]
type = "command"
command = "/usr/bin/touch /var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/project_root_inline.marker"
```

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "relay_probe_project_root_json",
        "hooks": [
          {
            "type": "command",
            "command": "/usr/bin/touch /var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/project_root_json.marker"
          }
        ]
      }
    ]
  }
}
```

All other fixtures use the same shape and unique `relay_probe_<label>` matcher and `<label>.marker` command, labels `user_json`, `user_inline`, `ancestor_json`, `ancestor_inline`, `project_child_json`, `project_child_inline`; root-project JSON uses `project_root_json` and inline uses `project_root_inline`. No executable hook source is created.

```sh
cd /var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/parent/repo/child
CODEX_HOME=/var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/home codex --strict-config -c 'hooks.PreToolUse=[{matcher="relay_probe_cli",hooks=[{type="command",command="/usr/bin/touch /var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/cli.marker"}]}]' app-server --print-startup-config
```

Exit 0.

```text
stdout: {"appServerVersion":"0.166.0","configRequirements":{"supportsIndependentSpeedModes":true,"requirements":null}}
stderr: (empty)
```

**F1 FAILED:** two listing attempts produced no discovered-hook inventory. No further retry of that listing probe is made. A successful process exit does not prove these fixture hooks loaded or that all layers were enumerated.

## F2 — batch 1: listing half only

The second F1 invocation is the seeded baseline. Each probe below adds exactly one candidate per-hook `enabled=false` override to that same fixture/cwd; the copied source suggests the state-key spelling but the listing has not confirmed it. No global hook switch, hook-trust bypass, paid execution, or real configuration edit is used.

### F2 user

```sh
CODEX_HOME=/var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/home codex --strict-config -c 'hooks.PreToolUse=[{matcher="relay_probe_cli",hooks=[{type="command",command="/usr/bin/touch /var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/cli.marker"}]}]' -c 'hooks.state."/var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/home/hooks.json:pre_tool_use:7:0".enabled=false' app-server --print-startup-config
```

Exit 1; cwd `/var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/parent/repo/child`.

```text
stdout: {"error":{"code":-32600,"data":{"reason":"configLoad","filePath":null,"line":null,"column":null,"detail":"unknown configuration field `hooks.state.\"/var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/home/hooks.json:pre_tool_use:7:0\"` in -c/--config override"},"message":"failed to load configuration: unknown configuration field `hooks.state.\"/var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/home/hooks.json:pre_tool_use:7:0\"` in -c/--config override"}}
stderr: Error: startup configuration unavailable
```

**FAILED (listing evidence):** stdout differs from the baseline; no hook list or disabled state is exposed, so removal of the `user` hook cannot be established. This override probe was run once, with no retry.

### F2 project

```sh
CODEX_HOME=/var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/home codex --strict-config -c 'hooks.PreToolUse=[{matcher="relay_probe_cli",hooks=[{type="command",command="/usr/bin/touch /var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/cli.marker"}]}]' -c 'hooks.state."/var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/parent/repo/.codex/hooks.json:pre_tool_use:0:0".enabled=false' app-server --print-startup-config
```

Exit 1; cwd `/var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/parent/repo/child`.

```text
stdout: {"error":{"code":-32600,"data":{"reason":"configLoad","filePath":null,"line":null,"column":null,"detail":"unknown configuration field `hooks.state.\"/var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/parent/repo/.codex/hooks` in -c/--config override"},"message":"failed to load configuration: unknown configuration field `hooks.state.\"/var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/parent/repo/.codex/hooks` in -c/--config override"}}
stderr: Error: startup configuration unavailable
```

**FAILED (listing evidence):** stdout differs from the baseline; no hook list or disabled state is exposed, so removal of the `project` hook cannot be established. This override probe was run once, with no retry.

### F2 inline -c

```sh
CODEX_HOME=/var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/home codex --strict-config -c 'hooks.PreToolUse=[{matcher="relay_probe_cli",hooks=[{type="command",command="/usr/bin/touch /var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/cli.marker"}]}]' -c 'hooks.state."/<session-flags>/config.toml:pre_tool_use:0:0".enabled=false' app-server --print-startup-config
```

Exit 1; cwd `/var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/parent/repo/child`.

```text
stdout: {"error":{"code":-32600,"data":{"reason":"configLoad","filePath":null,"line":null,"column":null,"detail":"unknown configuration field `hooks.state.\"/<session-flags>/config.toml:pre_tool_use:0:0\"` in -c/--config override"},"message":"failed to load configuration: unknown configuration field `hooks.state.\"/<session-flags>/config.toml:pre_tool_use:0:0\"` in -c/--config override"}}
stderr: Error: startup configuration unavailable
```

**FAILED (listing evidence):** stdout differs from the baseline; no hook list or disabled state is exposed, so removal of the `inline -c` hook cannot be established. This override probe was run once, with no retry.

### F1/F2 candidate HookSurface and bounded result

| Field | Candidate / evidence status |
|---|---|
| `list_args` | `("app-server", "--print-startup-config")`: **FAILED**, prints version/requirements only in both F1 attempts. No replacement listing command appears in the permitted `exec --help` output. |
| `disable` | `hooks.state."{key}".enabled=false`: candidate inferred from copied state config; the first three F2 invocations exited 1 with `unknown configuration field` errors. **FAILED in this dotted-key form**; no hook removal proved. |
| `inline` | `hooks.PreToolUse=[{matcher="relay_probe_cli",hooks=[{type="command",command="<scratch touch command>"}]}]`: concrete candidate used above. General template `hooks.{event}=[{matcher="{matcher}",hooks=[{type="command",command="{command}"}]}]` remains unproved; startup output does not demonstrate parsing/loading, even with `--strict-config`. Proper TOML escaping of substitutions is required. |
| `trust` | `hooks.state."{key}".trusted_hash="<sha256:content hash>"`: field observed in copied user config, not an established template. Hash construction and inline trust acceptance were not probed (F3 excluded). |
| `deny` | Unknown; neither `exit2` nor `json` is proved. F4 excluded. |

**DESIGN:** F1 failed to provide the required model-free discovery surface on installed 0.166.0, and the requested 0.165 target is unavailable within the supplied inputs. F2’s listing half is **FAILED / not proved**, with zero hook removals observable; this is not evidence that the overrides fail to disable execution. Neither version receives a `PROVEN` entry. Configured source rows above are not presented as the set actually loaded by `codex exec`. Model execution, F2 runtime marker absence, and F3–F9 were skipped as requested.

Commands were synchronous and completed; no background process or persistent server was launched. Marker files were absent after startup probes; this proves only that this model-free command did not execute the harmless scratch commands, not F2 runtime suppression. No probe command was retried more than twice.

### F2 second and final attempt: override the state map

The first attempts failed with `unknown configuration field` in the dotted quoted-key override; this corrects the earlier preliminary summary. Each final attempt uses an inline TOML map at `hooks.state`, avoiding a quoted path component in the `-c` dotted key. This is the second attempt for each layer, with no further retry.

#### F2 user — final

```sh
CODEX_HOME=/var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/home codex --strict-config -c 'hooks.PreToolUse=[{matcher="relay_probe_cli",hooks=[{type="command",command="/usr/bin/touch /var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/cli.marker"}]}]' -c 'hooks.state={"/var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/home/hooks.json:pre_tool_use:7:0"={enabled=false}}' app-server --print-startup-config
```

Exit 0; cwd `/var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/parent/repo/child`.

```text
stdout: {"appServerVersion":"0.166.0","configRequirements":{"supportsIndependentSpeedModes":true,"requirements":null}}
stderr: (empty)
```

**FAILED (F2 listing):** output is byte-for-byte identical to baseline, exposing no hook inventory or disabled state. No runtime inference or further retry.

#### F2 project — final

```sh
CODEX_HOME=/var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/home codex --strict-config -c 'hooks.PreToolUse=[{matcher="relay_probe_cli",hooks=[{type="command",command="/usr/bin/touch /var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/cli.marker"}]}]' -c 'hooks.state={"/var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/parent/repo/.codex/hooks.json:pre_tool_use:0:0"={enabled=false}}' app-server --print-startup-config
```

Exit 0; cwd `/var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/parent/repo/child`.

```text
stdout: {"appServerVersion":"0.166.0","configRequirements":{"supportsIndependentSpeedModes":true,"requirements":null}}
stderr: (empty)
```

**FAILED (F2 listing):** output is byte-for-byte identical to baseline, exposing no hook inventory or disabled state. No runtime inference or further retry.

#### F2 inline -c — final

```sh
CODEX_HOME=/var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/home codex --strict-config -c 'hooks.PreToolUse=[{matcher="relay_probe_cli",hooks=[{type="command",command="/usr/bin/touch /var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/cli.marker"}]}]' -c 'hooks.state={"/<session-flags>/config.toml:pre_tool_use:0:0"={enabled=false}}' app-server --print-startup-config
```

Exit 0; cwd `/var/folders/w8/42n0_hcx07jbsdd75ttwz3t80000gn/T/relay-codex-native-zsj5v7g4/parent/repo/child`.

```text
stdout: {"appServerVersion":"0.166.0","configRequirements":{"supportsIndependentSpeedModes":true,"requirements":null}}
stderr: (empty)
```

**FAILED (F2 listing):** output is byte-for-byte identical to baseline, exposing no hook inventory or disabled state. No runtime inference or further retry.

Final `disable` candidate: `hooks.state={"{key}"={enabled=false}}`; any CLI acceptance is distinct from proof of disabling. F1 and F2 listing remain FAILED/unproved for the reasons recorded above. F2 runtime and F3–F9 remain skipped.

### F1/F2 cleanup and done-check

Final scratch check: `list(root.glob("*.marker"))` returned `[]`. `shutil.rmtree(root)` removed only the named scratch tree; `assert not root.exists()` passed. Captured outputs were transcribed above before removal. Every subprocess returned synchronously; no background process was launched or left for cleanup. Only `docs/codex-native-report.md` differs from the merge commit.

```sh
grep -nF 'F2' docs/codex-native-report.md
```

Exit 0; 18 matching lines. Output trimmed to the first two matches:

```text
586:Scope: F1 plus the model-free listing half of F2; F3–F9 and F2 runtime execution are deliberately skipped. No `PROVEN` entry can be certified by this batch.
828:## F2 — batch 1: listing half only
```

CHOSEN: keep source inventory separate from runtime discovery; report absent evidence as FAILED; do not infer execution suppression from startup output; no model call, code change, configuration-source change, or push.
