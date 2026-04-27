# pytest-trim

`pytest-trim` is a pytest plugin that emits compact, machine-friendly test
output to minimize transcript size and context load. With `--trim`, it
suppresses normal pytest terminal noise, prints one compact block per issue,
and normally finishes with a two-row machine-readable footer.

## Quick Introduction

`pytest-trim` is not a new test runner and it does not change how pytest
executes tests. It is a thin output layer for pytest runs that makes the result
much easier to consume when you want signal over terminal chatter.

Its purpose is context minimization, not runtime optimization. It does not make
pytest execute tests faster; it changes how much output a run emits and how easy
that output is to consume.

For a Python developer, the practical idea is simple:

- keep normal pytest semantics and exit codes
- hide most progress noise, headers, and long summaries
- print one compact block per relevant failure
- end with typed `TRIM:` rows that report counts and the final result

That makes it useful for fast local loops, wrapper scripts, CI adapters, and
agent-style workflows where the caller needs a compact answer rather than the
full pytest transcript.

If a skill-aware LLM or coding agent is working in this repository, see
[`skills/pytest-trim/SKILL.md`](skills/pytest-trim/SKILL.md) for repo-local
guidance on running `pytest-trim` and interpreting the footer rows.

A normal passing run looks like this:

```text
TRIM: counts selected=2 executed=2 passed=2 failed=0 errors=0 collection_errors=0 skipped=0 xfailed=0 xpassed=0 deselected=0
TRIM: result RUN=COMPLETE VERDICT=PASS SCOPE=FULL ACTION=DONE
```

A failing run stays really concise:

```text
tests/test_example.py::test_breaks:12 - assert 1 == 2

TRIM: counts selected=1 executed=1 passed=0 failed=1 errors=0 collection_errors=0 skipped=0 xfailed=0 xpassed=0 deselected=0
TRIM: result RUN=COMPLETE VERDICT=FAIL SCOPE=FULL ACTION=FIX
```

- Use regular pytest when you want the full debugging surface.
- Use `pytest --trim` when you want a concise, dependable summary that is easy
  for both humans and tools to scan.

## Install


```bash
pip install pytest-trim
poetry add pytest-trim="*"
uv add pytest-trim
```

## Usage

```bash
pytest --trim
```

With cached failure artifacts:

```bash
pytest --trim --trim-artifacts
pytest --trim --trim-artifacts-dir=.pytest-trim
```

Stepwise workflow:

```bash
pytest --trim --sw --ff --nf
```

## Output Contract

With `--trim`, the plugin emits machine-friendly failure summaries once pytest
has successfully initialized the test run:

- Each failure starts with a headline line in the form `nodeid:lineno - message`
  when line numbers are available, otherwise `nodeid - message`.
- Rich assertion failures may add up to two indented `detail:` lines.
- When additional assertion detail is omitted, the last emitted detail line is
  `detail: (+N more details omitted)`.
- If artifact caching is enabled, each emitted issue also includes an
  `artifact: <path>` line pointing at a per-failure text file under the pytest
  cache directory (or a user-specified directory).
- Verbosity flags such as `-v`, `-vv`, `-vvv`, and `--verbose` do not change
  the compact `--trim` output.
- After pytest finishes its summary hooks, the final emitted footer has this
  shape:
  `TRIM: counts selected=... executed=... passed=... failed=... errors=... collection_errors=... skipped=... xfailed=... xpassed=... deselected=...`
  followed by
  `TRIM: result RUN=... VERDICT=... SCOPE=... ACTION=...`

The final `TRIM: result ...` row is the authoritative machine-readable result
for the run and remains the final non-empty stdout line.

In short:

- `counts` gives item-oriented run-scale context.
- `RUN` is the coarse machine-readable run-state category.
- `VERDICT` is the direct red/green/broken behavior signal.
- `SCOPE` is the intended or resolved run scope after selection resolution.
- `ACTION` is the agent-facing next-step signal.

For the full protocol contract, including exact allowed values, precedence
rules, legal combinations, and design rationale, see
[`docs/specs/trim-protocol-v1.md`](docs/specs/trim-protocol-v1.md).

Notes:

- Normal pytest progress and summary output is hidden while `--trim` is active.
- Skips, xfails, non-strict xpasses, and deselections do not produce per-test
  output lines.
- Strict xpasses are treated as failures because pytest treats them as failures.
- Output written through pytest's terminal reporter stays hidden by default,
  including terminal-summary hooks that call
  `terminalreporter.write_line(...)`.
- `pytest-cov` terminal coverage sections are replayed before the footer block,
  so `pytest --trim --cov=...` still shows the coverage report.
- Direct writes to stdout/stderr, such as `print(...)` in tests or hooks, may
  still appear before the footer block.
- Artifact files include pytest's `longreprtext` and captured sections when
  capture is enabled. Under `-s` / `--capture=no`, the artifact still contains
  the traceback, but uncaptured stdout/stderr cannot be reconstructed.
- `pytest --trim --collect-only` suppresses the footer block because
  collection is not a behavior run.
