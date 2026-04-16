# ADR 0001: Final `--trim` Protocol Uses `RUN`, `VERDICT`, `SCOPE`, and `ACTION`

- Status: Accepted
- Date: 2026-04-16

## Context

`pytest-trim` started with a single-token final-line protocol such as `PASS`,
`FAIL`, `REPEAT`, and `RERUN`.

That protocol was easy to scan, but it was too ambiguous for agent workflows:

- it mixed run category, red/green result, and next-step guidance into one token
- it did not expose a direct green/red signal without overloading the status
- it did not cleanly distinguish ordinary failing test behavior from a broken run
- it did not separate intended run scope from run outcome

A later structured direction based on separate status, action, and completeness
fields improved this, but the chosen names still had problems:

- `OK` was too success-coded for the primary run-state field
- `COMPLETENESS` mixed scope-like values (`FULL`, `PARTIAL`) with
  non-scope-like values (`UNKNOWN`)
- there was still no explicit red/green field

This ADR defines the final protocol vocabulary for `--trim`.

## Decision

The final non-empty line emitted by `pytest --trim` will use this exact key
order:

```text
RUN=... VERDICT=... SCOPE=... ACTION=...
```

All four keys are mandatory.

The protocol does not preserve backward compatibility with:

- the old single-token final-line protocol
- the intermediate structured protocol that used the older status, action, and
  completeness field names

Process exit codes remain unchanged. The protocol line is richer than pytest's
numeric exit code and is not a one-to-one copy of it.

## Vocabulary

### `RUN`

`RUN` describes what broad kind of run termination happened.

| Value | Meaning |
| --- | --- |
| `COMPLETE` | The run produced a usable behavior verdict, including both green runs and ordinary red behavior failures. |
| `BROKEN` | The run failed in a recognized run-viability way, so the next step is to repair the run before trusting it for behavior verification. |
| `NO_TESTS` | Selection resolved to zero tests to run. |
| `ERROR` | Pytest, a plugin, or the protocol machinery failed abnormally, so output may be unreliable. |
| `INTERRUPTED` | The run was intentionally or externally stopped, for example by `Ctrl-C` or `pytest.exit(...)`. |

### `VERDICT`

`VERDICT` provides the direct green/red signal.

| Value | Meaning |
| --- | --- |
| `PASS` | The run produced a green behavior verdict. |
| `FAIL` | The run produced a red result, either because behavior failed or because the run was broken in a recognized way. |
| `NONE` | No behavior verdict exists because no tests were selected to run. |
| `UNKNOWN` | No trustworthy verdict can be derived. |

### `SCOPE`

`SCOPE` describes the intended or resolved run scope, not achieved
verification completeness.

| Value | Meaning |
| --- | --- |
| `FULL` | The command targeted a full-suite run after selection resolution. |
| `PARTIAL` | The command targeted a narrowed or mode-limited subset. |
| `NONE` | Selection resolved to zero tests. |

`SCOPE` is mandatory even for `RUN=ERROR` and `RUN=INTERRUPTED`, because it
describes the intended run scope rather than how much useful verification was
achieved.

Examples:

| Example | `SCOPE` |
| --- | --- |
| plain `pytest --trim` | `FULL` |
| `pytest --trim -k expr` | `PARTIAL` |
| `pytest --trim some_test.py` | `PARTIAL` |
| `pytest --trim --lf` rerunning previous failures | `PARTIAL` |
| `pytest --trim --sw` resuming from a remembered failure | `PARTIAL` |
| `pytest --trim --lf --lfnf=none` with no cached failures | `NONE` |
| full-suite interrupt or internal error | usually `FULL` |

### `ACTION`

`ACTION` is the agent-facing next-step signal.

| Value | Meaning |
| --- | --- |
| `DONE` | Successful run, with no mode-implied follow-up pytest command. |
| `RUN_FULL` | Partial success where one full verification pass should happen next. |
| `FIX` | The run exposed a meaningful behavior-level failure, so the failing behavior should be fixed. |
| `REPAIR_RUN` | The run did not yet provide a usable behavior verdict, so runnability must be restored first. |
| `ADJUST` | The invocation or selection is wrong or too narrow. |
| `STOP` | Automatic continuation is unsafe or not useful. |

