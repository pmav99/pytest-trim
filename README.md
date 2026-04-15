# pytest-trim

`pytest-trim` is a pytest plugin that emits compact, machine-friendly test
output. With `--agent`, it suppresses normal pytest terminal noise, prints one
compact block per issue, and normally finishes with a single status token.

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
pytest --agent
```

Verbose pytest modes still work with the compact formatter:

```bash
pytest --agent -v
pytest --agent -vv
pytest --agent -vvv
pytest --agent --verbose
```

Stepwise workflow:

```bash
pytest --agent --sw --ff --nf
```

When the plugin is installed, pytest discovers it automatically through the
`pytest11` entry point.

For explicit loading:

```bash
pytest -p pytest_trim.plugin --agent
```

## Output Contract

With `--agent`, the plugin emits machine-friendly failure summaries once pytest has
successfully initialized the test run:

- Each failure starts with a headline line in the form `nodeid:lineno - message`
  when line numbers are available, otherwise `nodeid - message`.
- Rich assertion failures may add up to two indented `detail:` lines.
- When additional assertion detail is omitted, the last emitted detail line is
  `detail: (+N more details omitted)`.
- Verbose pytest flags such as `-v`, `-vv`, `-vvv`, and `--verbose` do not
  expose pytest's raw `Full diff:` block; `pytest-trim` keeps only the
  compact summary and filtered `detail:` lines.
- After pytest finishes its summary hooks, the final emitted line is one status
  token:
  `PASS`, `FAIL`, `REPEAT`, `RERUN`, `NO_TESTS`, or `ERROR`.

Status meanings:

- `PASS`: the current invocation completed successfully.
- `FAIL`: normal test or collection failures occurred; inspect the preceding
  issue lines.
- `REPEAT`: rerun the same stepwise command again.
- `RERUN`: the stepwise run reached the end; now run the full suite once.
- `NO_TESTS`: pytest collected or selected no tests.
- `ERROR`: an abnormal pytest failure occurred outside the normal test-failure
  path.

Notes:

- Normal pytest progress and summary output is hidden while `--agent` is active.
- Skips, xfails, non-strict xpasses, and deselections do not produce per-test
  output lines.
- Strict xpasses are treated as failures because pytest treats them as failures.
- Output written through pytest's terminal reporter stays hidden, including
  terminal-summary hooks that call `terminalreporter.write_line(...)`.
- Direct writes to stdout/stderr, such as `print(...)` in tests or hooks, may
  still appear before the final status token.
- The final status token is the authoritative machine-readable result for the
  run.
- CLI usage errors and very-early startup/configuration failures can happen
  before the plugin takes over terminal reporting; in those cases pytest may
  emit raw diagnostic output instead of a final status token.

## Examples

Single failing run:

```text
tests/test_example.py::test_breaks:12 - assert 1 == 2
FAIL
```

Failing run with retained assertion detail:

```text
tests/test_example.py::test_list_diff:12 - assert [1, 2, 3] == [1, 2, 3, 4]
  detail: Right contains one more item: 4
FAIL
```

Verbose run with filtered rich assertion details:

```text
tests/test_example.py::test_dict_diff:12 - assert {'a': 1, 'b': 2, 'c': 3} == {'a': 9, 'b': 8, 'c': 7}
  detail: Differing items: {'b': 2} != {'b': 8}
  detail: Differing items: {'c': 3} != {'c': 7}
  detail: (+1 more details omitted)
FAIL
```

Run with capture disabled:

```text
some test output
PASS
```

Stepwise run that should be repeated:

```text
tests/test_example.py::test_breaks:12 - assert False
REPEAT
```

Stepwise run that reached the end:

```text
RERUN
```

Clean pass:

```text
PASS
```

## Recommended Runner Loop

If you want a caller or agent to drive pytest automatically:

1. Start with:

   ```bash
   pytest --agent --sw --ff --nf
   ```

2. Read the last output line.

3. React as follows:

   - `PASS`: stop, the run succeeded.
   - `FAIL`: stop and report the preceding issue block(s).
   - `REPEAT`: run the same stepwise command again.
   - `RERUN`: run a final full pass, for example:

     ```bash
     pytest --agent
     ```

   - `NO_TESTS`: stop and report that no tests were collected or selected.
   - `ERROR`: stop and report the abnormal pytest failure.
