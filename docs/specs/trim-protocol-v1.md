# `TRIM:` Protocol v1

This document is the authoritative specification for the machine-readable
footer emitted by `pytest --trim`.

## Specification

### Footer block

For every non-`--collect-only` run that reaches trim reporting, `pytest --trim`
emits this typed footer block on stdout:

```text
TRIM: counts selected=<n> executed=<n> passed=<n> failed=<n> errors=<n> collection_errors=<n> skipped=<n> xfailed=<n> xpassed=<n> deselected=<n>
TRIM: result RUN=<value> VERDICT=<value> SCOPE=<value> ACTION=<value>
```

The `TRIM: result ...` row is the final non-empty stdout line.

### Wire format

- **Prefix:** literal `TRIM: ` (uppercase, colon, single space). Parsers
  anchor on this prefix to locate typed protocol rows in mixed pytest output.
- **Row type:** the first token after `TRIM: `. v1 row types are `counts` and
  `result`.
- **Stream:** stdout. Same stream as pytest's own summary, so a single
  capture or tee picks up both.
- **Encoding:** ASCII only. Result values match `[A-Z_]+`; counts are
  non-negative base-10 integers.
- **Separator:** single ASCII space between `key=value` pairs.
- **Order:** exactly the keys shown above, in that order, with no extras and no
  omissions.
- **Termination:** single trailing newline.

### Versioning

This is protocol v1. v1 commits to additive-only evolution: future patch
releases may introduce new result enum values for existing keys, and parsers
that match on known values and ignore unknown ones will continue to work.

Any breaking change requires a new prefix such as `TRIM2:`. A v1 parser will
simply fail to find its prefix instead of silently misclassifying the line.

### Emission rules

- `pytest --trim --collect-only` does not emit protocol rows. Collection is
  not a behavior run.
- Under `pytest-xdist`, only the coordinator emits protocol rows. Workers
  stay silent.
- If issue, diagnostic, direct stdout, or replayed plugin-summary output
  precedes the footer block, one blank line separates that output from the
  `TRIM: counts ...` row.
- If no output precedes the footer block, there is no leading blank line.

### `counts`

`counts` gives item-oriented run-scale context. The exact key order is:

```text
selected executed passed failed errors collection_errors skipped xfailed xpassed deselected
```

Meanings:

| Key | Meaning |
| --- | --- |
| `selected` | Post-deselection item count the run intended to execute. If collection or runner failure prevents selection from resolving, this is `0`. |
| `executed` | Sum of `passed + failed + errors + skipped + xfailed + xpassed`. |
| `passed` | Selected items whose call phase passed normally. |
| `failed` | Selected items with call-phase behavior failures, including strict unexpected passes. |
| `errors` | Selected items with setup or teardown failures. |
| `collection_errors` | Collection or import failures. This does not contribute to `selected`, `executed`, or `errors`. |
| `skipped` | Ordinary skipped selected items. |
| `xfailed` | Expected failures. |
| `xpassed` | Non-strict unexpected passes. |
| `deselected` | Items removed by deselection. This does not contribute to `selected` or `executed`. |

Each executed selected item contributes to exactly one of `passed`, `failed`,
`errors`, `skipped`, `xfailed`, or `xpassed`. If one item produces multiple
pytest reports, assign it to the most severe observed outcome:

```text
errors > failed > xpassed > xfailed > skipped > passed
```

Early-stop runs such as `-x`, `--maxfail=1`, and `--sw` may report
`executed < selected`. The difference is the number of selected items that did
not execute; v1 intentionally has no `unexecuted` key.

`RUN=ERROR`, `RUN=INTERRUPTED`, and usage-error result rows emit counts with
whatever partial state was observed before termination. If no item selection or
reports were observed, all counts are zero. CLI usage errors that happen before
trim reporting initializes remain out of scope and emit no trim footer rows.

For collection errors that prevent global selection from resolving, `selected`
is `0` and item outcome buckets remain `0`; `collection_errors` carries the
collection/import failure count. This keeps the counts row tied to the resolved
selection, even in distributed runs where a worker may have already started an
item before another worker reported a collection failure.

### `RUN`

`RUN` describes what broad kind of run termination happened.

| Value | Meaning |
| --- | --- |
| `COMPLETE` | The run produced a usable completed verdict, including both green runs and user-fixable red outcomes that still produced a trustworthy result. |
| `BROKEN` | The run failed in a recognized run-viability way (collection error, import failure, fixture setup, config error). The next step is to repair the run before trusting it for behavior verification. |
| `EMPTY` | Selection resolved to zero tests. Covers both selectors that matched nothing and runs where no tests were defined. |
| `ERROR` | Pytest, a plugin, or the protocol machinery failed abnormally. Output may be unreliable. |
| `INTERRUPTED` | The run was intentionally or externally stopped, for example by `Ctrl-C` or `pytest.exit(...)`. |

### `VERDICT`

`VERDICT` is the direct red/green/broken signal for the run.

