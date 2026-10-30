Status: approved.

# Relay research reuse

## Why

A fresh lead gets a full remap whenever any file the map names differs from the map's commit, so every lead that commits work in its section triggers a whole new research run.

- `relay/research.py:107-109` `stale` is true unless `git.changed(cwd, m.commit, m.files)` (`relay/git.py:50-55`) is exactly False. One changed path among all of the map's files marks the whole map stale. A git failure (None) does the same.
- `relay/loop.py:316-320` checks `stale` and, when true, calls `state.drop_map` (`relay/state.py:351-354`) and starts a full research run (`relay/loop.py:321-348`) with `research_brief` (`relay/prompts.py:185-199`). That brief can only map from scratch.
- A section's lead edits the files its section touches, and those are the files the map names. In the gates run's ledger, every s2 and s3 lead was followed by another full research run: s2 had 4 full maps across 3 RETIRED leads, and s3 had 3 maps across 2 RETIRED leads. Run 20's map at `a0417ab` named 28 files. Of the 9 files the lead changed by `7fc2945`, 6 were mapped, so all 28 were remapped. Run 8's map at `c87855b` named 53 files, and 21 of them were changed by `5c8b9c5`.
- Main-to-worktree: before `lead/<sid>` exists, `_section_cwd` (`relay/loop.py:260-262`) maps in the main checkout at main's HEAD (s3's run 16 at `db259df`). The next pass maps in the worktree, and the lead's first commits there make that whole map stale too.
- Basing freshness on a commit has two more faults. `git diff <commit>` never sees an untracked file, so a map naming a file the lead created and has not committed is never found stale. And a commit that git cannot resolve forces a full remap.
- `tests/test_loop.py:3895-3933` asserts the current full remap after a retire that changed one mapped file. `tests/test_loop.py:3866-3893` covers reuse when nothing changed. `tests/test_research.py:452-532` covers `stale`. `tests/test_git.py:304-396` covers `git.changed`, and `tests/test_git.py:400` checks that `head` and `changed` run git through `capture`.

## Modules

### `relay/research.py`: the map, its per-file digests, and its split and merge

A map file records a digest of every file it names. Freshness is decided file by file from those digests, with no commit and no git. A stale map is split into the part that still holds and the files that changed, and a refresh is merged back into it.

```python
UNKNOWN = "-"  # the digest of a file that is missing, unreadable, or changed while the researcher ran

@dataclass(frozen=True)
class Map:
    sid: str
    commit: str  # the HEAD Relay read in the research cwd before the run; kept for the ledger and block()
    files: tuple[str, ...]
    body: str
    digests: tuple[str, ...] = ()  # one per files entry, same order; () means none recorded

def digest(cwd: Path, path: str) -> str:
    """sha256 hex of the bytes at cwd/path; UNKNOWN when it is not a readable regular file."""
    raise NotImplementedError

def stamp(m: Map, cwd: Path, since_ns: int) -> Map:
    """m with digests for every file: digest(cwd, f), or UNKNOWN for a file whose st_mtime_ns >= since_ns."""
    raise NotImplementedError

def changed(m: Map, cwd: Path) -> frozenset[str]:
    """The files of m whose recorded digest is UNKNOWN, missing, or differs from digest(cwd, f).
    Every file when m.digests is ()."""
    raise NotImplementedError

def split(m: Map, changed: frozenset[str]) -> Map | None:
    """The part of m that still holds: entries on unchanged files, and links with both ends unchanged,
    in their order, with their digests. None when no entry is left."""
    raise NotImplementedError

def parse_refresh(
    kept: Map, commit: str, changed: frozenset[str], result_text: str | None, cfg: Config
) -> Map | None:
    """kept merged with the last MAP block of result_text, at `commit`, without digests:
    kept entries, then refresh entries, then LINKS with kept links, then refresh links.
    The block may hold no entries. None when the block is absent or malformed, when one of its
    entries names a file that a kept entry names, or when the merge is over
    cfg.map_max_lines or cfg.map_max_chars."""
    raise NotImplementedError
```

`save` writes the header line, then one `file <digest> <path>` line for each file, then the body. `load` reads those lines. A file saved before this change has no `file` lines, so it loads with `digests=()`, and `changed` reports every file, which means one full remap. A `file` line that does not parse, or whose path set differs from the body's `files`, makes `load` return None. `stale` is removed. `parse_map`, `block` and `parse_answer` keep their signatures and output. A brief never carries a digest.

Replaces `stale` (`relay/research.py:107-109`).

### `relay/git.py`

`changed` (`relay/git.py:50-55`) is removed, because no caller is left. Nothing is added.

### `relay/prompts.py`: the refresh brief

```python
def refresh_brief(
    queue: Path, section: Section, kept: Map, changed: tuple[str, ...], flag: Path, cfg: Config
) -> str:
    """Section body, research.block(kept), the changed paths sorted, and the order to map only the code
    in those paths that the section touches. It may name new paths, but no entry may name a file a kept
    entry names. Gives the room left under the caps after kept, the MAP form and the flag rule."""
    raise NotImplementedError
```

