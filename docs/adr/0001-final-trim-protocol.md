# ADR 0001: Final `--trim` Protocol

- Status: Accepted
- Date: 2026-04-17
- Protocol version: v1

## Context

`pytest-trim` started with a single-token final-line protocol such as `PASS`,
`FAIL`, `REPEAT`, and `RERUN`. That protocol was easy to scan but too
ambiguous for agent workflows:

- it mixed run category, red/green result, and next-step guidance into one token
- it did not expose a direct green/red signal without overloading the status
- it did not cleanly distinguish ordinary failing test behavior from a broken run
- it did not separate intended run scope from run outcome

A later iteration introduced separate status, action, and completeness fields,
but `OK` was too success-coded for a primary run-state field, `COMPLETENESS`
mixed scope-like values (`FULL`, `PARTIAL`) with non-scope-like values
(`UNKNOWN`), and there was still no explicit red/green field.

This ADR defines the final v1 protocol for `--trim`.

## Decision

The final non-empty line emitted by `pytest --trim` on stdout takes this exact
form:

```text
TRIM: RUN=<value> VERDICT=<value> SCOPE=<value> ACTION=<value>
```

### Wire format

- **Prefix:** literal `TRIM: ` (uppercase, colon, single space). Parsers
  anchor on this prefix to locate the line in mixed pytest output.
- **Stream:** stdout. Same stream as pytest's own summary, so a single
  capture or tee picks up both.
- **Encoding:** ASCII only. All values match `[A-Z_]+`.
- **Separator:** single ASCII space between `key=value` pairs.
- **Order:** exactly the four keys above, in that order, with no extras and
  no omissions.
- **Termination:** single trailing newline.

### Versioning

This is protocol v1. v1 commits to **additive-only evolution**: future patch
releases may introduce new enum values for existing keys, and naive parsers
that match on known values and ignore unknown ones will continue to work.

Any breaking change (renaming a key, removing a value, reordering, adding a
required key) requires a new prefix (e.g. `TRIM2:`). A v1 parser will simply
fail to find its prefix and stop cleanly, instead of silently misclassifying.

### Suppression

`pytest --trim --collect-only` does **not** emit a protocol line. Collection
is not a behavior run.

Under `pytest-xdist`, only the coordinator emits the protocol line. Workers
stay silent.

## Vocabulary

### `RUN`

Describes what broad kind of run termination happened.

| Value | Meaning |
| --- | --- |
| `COMPLETE` | The run produced a usable behavior verdict, including both green runs and ordinary red behavior failures. |
| `BROKEN` | The run failed in a recognized run-viability way (collection error, import failure, fixture setup, config error). The next step is to repair the run before trusting it for behavior verification. |
| `EMPTY` | Selection resolved to zero tests. Covers both selectors that matched nothing and runs where no tests were defined. |
| `ERROR` | Pytest, a plugin, or the protocol machinery failed abnormally. Output may be unreliable. |
| `INTERRUPTED` | The run was intentionally or externally stopped, for example by `Ctrl-C` or `pytest.exit(...)`. |

### `VERDICT`

Direct red/green/broken signal for the run. An agent can route on `VERDICT`
alone for green/red triage, without consulting `RUN`.

| Value | Meaning |
| --- | --- |
| `PASS` | The run produced a green behavior verdict. |
| `FAIL` | A behavior failure was observed (assertion, unexpected exception, strict xpass, warnings-as-errors triggered). |
| `BROKEN` | No behavior verdict was produced because run viability was lost (collection / import / fixture / config). |
| `NONE` | No behavior verdict applies because no tests were selected. |
| `UNKNOWN` | No trustworthy verdict can be derived (runner crash, external interrupt). |

### `SCOPE`

Describes the intended or resolved run scope, not achieved verification
completeness.

| Value | Meaning |
| --- | --- |
| `FULL` | The command targeted a full-suite run after selection resolution. |
| `PARTIAL` | The command targeted a narrowed or mode-limited subset. |
| `NONE` | Selection resolved to zero tests. |

Examples:

