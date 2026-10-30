Status: approved.

## Why

Sections from separate queues share a repository but do not share ownership. A section's identity is its resolved queue path together with its section id. Existing worktrees remain usable under their existing names when the owning queue identifies them.

There are four sites of unsafe worktree selection: `relay/git.py:12` selects the repository-wide `lead/<sid>` branch; `relay/loop.py:209` uses it for blockers; `relay/loop.py:263` uses it for checks, research and questions; the architect fallback repeats that selection and constructs the branch separately at `relay/loop.py:586`. Its report path bypasses validation at `relay/loop.py:584`.

Queue state is already isolated by the resolved queue path and its hash (`relay/state.py:71`), including maps (`relay/state.py:336`). Map files record only the section and commit (`relay/research.py:175`), and reuse checks only file bytes (`relay/research.py:61`). A map made in another queue's worktree can therefore survive a corrected lookup when the mapped bytes match. The lead prompt names the queue and section but assigns no branch or worktree (`relay/prompts.py:33`). Existing queue-specific lead reports are stored in `SectionState.last_report` (`relay/state.py:47`); `ladder.lead_branch` already parses their `BRANCH` lines (`relay/ladder.py:107`).

## Modules

### `relay/state.py`: queue identity and durable section bindings

Extract the current state-directory slug calculation without changing its bytes. Its existing resolved-path hash becomes the shared identity for state, branches, worktree locations and map provenance. Resolving aliases of one queue gives one identity; separate resolved queue paths give separate identities, including equally named files in different directories. Use the full hexadecimal digest for new names and provenance; retain its existing 16-character prefix in state-directory names. Hexadecimal names remain valid git ref components even when a queue filename contains repeated dots or other ref-invalid characters.

```python
def queue_id(queue: Path) -> str:
    """SHA-256 hex digest of str(queue.resolve()).encode()."""
    raise NotImplementedError

def queue_key(queue: Path) -> str:
    """The existing readable resolved-path suffix plus its 16-character SHA-256 suffix."""
    raise NotImplementedError

# Additional backwards-compatible SectionState fields:
worktree_branch: str | None = None
worktree_path: str | None = None

class State:
    def bind_worktree(self, sid: str, branch: str, path: Path) -> None:
        """Atomically persist the validated branch and absolute worktree path together."""
        raise NotImplementedError
```

`State.open` calls `queue_key`, which uses `queue_id` for its hash suffix; existing state directories, locks, ledgers and map paths stay discoverable. Missing fields in old records take their defaults. A later report without a `BRANCH` line does not erase a binding. Marking a section done retains the binding, because blocker checks still need it. State does not run git or infer ownership from section ids.

### `relay/git.py`: queue-qualified names and validated worktree lookup

```python
@dataclass(frozen=True)
class SectionWorktree:
    branch: str
    path: Path

def section_branch(queue: Path, sid: str) -> str:
    """lead/<queue_id(queue)>/<sid>."""
    raise NotImplementedError

def section_path(repo: Path, queue: Path, sid: str) -> Path:
    """repo.parent / (repo.name + '-wt') / queue_id(queue) / sid."""
    raise NotImplementedError

def section_worktree(
    repo: Path, queue: Path, sid: str,
    recorded: SectionWorktree | None = None,
) -> SectionWorktree | None:
    """Validate an explicit binding, otherwise find this queue's qualified branch."""
    raise NotImplementedError
```

Parse `git worktree list --porcelain` once per lookup, through `runner.capture`. An explicit binding is valid only when its resolved path and exact branch occur together in this repository's list. Detached worktrees, stale paths, a changed branch, another repository and partial output from failed git are not matches. A branch in the new qualified namespace for another queue or section is never accepted, even through a report. Namespaced branches use the full shared queue identity, with no name truncation or separate hash calculation.

An explicitly recorded legacy branch, including `lead/<sid>` or a custom name, remains usable without renaming or moving it. With no explicit binding, only the exact new qualified branch is discoverable. There is no fallback to a repository-wide `lead/<sid>`, queue basename, matching worktree basename or the only worktree in the repository. A bare legacy branch cannot establish which queue owns it.