## Distinctions

### `BROKEN` vs `ERROR`

Use `RUN=BROKEN` for recognized, expected pytest failure modes where the output
is still meaningful and the main problem is run viability.

Typical `BROKEN` cases:

- syntax error from a bad patch
- import or collection failure
- fixture setup failure
- teardown failure that invalidates the run as a behavior check

Use `RUN=ERROR` only for abnormal runner or tooling malfunction.

Typical `ERROR` cases:

- internal pytest error
- plugin crash
- protocol bug
- other abnormal failures where output may be unreliable

Mnemonic:

- `BROKEN` = the project/test run broke
- `ERROR` = the runner/tooling broke

### `FIX` vs `REPAIR_RUN`

Use `ACTION=FIX` when the run told us something meaningful about behavior and
the result was red.

Typical `FIX` cases:

- assertion failure
- unexpected exception in the test call phase
- strict `XPASS`

Use `ACTION=REPAIR_RUN` when the red result does not yet provide a usable
behavior verdict and the run must be made viable first.

Typical `REPAIR_RUN` cases:

- syntax error from a bad patch
- import or collection failure
- setup failure before meaningful test execution
- teardown/setup problems whose primary meaning is that the run is not yet
  trustworthy

Mnemonic:

- `FIX` = fix behavior
- `REPAIR_RUN` = repair the run

### Mixed failure precedence

If at least one meaningful call-phase behavior failure occurred, prefer:

```text
RUN=COMPLETE VERDICT=FAIL ACTION=FIX
```

even if teardown also failed.

Reserve:

```text
RUN=BROKEN VERDICT=FAIL ACTION=REPAIR_RUN
```

for runs whose red result is primarily about run viability rather than exposed
behavior.

## Canonical mappings

- full pass

  ```text
  RUN=COMPLETE VERDICT=PASS SCOPE=FULL ACTION=DONE
  ```

- targeted pass (`-k`, file path, nodeid, markers, `testmon`, similar subset selection)

  ```text
  RUN=COMPLETE VERDICT=PASS SCOPE=PARTIAL ACTION=DONE
  ```

- `--lf` passes after rerunning previous failures

  ```text
  RUN=COMPLETE VERDICT=PASS SCOPE=PARTIAL ACTION=RUN_FULL
  ```

- resumed `--sw` reaches the end

  ```text
  RUN=COMPLETE VERDICT=PASS SCOPE=PARTIAL ACTION=RUN_FULL
  ```

- normal assertion or runtime failure after meaningful execution

  ```text
  RUN=COMPLETE VERDICT=FAIL SCOPE=FULL|PARTIAL ACTION=FIX
  ```

- syntax, import, or collection failure

  ```text
  RUN=BROKEN VERDICT=FAIL SCOPE=FULL|PARTIAL ACTION=REPAIR_RUN
  ```

- setup or teardown failure without a usable behavior verdict

  ```text
  RUN=BROKEN VERDICT=FAIL SCOPE=FULL|PARTIAL ACTION=REPAIR_RUN
  ```

- selector matched nothing

  ```text
  RUN=NO_TESTS VERDICT=NONE SCOPE=NONE ACTION=ADJUST
  ```

- internal pytest or plugin crash

  ```text
  RUN=ERROR VERDICT=UNKNOWN SCOPE=FULL|PARTIAL|NONE ACTION=STOP
  ```

- `Ctrl-C` or `pytest.exit(...)`

  ```text
  RUN=INTERRUPTED VERDICT=UNKNOWN SCOPE=FULL|PARTIAL|NONE ACTION=STOP
  ```

## Consequences

- Agents get a direct red/green field through `VERDICT`.
- Scope is explicit and no longer overloaded with "unknown completeness"
  semantics.
- Run viability is distinguished from abnormal runner failure.
- The final protocol becomes easier to parse consistently because each field has
  one job.

## Out of scope

This ADR does not define:

- the future `--trim-details` option
- compact vs full assertion-detail modes
- any backward compatibility layer for older final-line protocols
