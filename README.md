# pytest-trim

`pytest-trim` is a pytest plugin that emits compact, machine-friendly test
output. With `--trim`, it suppresses normal pytest terminal noise, prints one
compact block per issue, and normally finishes with a single machine-readable
protocol line.

## Quick Introduction

`pytest-trim` is not a new test runner and it does not change how pytest
executes tests. It is a thin output layer for pytest runs that makes the result
much easier to consume when you want signal over terminal chatter.

For a Python developer, the practical idea is simple:

- keep normal pytest semantics and exit codes
- hide most progress noise, headers, and long summaries
- print one compact block per relevant failure
- end with a stable final line that says what happened and what to do next

That makes it useful for fast local loops, wrapper scripts, CI adapters, and
agent-style workflows where the caller needs a compact answer rather than the
full pytest transcript.

If a skill-aware LLM or coding agent is working in this repository, see
[`skills/pytest-trim/SKILL.md`](skills/pytest-trim/SKILL.md) for repo-local
guidance on running `pytest-trim` and interpreting the final protocol line.

A normal passing run looks like this:

```text
RUN=COMPLETE VERDICT=PASS SCOPE=FULL ACTION=DONE
```

A failing run stays short:

```text
tests/test_example.py::test_breaks:12 - assert 1 == 2
RUN=COMPLETE VERDICT=FAIL SCOPE=FULL ACTION=FIX
```

Use regular pytest when you want the full debugging surface. Use
`pytest --trim` when you want a concise, dependable summary that is easy for
both humans and tools to scan.

## Install

The plugin is currently tested against pytest 8.x and 9.x.

```bash
pip install .
```

To use it from another local project:

```bash
pip install /path/to/pytest-trim
```

For editable development:

```bash
pip install -e /path/to/pytest-trim
```

## Usage

```bash
pytest --trim
```

Verbose pytest modes still work with the compact formatter:

```bash
pytest --trim -v
pytest --trim -vv
pytest --trim -vvv
pytest --trim --verbose
```

Stepwise workflow:

```bash
pytest --trim --sw --ff --nf
```

When the plugin is installed, pytest discovers it automatically through the
`pytest11` entry point.

For explicit loading:

```bash
pytest -p pytest_trim.plugin --trim
```

## Output Contract

With `--trim`, the plugin emits machine-friendly failure summaries once pytest has
successfully initialized the test run:

- Each failure starts with a headline line in the form `nodeid:lineno - message`
  when line numbers are available, otherwise `nodeid - message`.
- Rich assertion failures may add up to two indented `detail:` lines.
- When additional assertion detail is omitted, the last emitted detail line is
  `detail: (+N more details omitted)`.
- Verbose pytest flags such as `-v`, `-vv`, `-vvv`, and `--verbose` do not
  expose pytest's raw `Full diff:` block; `pytest-trim` keeps only the
  compact summary and filtered `detail:` lines.
- After pytest finishes its summary hooks, the final emitted line has this
  shape:
  `RUN=... VERDICT=... SCOPE=... ACTION=...`

All four keys are always present, always uppercase, and always emitted in that
order.

Field meanings:

- `RUN` is the coarse machine-readable run-state category.
- `VERDICT` is the behavior verdict when one was produced.
- `SCOPE` is the intended or resolved run scope after selection resolution. It
  is not a measure of achieved verification completeness.
- `ACTION` is the agent-facing next-step signal.

Current values:

- `RUN=COMPLETE` means the run produced a usable behavior verdict. This covers
  both green runs and ordinary red behavior failures.
- `RUN=BROKEN` means the run failed in a recognized run-viability way, such as
  collection/import/setup/teardown problems where the primary next step is to
  make the run runnable first.
- `RUN=NO_TESTS` means pytest collected or selected no tests.
- `RUN=ERROR` means pytest or a plugin crashed abnormally.
- `RUN=INTERRUPTED` means the run was interrupted explicitly, such as
  `Ctrl-C` or `pytest.exit(...)`.

- `VERDICT=PASS` means the run produced a passing behavior verdict.
- `VERDICT=FAIL` means the run produced a failing result or a broken run.
- `VERDICT=NONE` means no test verdict was produced because zero tests were
  selected.
- `VERDICT=UNKNOWN` means the run ended abnormally and the verdict cannot be
  trusted.

- `SCOPE=FULL` means the command was targeting the full suite after selection
  resolution. Full-run `-x` and `--maxfail` still report `SCOPE=FULL`.