This function replaces `relay/git.py:12`; callers use the returned branch instead of reconstructing one. Git reads remain here and process execution stays in `runner.capture`.

### `relay/research.py`: map ownership alongside content freshness

```python
# Additional backwards-compatible Map field:
queue: str | None = None

def owned(m: Map, queue: Path) -> bool:
    """Whether m carries queue_id(queue)."""
    raise NotImplementedError

def attribute(m: Map, queue: Path) -> Map:
    """Return m with this queue's key, retaining all map content and digests."""
    raise NotImplementedError
```

`save` writes an optional `queue <key>` record between the header and per-file records; `load` accepts the previous form with `queue=None`, rejects malformed or duplicate provenance records, and restores the field. `split` and refresh preserve provenance. The agent-facing `block` form remains the section, commit and body; map metadata is a storage concern.

The loop accepts a cached map only when `owned` is true. A missing or different owner causes one full remap, not a partial refresh, even when all mapped bytes match. This retires potentially contaminated maps from the old lookup. Correctly owned maps retain the existing digest-based reuse behavior, including reuse from the queue checkout into its own newly created worktree with matching bytes. The commit remains the HEAD where research originally ran; reuse does not relabel an old map with a newer commit.

### `relay/loop.py`: one ownership resolver for every section consumer

```python
def _section_worktree(
    cwd: Path, queue: Path, sid: str, state: State,
) -> git.SectionWorktree | None:
    """Resolve and persist this queue section's validated worktree."""
    raise NotImplementedError

def _section_cwd(cwd: Path, queue: Path, sid: str, state: State) -> Path:
    """The owned worktree's path, else the queue's repository checkout."""
    raise NotImplementedError
```

The resolver uses a persisted binding first. Before a binding exists, it parses only this queue section's `last_report` through `ladder.lead_branch`, validates that candidate through `git.section_worktree`, and persists a successful match. Otherwise it looks for this queue section's qualified branch. It never takes another section's report or the queue-wide previous session as ownership evidence. An invalid explicit binding does not cause adoption of a bare legacy branch. A validated legacy binding remains preferred if a new qualified branch also exists.

Research, refresh, `ask`, checks (including pending checks), blocker cleanliness and architect code evidence all use this resolver. Pass the queue through `_wake` and `_landed`, including recursive recut blockers. `_lead_code` uses the resolver's branch and its worktree HEAD; it no longer trusts arbitrary report paths or synthesizes `lead/<sid>`. Resolve after recording a lead's report and before handling its status, so a first legacy report is available to the immediate check or architect call. Resolving also persists a newly created qualified worktree even when the lead omitted `BRANCH`.

Before research, load the map under the existing research lock. Drop an unowned map and its researcher session through `State.drop_map`, then perform a full run in the resolved cwd. Attribute a valid new map before saving it. Read HEAD in that cwd before the researcher starts and retain that commit in the map and lead ledger entry. No new map lock or file-writing path is introduced.

`ask` resolves the same owned worktree. If a saved map exists but lacks this queue's provenance, discard that map and researcher session under the research lock and raise `ResearchError` explaining that research must be refreshed before a follow-up. This prevents resuming a researcher attached to a known unverified map. Existing no-map researcher behavior otherwise remains unchanged.

### `relay/prompts.py`: assign the selected worktree to the lead

```python
# Additional keyword-only lead_prompt argument:
worktree: git.SectionWorktree | None = None
```

The loop supplies either the resolved legacy/new binding or a proposed binding built by `git.section_branch` and `git.section_path`. The prompt tells the lead to use that exact branch and path, create the worktree there if absent, and report `BRANCH <branch> <absolute path>` in its final report. A resumed legacy run uses its existing binding. This assignment takes precedence over generic worktree naming in the section body or a recalled session. Relay continues starting the lead in the queue checkout; the lead creates and uses its assigned worktree. The prompt module renders the assignment and never calculates a queue key or chooses a worktree.

