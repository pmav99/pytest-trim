---
name: pytest-trim
description: >
  Use when the user wants to run `pytest`, rerun failing pytest selections,
  inspect compact `--trim` failure output, or iterate on test fixes in a
  Python project and compact output is acceptable. `pytest-trim` is for
  context minimization, not faster test execution: it reduces transcript size
  for humans, tools, and agents without changing how pytest runs tests.
  Trigger on requests like "run the tests", "run pytest", "rerun failures",
  "what failed", "what's failing", "run this test", or fix-and-rerun loops
  over nodeids, paths, `-k`, `-m`, `--lf`, `--sw`, or `--maxfail`. Do NOT use
  when the user explicitly wants standard pytest output, full tracebacks,
  progress dots, warning sections, verbose formatting, a non-pytest runner,
  or documentation-only discussion of the plugin or `TRIM:` protocol.
---

# Pytest Trim

Run pytest with compact output and a stable final status line. Its purpose is
to minimize transcript/context size for humans, tools, and agents, not to make
pytest execute faster.

For agent-driven loops, prefer artifact mode unless there is a concrete reason
not to.

## When to Use It

- Requests to run pytest when compact output is acceptable.
- Requests to rerun failing tests or inspect compact `--trim` failure output.
- Test-fix loops where the next action depends on a compact final status line.
- Narrow reruns such as nodeid, path, `-k`, `-m`, `--lf`, `--sw`, or
  `--maxfail`.

## When Not to Use It

- User explicitly asks for standard, raw, or verbose pytest output.
- User wants full tracebacks, warning sections, progress dots, or default
  terminal formatting that `--trim` suppresses.
- Request targets a non-pytest runner or a documentation-only explanation of
  the plugin or `TRIM:` protocol without a pytest run or failure-triage task.

## Install Detection

Project metadata is not authoritative. Do not gate on `pyproject.toml`,
`poetry.lock`, `uv.lock`, or `requirements.txt`. Probe the runtime instead.

Either approach works; pick one:

- **Just run it.** Invoke the launcher with `--trim`. If pytest rejects the
  flag with a usage error like `unrecognized arguments: --trim`, fall back to
  plain pytest through the same launcher for the rest of the session.
- **Probe first.** Run `pytest --help | grep -- --trim` or the launcher
  equivalent. A match means the plugin is available; no match means fall back.

Cache the result per session. No need to re-probe on every invocation.

## Command Selection

1. Preserve the project's normal pytest launcher and append `--trim`.
2. For agent-driven loops, prefer artifact mode by default unless there is a
   concrete reason not to.
   - `--trim-artifacts` writes under pytest's cache directory.
   - `--trim-artifacts-dir=PATH` controls location explicitly and already
     implies `--trim-artifacts`.
3. Reasons to skip artifact mode include:
   - slow or network-backed filesystems where per-failure writes may hurt
     latency
   - environments where tracebacks, locals, or captured output should not be
     written to disk
   - cases where the user explicitly wants no sidecar files
4. If pytest rejects `--trim` (see *Install Detection*), fall back to normal
   pytest usage through the same launcher.

The plugin only changes output when `--trim` is present.

## Output Contract

Treat the final non-empty line as the protocol line. Any earlier non-empty
lines are issue reports. The protocol line always begins with the literal
`TRIM: ` prefix, so parsers should anchor on that prefix to locate it in mixed
output.

Issue lines are emitted in one of these forms:

- `nodeid:lineno - message`
- `nodeid - message`

This includes normal test failures and collection/setup/teardown failures.

Indented `  detail: ...` lines attach to the most recent headline issue line
above them. Up to two detail lines may appear per failure, optionally followed
by a `  detail: (+N more details omitted)` marker. Detail lines never appear
standalone; always bind them to the preceding headline when grouping output per
failure.

If artifact mode is enabled, an issue may also include:

- `  artifact: <path>`

This points to a per-failure text artifact containing pytest's full
`longreprtext` and any captured sections available on the report.

The final line always has this shape:

`TRIM: RUN=... VERDICT=... SCOPE=... ACTION=...`

This is protocol v1. v1 evolves additive-only: new enum values may appear for
existing keys. Any breaking change will use a new prefix such as `TRIM2:`, so
a v1 parser that anchors on `TRIM: ` will simply fail to find its prefix.

Field meanings:

- `RUN` is the coarse outcome category.
- `VERDICT` is a direct red/green/broken signal. Route on `VERDICT` alone for
  triage.
- `SCOPE` is the intended or resolved run scope after selection resolution.
- `ACTION` is the agent-facing next-step signal. Each value maps 1:1 to one
  operation, so routing entirely on `ACTION` is sufficient.

### Current `RUN` Values

- `COMPLETE`: ordinary completed runs that produced a usable behavior verdict,
  including normal test failures.
- `BROKEN`: recognized run-viability failures such as collection, import,
  setup, teardown, or config problems where the run needs repair first.
- `EMPTY`: selection resolved to zero tests.
- `ERROR`: pytest or a plugin crashed abnormally.
- `INTERRUPTED`: the run was explicitly interrupted, such as `Ctrl-C` or
  `pytest.exit(...)`.

### Current `VERDICT` Values

- `PASS`: green behavior verdict.
- `FAIL`: completed red result observed. This includes behavior failures and
  run-complete policy gates such as pure coverage-threshold failures.