| Example | `SCOPE` |
| --- | --- |
| plain `pytest --trim` | `FULL` |
| `pytest --trim -k expr` | `PARTIAL` |
| `pytest --trim some_test.py` | `PARTIAL` |
| `pytest --trim --lf` rerunning previous failures | `PARTIAL` |
| `pytest --trim --sw` resuming from a remembered failure | `PARTIAL` |
| `pytest --trim --lf --lfnf=none` with no cached failures | `NONE` |

#### `SCOPE` for `ERROR` and `INTERRUPTED`

`SCOPE` reflects the resolved selection at the point of termination:

- if collection completed → `FULL` or `PARTIAL` per resolved selection
- if the run crashed before collection resolved → infer from the CLI:
  `FULL` if no narrowing flags were present, otherwise `PARTIAL`
- `NONE` only if selection explicitly resolved to zero tests

Early termination via `-x` / `--exitfirst` does **not** retroactively narrow
`SCOPE` — the user-requested scope is preserved.

### `ACTION`

The agent-facing next-step signal. Each value maps 1:1 to one operation, so
an agent can route entirely on `ACTION`; the other fields are diagnostics.

| Value | Meaning |
| --- | --- |
| `DONE` | Successful run. No follow-up needed. |
| `EXPAND` | A failure-replay subset (`--lf`, `--ff`, `--sw`, `--stepwise`) passed. Re-invoke `pytest --trim` against the full suite to confirm nothing else regressed. |
| `FIX` | A meaningful behavior-level failure occurred. Fix the failing behavior. |
| `REPAIR` | The run did not yet provide a usable behavior verdict; restore runnability first (fix imports, syntax, fixtures, config). |
| `ADJUST` | The selector or invocation needs editing (typo, over-narrow filter, wrong path). |
| `INVESTIGATE` | The runner or tooling itself failed. Escalate; output may be unreliable. |
| `ABORT` | The run was halted externally. Do not auto-retry; the halt was intentional. |

#### `EXPAND` rule

`ACTION=EXPAND` is emitted only when the selection mode is a **failure-replay
shortcut** — i.e. the subset is derived from cached failures from a prior
run. Specifically: `--lf`, `--ff`, `--sw`, `--stepwise`. Passing such a
subset does not constitute a green verdict for the suite, so a follow-up
full run is required.

All other partial selections (explicit `-k`, file path, node id, marker
expression, impact-based modes like `testmon`) emit `ACTION=DONE` on pass,
because the subset *is* the user's intended verification target.

## Distinctions

### `BROKEN` vs `ERROR`

Use `RUN=BROKEN` for recognized, expected pytest failure modes where the
output is still meaningful and the main problem is run viability.

Typical `BROKEN` cases:

- syntax error from a bad patch
- import or collection failure
- fixture setup failure
- teardown failure that invalidates the run as a behavior check
- malformed `pytest.ini` / `pyproject.toml` config
- conftest import error

Use `RUN=ERROR` only for abnormal runner or tooling malfunction.

Typical `ERROR` cases:

- internal pytest error
- plugin crash
- protocol bug
- abnormal failures where output may be unreliable

Mnemonic:

- `BROKEN` = the project / test run broke
- `ERROR` = the runner / tooling broke

### `FIX` vs `REPAIR`

Use `ACTION=FIX` when the run told us something meaningful about behavior
and the result was red.

Typical `FIX` cases:

- assertion failure
- unexpected exception in the test call phase
- strict `XPASS`
- warnings-as-errors (`-W error::X`) triggered during a test

Use `ACTION=REPAIR` when the red result does not yet provide a usable
behavior verdict and the run must be made viable first.

Typical `REPAIR` cases:

- syntax error from a bad patch
- import or collection failure
- setup failure before meaningful test execution
- teardown / setup problems whose primary meaning is that the run is not
  yet trustworthy
- bad config or conftest import

Mnemonic:

- `FIX` = fix behavior
- `REPAIR` = repair the run

### `INVESTIGATE` vs `ABORT`

- `INVESTIGATE` = the runner crashed or behaved abnormally; a human (or
  higher-capability agent) should look at what went wrong before retrying.
- `ABORT` = the run was halted on purpose (Ctrl-C, `pytest.exit(...)`);
  auto-retrying would fight the user's intent.

### Mixed failure precedence

When multiple failure modes occur in the same run, classify in this order
(first match wins):