| Value | Meaning |
| --- | --- |
| `PASS` | The run produced a green behavior verdict. |
| `FAIL` | The run completed red in a user-fixable way (assertion, unexpected exception, strict xpass, warnings-as-errors triggered, or a run-complete policy gate such as `pytest-cov --cov-fail-under`). |
| `BROKEN` | No behavior verdict was produced because run viability was lost (collection / import / fixture / config). |
| `NONE` | No behavior verdict applies because no tests were selected. |
| `UNKNOWN` | No trustworthy verdict can be derived (runner crash, external interrupt). |

### `SCOPE`

`SCOPE` describes the intended or resolved run scope, not achieved
verification completeness.

| Value | Meaning |
| --- | --- |
| `FULL` | The command targeted a full-suite run after selection resolution. |
| `PARTIAL` | The command targeted a narrowed or mode-limited subset. |
| `NONE` | Selection resolved to zero tests. |

Examples:

| Example | `SCOPE` |
| --- | --- |
| plain `pytest --trim` | `FULL` |
| `pytest --trim --ff` rerunning previous failures first | `FULL` |
| `pytest --trim -k expr` | `PARTIAL` |
| `pytest --trim some_test.py` | `PARTIAL` |
| `pytest --trim --lf` rerunning previous failures | `PARTIAL` |
| `pytest --trim --sw` resuming from a remembered failure | `PARTIAL` |
| `pytest --trim --lf --lfnf=none` with no cached failures | `NONE` |

For `ERROR` and `INTERRUPTED`, `SCOPE` reflects the resolved selection at the
point of termination:

- if collection completed, use `FULL` or `PARTIAL` per resolved selection
- if the run crashed before collection resolved, infer from the CLI:
  `FULL` if no narrowing flags were present, otherwise `PARTIAL`
- use `NONE` only if selection explicitly resolved to zero tests

Early termination via `-x` or `--exitfirst` does not retroactively narrow
`SCOPE`.

### `ACTION`

`ACTION` is the agent-facing next-step signal. Each value maps 1:1 to one
operation.

| Value | Meaning |
| --- | --- |
| `DONE` | Successful run. No follow-up needed. |
| `EXPAND` | A failure-replay subset (`--lf`, `--sw`, `--stepwise`) passed. Re-invoke `pytest --trim` against the full suite to confirm nothing else regressed. |
| `FIX` | A meaningful behavior-level failure occurred. Fix the failing behavior. |
| `REPAIR` | The run did not yet provide a usable behavior verdict; restore runnability first (fix imports, syntax, fixtures, config). |
| `ADJUST` | The selector or invocation needs editing (typo, over-narrow filter, wrong path). |
| `INVESTIGATE` | The runner or tooling itself failed. Escalate; output may be unreliable. |
| `ABORT` | The run was halted externally. Do not auto-retry; the halt was intentional. |

`ACTION=EXPAND` is emitted only when the selection mode is a failure-replay
shortcut derived from cached failures from a prior run: `--lf`, `--sw`, or
`--stepwise`.

By contrast, `--ff` only reorders a full run. It keeps `SCOPE=FULL` and, on
pass, emits `ACTION=DONE`.

All other partial selections, such as explicit `-k`, file paths, node ids,
marker expressions, or impact-based modes like `testmon`, emit `ACTION=DONE`
on pass because the subset is the user's intended verification target.

### Classification distinctions

Use `RUN=BROKEN` for recognized, expected pytest failure modes where the output
is still meaningful and the main problem is run viability.

Typical `BROKEN` cases once trim reporting has initialized:

- syntax error from a bad patch
- import or collection failure
- fixture setup failure
- teardown failure that invalidates the run as a behavior check
- malformed `pytest.ini` or `pyproject.toml` config observed after
  initialization
- conftest import error observed after initialization

Use `RUN=ERROR` only for abnormal runner or tooling malfunction.

Typical `ERROR` cases:

- internal pytest error
- plugin crash
- protocol bug
- abnormal failures where output may be unreliable

Use `ACTION=FIX` when the run completed and produced a meaningful user-fixable
red result.

Typical `FIX` cases:

- assertion failure
- unexpected exception in the test call phase
- strict `XPASS`
- warnings-as-errors triggered during a test
- unmet `pytest-cov --cov-fail-under` threshold with otherwise passing tests

Use `ACTION=REPAIR` when the red result does not yet provide a usable behavior
verdict and the run must be made viable first.

Typical `REPAIR` cases:

- syntax error from a bad patch
- import or collection failure
- setup failure before meaningful test execution
- teardown or setup problems whose primary meaning is that the run is not yet
  trustworthy
- bad config or conftest import observed after trim initialization

`ACTION=INVESTIGATE` means the runner crashed or behaved abnormally.
`ACTION=ABORT` means the run was halted on purpose, such as `Ctrl-C` or
`pytest.exit(...)`.

### Mixed failure precedence

When multiple failure modes occur in the same run, classify in this order
(first match wins):