- `BROKEN`: run viability was lost; no behavior verdict produced.
- `NONE`: no tests were selected.
- `UNKNOWN`: no trustworthy verdict can be derived.

### Current `SCOPE` Values

- `FULL`: full-suite target after selection resolution.
- `PARTIAL`: intentionally narrowed or mode-limited subset, such as explicit
  paths, `-k`, `-m`, `--lf` reruns, resumed or currently-stopped `--sw`, and
  similar subset-selection plugins.
- `NONE`: zero tests were selected to run.

### Current `ACTION` Values

- `DONE`: successful run; no follow-up needed.
- `EXPAND`: a failure-replay subset (`--lf`, `--ff`, `--sw`, `--stepwise`)
  passed; re-invoke against the full suite to confirm nothing else regressed.
- `FIX`: a meaningful user-fixable red result occurred; fix the behavior or
  unmet gate.
- `REPAIR`: the run has no usable verdict yet; restore runnability first
  (imports, syntax, fixtures, config).
- `ADJUST`: the selector or invocation needs editing.
- `INVESTIGATE`: the runner or tooling itself failed; escalate.
- `ABORT`: the run was halted externally; do not auto-retry.

## Operating Guidance

- Parse the last non-empty line first; anchor on the `TRIM: ` prefix.
- If `ACTION=FIX` and issue lines are present, use them as the actionable
  failures. This includes both broken product behavior and broken test
  behavior, such as stale assertions, wrong expected values, or buggy test
  helpers.
- If `ACTION=FIX` and no issue lines are present, inspect replayed plugin
  summary text before the final line. Pure `pytest-cov --cov-fail-under`
  failures currently work this way.
- If `ACTION=REPAIR`, repair the run first, then rerun the same pytest
  command.
- If `ACTION=EXPAND`, run one final full verification pass next.
- If `ACTION=ADJUST` (typically paired with `RUN=EMPTY`), edit the selection
  before rerunning.
- If `ACTION=INVESTIGATE`, stop automation and surface the runner/tooling
  crash.
- If `ACTION=ABORT`, stop; do not auto-retry an externally halted run.
- Treat `SCOPE` as target scope, not achieved verification completeness.
  Full-run `-x` and `--maxfail` still report `SCOPE=FULL`.
- If the original failing run targeted the full suite and you narrow to a
  partial rerun to iterate on a fix, do not treat
  `SCOPE=PARTIAL ACTION=DONE` as final verification. Run one final full-suite
  pass before declaring done.
- Do not expect default pytest progress output, summaries, warning sections, or
  verbose formatting while `--trim` is active.
- If an issue block includes an `artifact: <path>` line, open that file first for
  the full traceback and any captured stdout/stderr before deciding to rerun.
- If you expect artifacts to be useful and the filesystem is slow or
  network-backed, prefer a fast local directory. On Linux, a RAM-backed path
  such as `/dev/shm/pytest-trim` can be a good choice when available.
- Artifact files may contain tracebacks, locals, and captured output. Using a
  RAM-backed directory reduces persistence, but does not eliminate exposure
  during the run.
- Under `-s` / `--capture=no`, artifact files still contain the traceback, but
  stdout/stderr capture is unavailable; treat them as degraded mode.
- Cleanup is allowed only for directories the agent created specifically for the
  current run and no longer needs. Do not delete user-owned or
  project-persistent artifact directories unless the user asked for cleanup.
- If the compact failure headline plus detail lines are not enough to diagnose
  a failure, rerun the single failing nodeid without `--trim` to get the full
  pytest traceback, then return to `--trim` for the loop.

## Agent Loop Recipe

Use this recipe to avoid declaring a fix complete based on a narrowed rerun.

1. **Save the original command.** Record the full-suite invocation the user
   asked for, such as `poetry run pytest --trim --trim-artifacts`. This is the
   verification target.
2. **Run it.** Parse the final `TRIM: ...` line.
   - `ACTION=DONE` with `SCOPE=FULL` -> stop, green.
   - `ACTION=FIX` -> proceed to step 3.
   - `ACTION=REPAIR` -> fix runnability (imports/fixtures/config), rerun the
     original command.
   - `ACTION=ADJUST` -> the selector is wrong; fix it or escalate.
   - `ACTION=INVESTIGATE` or `ACTION=ABORT` -> stop and surface the problem.
3. **Narrow to iterate.** While fixing, you may rerun a subset (e.g. a
   specific nodeid, `-k`, or `--lf`) for speed.
4. **Do not stop on partial green.** A narrowed rerun that reports
   `SCOPE=PARTIAL ACTION=DONE` or `ACTION=EXPAND` is not final verification.
   It only proves the subset passes.
5. **Restore and rerun the saved full-suite command.** Only stop when the
   saved command returns `SCOPE=FULL ACTION=DONE`.

## Examples

```bash
pytest --trim --trim-artifacts
pytest --trim --trim-artifacts-dir=.pytest-trim
pytest --trim --trim-artifacts-dir=/dev/shm/pytest-trim
pytest --trim
poetry run pytest --trim --trim-artifacts
uv run pytest --trim --trim-artifacts
python -m pytest --trim --trim-artifacts
pytest --trim -k failing_test
pytest --trim --maxfail=1
pytest --trim --sw
pytest --trim --lf
```

## Source of Truth

If behavior seems inconsistent with this skill, check these files before
assuming the contract:

- `src/pytest_trim/plugin.py`
- `tests/test_plugin.py`