- `SCOPE=PARTIAL` means the command intentionally targeted a narrowed or
  mode-limited subset, such as explicit paths or nodeids, `-k`, `-m`,
  `--lf` reruns of previous failures, resumed or currently-stopped `--sw`, and
  other subset-selection plugins such as testmon when they narrow the run.
- `SCOPE=NONE` means zero tests were selected to run.

- `ACTION=DONE` means no mode-implied follow-up pytest command is needed.
- `ACTION=RUN_FULL` means one final full verification pass should happen next.
- `ACTION=FIX` means tests ran meaningfully and found product or test-behavior
  failures.
- `ACTION=REPAIR_RUN` means the run is broken and needs to be made runnable
  first.
- `ACTION=ADJUST` means the invocation or selection is wrong or too narrow.
- `ACTION=STOP` means automatic continuation is unsafe or not useful.

Mixed-case policy:

- If at least one meaningful call-phase behavior failure occurred, the final
  line prefers `RUN=COMPLETE VERDICT=FAIL ACTION=FIX` even if teardown also
  failed.
- `RUN=BROKEN ACTION=REPAIR_RUN` is reserved for runs whose red result is
  primarily about run viability rather than behavior.

Notes:

- Normal pytest progress and summary output is hidden while `--trim` is active.
- Skips, xfails, non-strict xpasses, and deselections do not produce per-test
  output lines.
- Strict xpasses are treated as failures because pytest treats them as failures.
- Output written through pytest's terminal reporter stays hidden, including
  terminal-summary hooks that call `terminalreporter.write_line(...)`.
- Direct writes to stdout/stderr, such as `print(...)` in tests or hooks, may
  still appear before the final protocol line.
- The final protocol line is the authoritative machine-readable result for the
  run.
- CLI usage errors and very-early startup/configuration failures can happen
  before the plugin takes over terminal reporting; in those cases pytest may
  emit raw diagnostic output instead of a final protocol line.

## Examples

Single failing run:

```text
tests/test_example.py::test_breaks:12 - assert 1 == 2
RUN=COMPLETE VERDICT=FAIL SCOPE=FULL ACTION=FIX
```

Failing run with retained assertion detail:

```text
tests/test_example.py::test_list_diff:12 - assert [1, 2, 3] == [1, 2, 3, 4]
  detail: Right contains one more item: 4
RUN=COMPLETE VERDICT=FAIL SCOPE=FULL ACTION=FIX
```

Verbose run with filtered rich assertion details:

```text
tests/test_example.py::test_dict_diff:12 - assert {'a': 1, 'b': 2, 'c': 3} == {'a': 9, 'b': 8, 'c': 7}
  detail: Differing items: {'b': 2} != {'b': 8}
  detail: Differing items: {'c': 3} != {'c': 7}
  detail: (+1 more details omitted)
RUN=COMPLETE VERDICT=FAIL SCOPE=FULL ACTION=FIX
```

Run with capture disabled:

```text
some test output
RUN=COMPLETE VERDICT=PASS SCOPE=FULL ACTION=DONE
```

Stepwise run that stopped at the current failing test:

```text
tests/test_example.py::test_breaks:12 - assert False
RUN=COMPLETE VERDICT=FAIL SCOPE=PARTIAL ACTION=FIX
```

Stepwise run that reached the end:

```text
RUN=COMPLETE VERDICT=PASS SCOPE=PARTIAL ACTION=RUN_FULL
```

Clean pass:

```text
RUN=COMPLETE VERDICT=PASS SCOPE=FULL ACTION=DONE
```

Selector matched nothing:

```text
RUN=NO_TESTS VERDICT=NONE SCOPE=NONE ACTION=ADJUST
```

Internal pytest/plugin crash:

```text
RUN=ERROR VERDICT=UNKNOWN SCOPE=FULL ACTION=STOP
```

## Recommended Runner Loop

If you want a caller or agent to drive pytest automatically:

1. Start with:

   ```bash
   pytest --trim --sw --ff --nf
   ```

2. Read the last output line.

3. React as follows:

   - `ACTION=DONE`: stop. `SCOPE` already tells you whether the completed run
     was full or partial.
   - `ACTION=RUN_FULL`: run a final full pass, for example:

     ```bash
     pytest --trim
     ```

   - `ACTION=FIX`: fix the reported behavior failure(s), then rerun the same
     pytest command.
   - `ACTION=REPAIR_RUN`: repair the broken run state first, then rerun the
     same pytest command.
   - `ACTION=ADJUST`: change the selection or invocation before rerunning.
   - `ACTION=STOP`: stop and surface the abnormal interruption or crash.
