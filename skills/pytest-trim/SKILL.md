---
name: pytest-trim
description: Use when working in a Python project where `pytest-trim` may be available and you need to run pytest with compact, machine-friendly output instead of normal terminal noise. Trigger when running tests, inspecting failures, or iterating on fixes would benefit from one issue block per failure plus a final `RUN=... VERDICT=... SCOPE=... ACTION=...` line. First try `pytest --trim`; if needed, retry with `pytest -p pytest_trim.plugin --trim`.
---

# Pytest Trim

Use this skill when you need concise pytest output that is easy for an agent to
parse.

If your tooling supports repo-local skills, this file describes how to invoke
`pytest-trim` and interpret its final protocol line.

## When To Use It

- The user asks to run pytest with minimal or machine-friendly output.
- The user asks to run or rerun pytest, and compact output would make the
  failures easier to act on.
- You are debugging test failures and want one line per issue plus a final protocol line.
- You are iterating with `pytest --sw` and need a compact loop signal.

## Command Selection

1. Prefer `pytest --trim ...` when the plugin may already be installed through pytest's plugin discovery.
2. If that does not activate the compact output, retry with `pytest -p pytest_trim.plugin --trim ...`.
3. If `pytest` rejects `--trim`, assume the plugin is not available in the current environment and fall back to normal pytest usage.

The plugin only changes output when `--trim` is present.

## Output Contract

Treat the final non-empty line as the protocol line. Any earlier non-empty lines are issue reports.

Issue lines are emitted in one of these forms:

- `nodeid:lineno - message`
- `nodeid - message`

This includes normal test failures and collection/setup/teardown failures.

The final line always has this shape:

`RUN=... VERDICT=... SCOPE=... ACTION=...`

Fields:

- `RUN` is the coarse outcome category.
- `VERDICT` is the behavior verdict when one was produced.
- `SCOPE` is the intended or resolved run scope after selection resolution.
- `ACTION` is the agent-facing next-step signal.

Current `RUN` values:

- `COMPLETE`: ordinary completed runs that produced a usable behavior verdict,
  including normal test failures.
- `BROKEN`: recognized run-viability failures such as collection, import,
  setup, or teardown problems where the run needs repair first.
- `NO_TESTS`: pytest collected or selected no tests.
- `ERROR`: pytest or a plugin crashed abnormally.
- `INTERRUPTED`: the run was explicitly interrupted, such as `Ctrl-C` or `pytest.exit(...)`.

Current `VERDICT` values:

- `PASS`
- `FAIL`
- `NONE`
- `UNKNOWN`

Current `SCOPE` values:

- `FULL`: full-suite target after selection resolution.
- `PARTIAL`: intentionally narrowed or mode-limited subset, such as explicit
  paths, `-k`, `-m`, `--lf` reruns, resumed or currently-stopped `--sw`, and
  similar subset-selection plugins.
- `NONE`: zero tests were selected to run.

Current `ACTION` values:

- `DONE`: no mode-implied follow-up pytest command.
- `RUN_FULL`: one final full verification pass should happen next.
- `FIX`: tests ran meaningfully and found product or test-behavior failures.
- `REPAIR_RUN`: the run is broken and needs to be made runnable first.
- `ADJUST`: the invocation or selection is wrong or too narrow.
- `STOP`: automatic continuation is unsafe or not useful.

## Operating Guidance

- Parse the last non-empty line first.
- If `ACTION=FIX`, use the preceding issue lines as the actionable failures.
- If `ACTION=REPAIR_RUN`, repair the run first, then rerun the same pytest command.
- If `ACTION=RUN_FULL`, run one final full verification pass next.
- If `RUN=NO_TESTS`, adjust the selection before rerunning.
- If `RUN=ERROR` or `RUN=INTERRUPTED`, stop and surface the abnormal condition.
- Treat `SCOPE` as target scope, not achieved verification completeness. Full-run
  `-x` and `--maxfail` still report `SCOPE=FULL`.
- If any call-phase behavior failure is present, prefer the `RUN=COMPLETE
  VERDICT=FAIL ACTION=FIX` interpretation even if teardown also failed.
- Do not expect default pytest progress output, summaries, warning sections, or verbose formatting while `--trim` is active.

## Examples

```bash
pytest --trim
pytest --trim -k failing_test
pytest --trim --maxfail=1
pytest --trim --sw
pytest -p pytest_trim.plugin --trim
```

## Source Of Truth

If behavior seems inconsistent with this skill, check these files before assuming the contract:

- `src/pytest_trim/plugin.py`
- `tests/test_plugin.py`
