---
name: pytest-trim
description: Use when running pytest in a Python project and the user wants compact, agent-friendly test output for debugging failures or iterating on fixes. Prefer pytest-trim over default pytest terminal output. Try `pytest --agent` first when the plugin may already be installed; if needed, retry with `pytest -p pytest_trim.plugin --agent`.
---

# Pytest Trim

Use this skill when you need concise pytest output that is easy for an agent to parse.

## When To Use It

- The user asks to run pytest with minimal or machine-friendly output.
- You are debugging test failures and want one line per issue plus a final status token.
- You are iterating with `pytest --sw` and need a compact loop signal.

## Command Selection

1. Prefer `pytest --agent ...` when the plugin may already be installed through pytest's plugin discovery.
2. If that does not activate the compact output, retry with `pytest -p pytest_trim.plugin --agent ...`.
3. If `pytest` rejects `--agent`, assume the plugin is not available in the current environment and fall back to normal pytest usage.

The plugin only changes output when `--agent` is present.

## Output Contract

Treat the final non-empty line as the status token. Any earlier non-empty lines are issue reports.

Issue lines are emitted in one of these forms:

- `nodeid:lineno - message`
- `nodeid - message`

This includes normal test failures and collection/setup/teardown failures.

Current status tokens:

- `PASS`: the run completed successfully with no reported issues.
- `FAIL`: one or more issues were emitted above.
- `REPEAT`: a `--sw` run stopped at a remembered failure. After fixing the problem, rerun the same stepwise command to continue.
- `RERUN`: a resumed `--sw` run reached the end after continuing from an earlier stepwise stop. This is distinct from a fresh full-run `PASS`.
- `NO_TESTS`: pytest collected no tests.
- `ERROR`: pytest hit an internal error.

## Operating Guidance

- Parse the last non-empty line first.
- If the status is `FAIL`, use the preceding issue lines as the actionable failures.
- If the status is `REPEAT`, keep the `--sw` loop and rerun after making a fix.
- If the status is `RERUN`, understand that the successful result came from a resumed stepwise run rather than a fresh run from the start.
- Do not expect default pytest progress output, summaries, warning sections, or verbose formatting while `--agent` is active.

## Examples

```bash
pytest --agent
pytest --agent -k failing_test
pytest --agent --maxfail=1
pytest --agent --sw
pytest -p pytest_trim.plugin --agent
```

## Source Of Truth

If behavior seems inconsistent with this skill, check these files before assuming the contract:

- `src/pytest_trim/plugin.py`
- `tests/test_plugin.py`