`research_brief` and `refresh_brief` share one private helper for the MAP form text and the flag rule. That text is not written twice.

### `relay/progress.py`

```python
def research_refreshing(sid: str, cwd: Path, changed: frozenset[str], kept: Map) -> None:
    """`research <sid>: refreshing <len(changed)> changed of <files> mapped files in <cwd>`."""
    raise NotImplementedError
```

`map_reused`, `research_started` and `research_finished` keep their wording.

### `relay/loop.py`: `_research` chooses reuse, refresh or full research

All of this runs under `state.research_lock(sid)`, in `where = _section_cwd(cwd, sid)`:

1. `saved = research.load(...)`. When it is present and `research.changed(saved, where)` is empty, report `progress.map_reused` and return `saved`. Nothing runs. This is the path across RETIRED and across main-to-worktree when no mapped file changed.
2. `kept = research.split(saved, changed)` when `saved` is present, else None.
3. `commit = git.head(where)`. On None, return no map, as today.
4. Record `since_ns = time.time_ns()`, then run the researcher (ledger kind `"research"`):
   - when `kept` is present: `progress.research_refreshing`, `refresh_brief`, then `research.parse_refresh`;
   - otherwise: `progress.research_started`, `research_brief`, then `research.parse_map`.
5. On a map, `research.save(research.stamp(m, where, since_ns), state.map_path(sid))` and return it. `set_research_session`, `research_finished`, the failure ping and the budget flag stay as they are today.

`_research` no longer calls `state.drop_map`. The saved file is replaced only by a good map, through `write_atomic`. A failed, malformed or over-cap refresh leaves that lead without a map, as a failed research does today, and the next pass checks the saved map again and refreshes again. A stale file on disk is never used, because `changed` runs on every load. Done sections and recuts keep their `drop_map` calls (`relay/state.py:136`, `relay/loop.py:799`).

## Homes

| Concern | Home | Forbidden elsewhere |
|---|---|---|
| Map text: format, parse, caps, split, merge | `relay/research.py` | Parsing or building MAP lines in `loop.py`, `prompts.py` or tests outside fixtures |
| Map freshness and file digests | `research.digest`, `research.stamp`, `research.changed` | Hashing mapped files elsewhere, or deciding freshness with git. `state.py:74`'s hash keys the state directory and is a separate concern. |
| Map file on disk | `research.save` / `research.load`, path from `State.map_path` | Reading or writing `maps/<sid>.map` anywhere else |
| Git queries | `relay/git.py` | `runner.capture(["git", ...])` outside `git.py` |
| Choosing reuse, refresh or full research, and the lock | `loop._research` | A second caller of the researcher for maps |
| Researcher brief text and the MAP form | `relay/prompts.py`, one shared private form helper | Writing the MAP form text twice |
| Research progress lines | `relay/progress.py` | `print` of research lines in `loop.py` |
| Map test fixtures | `tests/fixtures/research-map.txt`, plus the refresh fixtures that the loop tests add under `tests/fixtures/` | Map text written inline in more than one test module |
| Git repo test helper | `GitRepo` in `tests/conftest.py` | A second temp-repo builder |

## Order

1. **stub** (`builder`): `relay/research.py`, `relay/prompts.py` and `relay/progress.py` get the Modules signatures above, raise-only, plus the `Map.digests` field.
2. **red: map digests, split, merge, save and load** (`test-writer`): `tests/test_research.py` and `tests/test_git.py`. Covers per-file freshness, unknown and missing files, files changed during a run, an old map file without `file` lines, and merge rules and caps. Removes the `stale` tests and the `git.changed` tests, and narrows `tests/test_git.py:400` to `head`.
3. **map core** (`builder`): `relay/research.py`, and `relay/git.py`, which drops `changed`.
4. **red: refresh brief and progress line** (`test-writer`): `tests/test_prompts.py`, `tests/test_progress.py`.
5. **refresh brief and progress line** (`builder`): `relay/prompts.py`, `relay/progress.py`.
6. **red: loop reuse and refresh** (`test-writer`): `tests/test_loop.py`, plus fixtures under `tests/fixtures/`. A fresh lead after RETIRED reuses the map when no mapped file changed. A map drawn in the main checkout is reused in the new `lead/<sid>` worktree when the mapped files match. A changed mapped file, including an uncommitted or untracked one, gets a refresh run that covers only the changed files, and the lead gets the merged map. A failed or invalid refresh leaves the lead without a map and keeps the saved file for the next pass. `tests/test_loop.py:3895-3933` is rewritten to expect a refresh.
7. **loop** (`builder`): `relay/loop.py` `_research`.
8. **full suite** (`lead`, writes nothing): `uv run pytest` over the whole suite, with the existing tests and the new ones all passing.