1. abnormal runner / plugin crash → `RUN=ERROR`
2. external interrupt → `RUN=INTERRUPTED`
3. at least one meaningful call-phase behavior failure (assertion,
   exception, strict xpass) → `RUN=COMPLETE VERDICT=FAIL ACTION=FIX`,
   even if teardown or collection of unrelated tests also failed
4. otherwise, if any collection / import / fixture / config failure
   prevented behavior verdicts for all selected tests → `RUN=BROKEN`
5. all selected tests passed → `RUN=COMPLETE VERDICT=PASS`
6. zero tests selected → `RUN=EMPTY`

## Legal combinations

Exactly the following eight combination shapes are valid v1 lines. Anything
outside this table is a protocol bug.

| RUN | VERDICT | SCOPE | ACTION | When |
| --- | --- | --- | --- | --- |
| `COMPLETE` | `PASS` | `FULL` | `DONE` | full suite green |
| `COMPLETE` | `PASS` | `PARTIAL` | `DONE` | explicit subset green (`-k`, file, node id, marker, `testmon`) |
| `COMPLETE` | `PASS` | `PARTIAL` | `EXPAND` | failure-replay subset green (`--lf`, `--ff`, `--sw`, `--stepwise`) |
| `COMPLETE` | `FAIL` | `FULL` \| `PARTIAL` | `FIX` | behavior failure |
| `BROKEN` | `BROKEN` | `FULL` \| `PARTIAL` | `REPAIR` | collection / import / fixture / config broke run |
| `EMPTY` | `NONE` | `NONE` | `ADJUST` | selection resolved to zero |
| `ERROR` | `UNKNOWN` | `FULL` \| `PARTIAL` \| `NONE` | `INVESTIGATE` | runner / plugin / protocol crash |
| `INTERRUPTED` | `UNKNOWN` | `FULL` \| `PARTIAL` \| `NONE` | `ABORT` | Ctrl-C, `pytest.exit(...)` |

## Agent decision table

`ACTION` is a complete control signal. Routing logic for an automated agent:

| `ACTION` | Agent next step |
| --- | --- |
| `DONE` | Exit success; no further pytest invocation. |
| `EXPAND` | Re-invoke `pytest --trim` against the full suite. |
| `FIX` | Edit code under test to address the behavior failure; retry. |
| `REPAIR` | Edit imports / config / fixtures / syntax to restore runnability; retry. |
| `ADJUST` | Revise the selector (fix typo, broaden filter, correct path); retry. |
| `INVESTIGATE` | Stop automation; escalate to a human or higher-capability agent. |
| `ABORT` | Stop automation; do not retry. |

`RUN`, `VERDICT`, and `SCOPE` are diagnostic context for logs, dashboards,
and humans reading output. They are not required for routing.

## Special cases

- **`--collect-only`**: protocol line suppressed.
- **`pytest-xdist`**: only the coordinator emits; workers stay silent.
- **Warnings-as-errors** (`-W error::X`) triggered in a test: classified
  as a call-phase failure → `ACTION=FIX`.
- **Non-strict xpass**: pytest treats as pass; protocol reports
  `VERDICT=PASS`.
- **Selector matched nothing vs no tests defined**: both → `RUN=EMPTY`.
  Pytest does not distinguish at exit; the protocol does not either.
- **Bad `pytest.ini` / `pyproject.toml`**: `RUN=BROKEN` (user-fixable),
  not `RUN=ERROR` (runner malfunction).
- **conftest import failure**: `RUN=BROKEN`, same repair path as test
  import failure.
- **`-x` / `--exitfirst` early stop**: `SCOPE` keeps the user-requested
  value; early termination does not retroactively narrow it.

## Consequences

- Agents get a direct red/green/broken field through `VERDICT`.
- `ACTION` is a complete agent control signal — one value per next step.
- Scope is explicit and no longer overloaded with "unknown completeness"
  semantics.
- Run viability is distinguished from abnormal runner failure.
- The legal-combinations table makes the protocol mechanically verifiable:
  implementations and parsers can assert against eight fixed shapes.
- The `TRIM:` prefix and additive-only evolution rule let naive parsers
  (`grep '^TRIM: ' | awk`) keep working across future v1 additions.

## Out of scope

This ADR does not define:

- the future `--trim-details` option
- compact vs full assertion-detail modes
- any backward compatibility layer for older final-line protocols