1. abnormal runner or plugin crash -> `RUN=ERROR`
2. external interrupt -> `RUN=INTERRUPTED`
3. at least one meaningful call-phase behavior failure -> `RUN=COMPLETE VERDICT=FAIL ACTION=FIX`, even if teardown or collection of unrelated tests also failed
4. otherwise, if the run still completed with a user-fixable red gate such as a pure `pytest-cov --cov-fail-under` failure -> `RUN=COMPLETE VERDICT=FAIL ACTION=FIX`
5. otherwise, if any collection, import, fixture, or config failure prevented behavior verdicts for all selected tests -> `RUN=BROKEN`
6. all selected tests passed -> `RUN=COMPLETE VERDICT=PASS`
7. zero tests selected -> `RUN=EMPTY`

### Legal combinations

Exactly the following eight combination shapes are valid v1 `result` rows.
Anything outside this table is a protocol bug.

| RUN | VERDICT | SCOPE | ACTION | When |
| --- | --- | --- | --- | --- |
| `COMPLETE` | `PASS` | `FULL` | `DONE` | full suite green |
| `COMPLETE` | `PASS` | `PARTIAL` | `DONE` | explicit subset green (`-k`, file, node id, marker, `testmon`) |
| `COMPLETE` | `PASS` | `PARTIAL` | `EXPAND` | failure-replay subset green (`--lf`, `--sw`, `--stepwise`) |
| `COMPLETE` | `FAIL` | `FULL` or `PARTIAL` | `FIX` | behavior failure or other user-fixable completed red gate |
| `BROKEN` | `BROKEN` | `FULL` or `PARTIAL` | `REPAIR` | collection, import, fixture, or config broke run |
| `EMPTY` | `NONE` | `NONE` | `ADJUST` | selection resolved to zero |
| `ERROR` | `UNKNOWN` | `FULL` or `PARTIAL` or `NONE` | `INVESTIGATE` | runner, plugin, or protocol crash |
| `INTERRUPTED` | `UNKNOWN` | `FULL` or `PARTIAL` or `NONE` | `ABORT` | `Ctrl-C`, `pytest.exit(...)` |

### Agent routing

`ACTION` is a complete control signal.

| `ACTION` | Agent next step |
| --- | --- |
| `DONE` | Exit success; no further pytest invocation. |
| `EXPAND` | Re-invoke `pytest --trim` against the full suite. |
| `FIX` | Address the actionable red result, then retry. |
| `REPAIR` | Edit imports, config, fixtures, or syntax to restore runnability, then retry. |
| `ADJUST` | Revise the selector, then retry. |
| `INVESTIGATE` | Stop automation and escalate to a human or higher-capability agent. |
| `ABORT` | Stop automation; do not retry. |

`RUN`, `VERDICT`, and `SCOPE` are diagnostic context for logs and humans
reading output. They are not required for routing.

### Special cases

- Warnings-as-errors triggered in a test classify as call-phase failures and
  therefore emit `ACTION=FIX`.
- `pytest-cov --cov-fail-under` with otherwise passing tests emits
  `RUN=COMPLETE VERDICT=FAIL ACTION=FIX`.
- Non-strict xpass reports `VERDICT=PASS`.
- Selector matched nothing and "no tests defined" both map to `RUN=EMPTY`.
- Bad `pytest.ini` or `pyproject.toml` config that reaches trim reporting maps
  to `RUN=BROKEN`, not `RUN=ERROR`. Very-early config failures can occur before
  trim initializes and may emit no footer rows.
- conftest import failure that reaches trim reporting maps to `RUN=BROKEN`.
  Very-early conftest failures can occur before trim initializes and may emit
  no footer rows.

## Rationale

This section is explanatory, not normative.

### Why these four keys

Earlier protocol shapes mixed run category, red or green result, and next-step
guidance into one token. That was compact, but too ambiguous for agent-style
workflows.

The current shape separates four concerns:

- `RUN` answers what broad kind of termination happened
- `VERDICT` gives a direct red or green or broken signal
- `SCOPE` describes intended verification scope, not completeness
- `ACTION` gives a single next-step control signal

### Why `VERDICT` is separate from `RUN`

A caller should be able to route on a direct red or green signal without
inferring it indirectly from a broader run-state category. Separating
`VERDICT` from `RUN` makes that explicit.

### Why `ACTION` is separate from `VERDICT`

Green or red alone does not tell an agent what to do next. A passing
failure-replay subset still requires expansion to a full run, while a broken
run requires repair before any behavior verdict is trustworthy.

`ACTION` exists so one field can drive the next operation directly.

### Why `SCOPE` means intended scope rather than completeness

Completeness becomes misleading under modes such as `-x`, `--maxfail`, or
interruptions. The protocol needs to describe the intended verification target,
not pretend to measure how much of that target finished executing.

### Why version by prefix

Prefix-based versioning is mechanically simple. A parser anchored on `TRIM: `
can safely reject incompatible future shapes by failing to find the expected
prefix, instead of trying to reinterpret a changed wire format.

## Non-goals

This specification does not define:

- a `--trim-details` option
- compact versus full assertion-detail modes
- any backward-compatibility layer for older single-line protocols