### Test support and documentation

Extend `tests/conftest.py:146` so fixtures can create queue-qualified worktrees and explicit legacy bindings. Keep legacy fixtures where the test exercises legacy behavior; migrate tests that previously relied on unqualified discovery to an explicit binding or a qualified branch. Shared setup belongs in `tests/conftest.py` or `tests/harness.py`, not copied into test files. Existing in-process agent support at `tests/fakes/fake_runner.py:18` records cwd and prompts and remains the shared runner fake.

Update the worktree description at `README.md:31`, the check description at `README.md:37`, and the state description at `README.md:196` to describe qualified names, persisted legacy bindings and the one-time map refresh. No queue file or live state is migrated by this development task.

## Homes

| Shared concern | One home | Forbidden elsewhere |
|---|---|---|
| Canonical queue identity and existing state-directory compatibility | `state.queue_id`, `state.queue_key` | Another path hash, basename identity or slug algorithm |
| Branch/path names and validation against repository worktrees | `git.py` | Raw porcelain parsing, git subprocesses or bare-sid fallback in callers |
| Durable binding and state writes | `State.bind_worktree`, existing write guard | Editing state JSON in loop or prompts |
| Legacy report syntax | `ladder.lead_branch` | A second BRANCH parser |
| Selecting the section's ownership evidence | `loop._section_worktree` | Separate report/worktree decisions for checks, blockers, research or architects |
| Map provenance and serialization | `research.py` | Loop parsing or rewriting map records |
| Map invalidation and refresh sequencing | Existing `_research`, `ask` and research lock | Additional ownership locks or independent map-write paths |
| Lead assignment wording | `prompts.lead_prompt` | Branch naming or prompt assembly in the loop |
| Process lifecycle, errors and atomic writes | Existing `runner.py`, `errors.py`, `files.py` | New process wrappers, exit codes or atomic writers |
| Git and loop test setup | `tests/conftest.py`, `tests/harness.py`, existing fake runner | Per-test copies of shared setup |

## Order

1. **Interfaces — `builder` (`stub`).** Add the new signatures and defaulted fields in `relay/state.py`, `relay/git.py`, `relay/research.py`, `relay/loop.py` and `relay/prompts.py`; new callable bodies are raise-only. Existing APIs remain usable until their integration step replaces their callers.
2. **Core behavior — `test-writer`.** Extend shared fixtures in `tests/conftest.py` as needed and write `tests/test_state.py`, `tests/test_git.py`, `tests/test_research.py`: stable and distinct queue keys, old state lookup, persisted bindings, exact worktree validation, qualified names, explicit legacy compatibility, rejection of another queue's namespace, and map ownership serialization and preservation.
3. **Core implementation — `builder`.** Implement the state, git and map contracts in `relay/state.py`, `relay/git.py` and `relay/research.py` against the core tests.
4. **Integration behavior — `test-writer`.** Write `tests/test_loop.py` and `tests/test_prompts.py`, extending `tests/conftest.py` and `tests/harness.py` only for shared setup. Cover two queues in one repository that both contain `s1`, each using only its own worktree for research, refresh, questions and checks, with distinct correctly attributed map commits and ledger entries. Cover another queue's dirty blocker, architect evidence, a queue without a worktree beside another queue's legacy `lead/s1`, resumed legacy reports, restart after a report without BRANCH, rejected foreign/stale report paths, same-basename queues, and one-time rejection of old or foreign maps despite matching bytes. Preserve valid within-queue map reuse. Update existing tests whose fixture setup assumes global section ownership.
5. **Integration — `builder`.** Implement the resolver and all consumers in `relay/loop.py`, and the explicit assignment in `relay/prompts.py`. Remove the old unqualified lookup signature after all callers and tests use the queue-aware interface. Run the full suite with `uv run pytest`, the development command at `README.md:218`; keep the configured two workers (`pyproject.toml:21`).
6. **Documentation — `builder`.** Update `README.md` with the ownership and migration contract above.