- `--ff` reorders a full run; by itself it still reports `SCOPE=FULL` and, on
  pass, `ACTION=DONE`.
- CLI usage errors and very-early startup/configuration failures can happen
  before the plugin takes over terminal reporting; in those cases pytest may
  emit raw diagnostic output instead of footer rows.

## Examples

Single failing run:

```text
tests/test_example.py::test_breaks:12 - assert 1 == 2

TRIM: counts selected=1 executed=1 passed=0 failed=1 errors=0 collection_errors=0 skipped=0 xfailed=0 xpassed=0 deselected=0
TRIM: result RUN=COMPLETE VERDICT=FAIL SCOPE=FULL ACTION=FIX
```

Failing run with retained assertion detail:

```text
tests/test_example.py::test_list_diff:12 - assert [1, 2, 3] == [1, 2, 3, 4]
  detail: Right contains one more item: 4

TRIM: counts selected=1 executed=1 passed=0 failed=1 errors=0 collection_errors=0 skipped=0 xfailed=0 xpassed=0 deselected=0
TRIM: result RUN=COMPLETE VERDICT=FAIL SCOPE=FULL ACTION=FIX
```

Verbose run with filtered rich assertion details:

```text
tests/test_example.py::test_dict_diff:12 - assert {'a': 1, 'b': 2, 'c': 3} == {'a': 9, 'b': 8, 'c': 7}
  detail: Differing items: {'b': 2} != {'b': 8}
  detail: Differing items: {'c': 3} != {'c': 7}
  detail: (+1 more details omitted)

TRIM: counts selected=1 executed=1 passed=0 failed=1 errors=0 collection_errors=0 skipped=0 xfailed=0 xpassed=0 deselected=0
TRIM: result RUN=COMPLETE VERDICT=FAIL SCOPE=FULL ACTION=FIX
```

Run with capture disabled:

```text
some test output

TRIM: counts selected=1 executed=1 passed=1 failed=0 errors=0 collection_errors=0 skipped=0 xfailed=0 xpassed=0 deselected=0
TRIM: result RUN=COMPLETE VERDICT=PASS SCOPE=FULL ACTION=DONE
```

Stepwise run that stopped at the current failing test:

```text
tests/test_example.py::test_breaks:12 - assert False

TRIM: counts selected=2 executed=1 passed=0 failed=1 errors=0 collection_errors=0 skipped=0 xfailed=0 xpassed=0 deselected=0
TRIM: result RUN=COMPLETE VERDICT=FAIL SCOPE=PARTIAL ACTION=FIX
```

Stepwise run that reached the end:

```text
TRIM: counts selected=1 executed=1 passed=1 failed=0 errors=0 collection_errors=0 skipped=0 xfailed=0 xpassed=0 deselected=0
TRIM: result RUN=COMPLETE VERDICT=PASS SCOPE=PARTIAL ACTION=EXPAND
```

Clean pass:

```text
TRIM: counts selected=1 executed=1 passed=1 failed=0 errors=0 collection_errors=0 skipped=0 xfailed=0 xpassed=0 deselected=0
TRIM: result RUN=COMPLETE VERDICT=PASS SCOPE=FULL ACTION=DONE
```

Selector matched nothing:

```text
TRIM: counts selected=0 executed=0 passed=0 failed=0 errors=0 collection_errors=0 skipped=0 xfailed=0 xpassed=0 deselected=1
TRIM: result RUN=EMPTY VERDICT=NONE SCOPE=NONE ACTION=ADJUST
```

Internal pytest/plugin crash:

```text
TRIM: counts selected=0 executed=0 passed=0 failed=0 errors=0 collection_errors=0 skipped=0 xfailed=0 xpassed=0 deselected=0
TRIM: result RUN=ERROR VERDICT=UNKNOWN SCOPE=FULL ACTION=INVESTIGATE
```

External halt (Ctrl-C, `pytest.exit(...)`):

```text
TRIM: counts selected=1 executed=0 passed=0 failed=0 errors=0 collection_errors=0 skipped=0 xfailed=0 xpassed=0 deselected=0
TRIM: result RUN=INTERRUPTED VERDICT=UNKNOWN SCOPE=FULL ACTION=ABORT
```

## Recommended Runner Loop

If you want a caller or agent to drive pytest automatically:

1. Start with:

   ```bash
   pytest --trim --sw --ff --nf
   ```

2. Read the final `TRIM: result ...` row.

3. React as follows:

   - `ACTION=DONE`: stop. `SCOPE` already tells you whether the completed run
     was full or partial.
   - `ACTION=EXPAND`: run a final full pass, for example:

     ```bash
     pytest --trim --sw --ff --nf
     ```

   - `ACTION=FIX`: fix the reported failure(s) or unmet gate(s), then rerun
     the same pytest command.
   - `ACTION=REPAIR`: repair the broken run state first, then rerun the
     same pytest command.
   - `ACTION=ADJUST`: change the selection or invocation before rerunning.
   - `ACTION=INVESTIGATE`: stop automation; escalate the runner/tooling crash.
   - `ACTION=ABORT`: stop; do not auto-retry an externally halted run.
