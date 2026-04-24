"""Minimal, machine-friendly pytest output."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import sys
import uuid

import pytest
from pytest_trim_bootstrap.options import add_trim_options

TRIM_PREFIX = "TRIM: "

RUN_COMPLETE = "COMPLETE"
RUN_BROKEN = "BROKEN"
RUN_EMPTY = "EMPTY"
RUN_ERROR = "ERROR"
RUN_INTERRUPTED = "INTERRUPTED"

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_BROKEN = "BROKEN"
VERDICT_NONE = "NONE"
VERDICT_UNKNOWN = "UNKNOWN"

ACTION_DONE = "DONE"
ACTION_EXPAND = "EXPAND"
ACTION_FIX = "FIX"
ACTION_REPAIR = "REPAIR"
ACTION_ADJUST = "ADJUST"
ACTION_INVESTIGATE = "INVESTIGATE"
ACTION_ABORT = "ABORT"

SCOPE_FULL = "FULL"
SCOPE_PARTIAL = "PARTIAL"
SCOPE_NONE = "NONE"

_DETAIL_LIMIT = 2
_NOISE_PATTERNS = (
    re.compile(r"^Use -v to get more diff$"),
    re.compile(r"^Use -vv to show.*$"),
    re.compile(r"^Omitting \d+ identical items, use -vv to show$"),
    re.compile(r"^\.\.\.Full output truncated \(\d+ lines hidden\), use '-vv' to show$"),
)


@dataclass(frozen=True)
class FinalOutcome:
    run: str
    verdict: str
    scope: str
    action: str

    def render(self) -> str:
        return render_final_line(self.run, self.verdict, self.scope, self.action)


def render_final_line(run: str, verdict: str, scope: str, action: str) -> str:
    return f"{TRIM_PREFIX}RUN={run} VERDICT={verdict} SCOPE={scope} ACTION={action}"


def pytest_addoption(parser: pytest.Parser) -> None:
    add_trim_options(parser)


@pytest.hookimpl(trylast=True)
def pytest_configure(config: pytest.Config) -> None:
    if not config.getoption("--trim", default=False):
        return

    if config.pluginmanager.getplugin("trimreporter") is not None:
        return

    terminal_reporter = config.pluginmanager.getplugin("terminalreporter")
    if os.environ.get("PYTEST_XDIST_WORKER") and terminal_reporter is None:
        return

    if terminal_reporter is not None:
        terminal_reporter._tw = QuietTerminalWriter(terminal_reporter._tw)

    config.pluginmanager.register(TrimReporter(config), "trimreporter")


class QuietTerminalWriter:
    """Terminal writer proxy that suppresses visible output while preserving API access."""

    _trim_quiet_writer = True

    def __init__(self, wrapped: object) -> None:
        self._wrapped = wrapped

    def __getattr__(self, name: str) -> object:
        return getattr(self._wrapped, name)

    def write(self, content: str, *, flush: bool = False, **markup: bool) -> None:
        del content, flush, markup

    def line(self, s: str = "", **markup: bool) -> None:
        del s, markup

    def sep(
        self,
        sepchar: str,
        title: str | None = None,
        fullwidth: int | None = None,
        **markup: bool,
    ) -> None:
        del sepchar, title, fullwidth, markup

    def flush(self) -> None:
        return None

    def write_raw(self, content: str, *, flush: bool = False) -> None:
        del content, flush

    def _write_source(self, lines: list[str], indents: list[str] | None = None) -> None:
        del lines, indents


class TrimTerminalWriter:
    """Tiny stdout-backed writer for compact pytest output."""

    def line(self, text: str = "") -> None:
        sys.stdout.write(f"{text}\n")
        sys.stdout.flush()


class TrimReporter:
    """Replacement terminal reporter with compact failure blocks and a final protocol line."""

    def __init__(self, config: pytest.Config) -> None:
        self.config = config
        self.stats: dict[str, list[object]] = {}
        self._issues: list[object] = []
        self._diagnostics: list[str] = []
        self._tw = TrimTerminalWriter()
        self._artifact_run_dir: Path | None = self._init_artifact_run_dir()
        self._artifact_paths: dict[int, Path] = {}
        self._artifact_write_failed = False
        self._session: pytest.Session | None = None
        self._stepwise_plugin = config.pluginmanager.getplugin("stepwiseplugin")
        self._last_failed_plugin = config.pluginmanager.getplugin("lfplugin")
        self._stepwise_active = bool(config.getoption("stepwise"))
        self._keyboard_interrupt = False
        self._internal_error = False
        self._issues_emitted = False
        self._final_line_emitted = False

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.failed:
            self.stats.setdefault("failed", []).append(report)
            self._issues.append(report)
        elif report.when == "call":
            self.stats.setdefault("passed", []).append(report)

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.failed:
            self.stats.setdefault("error", []).append(report)
            self._issues.append(report)

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        del session, exitstatus

    def _get_lineno(self, report: pytest.CollectReport | pytest.TestReport) -> int | None:
        """Extract the failure line number from the report."""
        longrepr = getattr(report, "longrepr", None)
        if longrepr is None:
            return None

        if hasattr(longrepr, "longrepr") and isinstance(longrepr.longrepr, str):
            match = re.search(r'File ".*?", line (\d+)', longrepr.longrepr)
            if match:
                return int(match.group(1))

        if hasattr(longrepr, "chain"):
            for repr_traceback, _, _ in reversed(longrepr.chain):
                if repr_traceback and repr_traceback.reprentries:
                    last_entry = repr_traceback.reprentries[-1]
                    if hasattr(last_entry, "reprfileloc") and last_entry.reprfileloc:
                        return last_entry.reprfileloc.lineno

        if isinstance(longrepr, tuple) and len(longrepr) >= 2:
            return longrepr[1]

        return None

    def _get_error_message_parts(
        self,
        report: pytest.CollectReport | pytest.TestReport,
    ) -> tuple[str, list[str]]:
        """Extract a compact error summary plus a few useful detail lines."""
        longrepr = getattr(report, "longrepr", None)
        if longrepr is None:
            return "unknown error", []

        if hasattr(longrepr, "chain"):
            for _, reprcrash, _ in reversed(longrepr.chain):
                if reprcrash:
                    return self._split_error_message(reprcrash.message)

        if isinstance(longrepr, tuple) and len(longrepr) >= 3:
            return self._split_error_message(longrepr[2])

        fallback_message = str(longrepr).strip()
        if not fallback_message:
            return "unknown error", []

        return self._split_error_message(fallback_message.splitlines()[-1])

    def _format_issue_lines(
        self,
        report: pytest.CollectReport | pytest.TestReport,
    ) -> list[str]:
        nodeid = report.nodeid
        lineno = self._get_lineno(report)
        summary, details = self._get_error_message_parts(report)
        headline = f"{nodeid}:{lineno} - {summary}" if lineno is not None else f"{nodeid} - {summary}"

        lines = [headline]
        visible_details = details[:_DETAIL_LIMIT]
        lines.extend(f"  detail: {detail}" for detail in visible_details)

        remaining_details = len(details) - len(visible_details)
        if remaining_details > 0:
            lines.append(f"  detail: (+{remaining_details} more details omitted)")

        artifact_line = self._artifact_detail_line(report)
        if artifact_line is not None:
            lines.append(artifact_line)

        return lines

    def _init_artifact_run_dir(self) -> Path | None:
        artifacts_dir = self.config.getoption("--trim-artifacts-dir", default=None)
        enabled = bool(self.config.getoption("--trim-artifacts", default=False) or artifacts_dir)
        if not enabled:
            return None

        try:
            base_dir = self._resolve_artifacts_base_dir(artifacts_dir)
            run_dir = base_dir / f"run-{uuid.uuid4().hex[:12]}"
            run_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # pragma: no cover - defensive: keep trim usable even if artifacts fail
            self._diagnostics.append(f"ARTIFACTS DISABLED: {exc}")
            return None

        return run_dir

    def _resolve_artifacts_base_dir(self, configured_dir: str | None) -> Path:
        if configured_dir:
            base_dir = Path(configured_dir)
            if not base_dir.is_absolute():
                base_dir = Path(self.config.rootpath) / base_dir
            return base_dir

        cache = getattr(self.config, "cache", None)
        if cache is not None and hasattr(cache, "mkdir"):
            return Path(cache.mkdir("pytest-trim"))

        # If pytest's cache plugin is unavailable, fall back to a conventional location.
        return Path(self.config.rootpath) / ".pytest_cache" / "pytest-trim"

    def _artifact_detail_line(self, report: pytest.CollectReport | pytest.TestReport) -> str | None:
        if self._artifact_run_dir is None or self._artifact_write_failed:
            return None

        try:
            artifact_path = self._write_artifact(report)
        except Exception as exc:  # pragma: no cover - defensive: artifact writing must not break the run
            self._artifact_write_failed = True
            self._diagnostics.append(f"ARTIFACT WRITE FAILED: {exc}")
            return None

        return f"  artifact: {self._display_path(artifact_path)}"

    def _write_artifact(self, report: pytest.CollectReport | pytest.TestReport) -> Path:
        assert self._artifact_run_dir is not None

        cache_key = id(report)
        cached = self._artifact_paths.get(cache_key)
        if cached is not None:
            return cached

        nodeid = getattr(report, "nodeid", "unknown")
        when = getattr(report, "when", None) or "collect"
        short_id = uuid.uuid4().hex[:8]
        filename = f"{self._sanitize_nodeid(nodeid)}__{when}__{short_id}.txt"
        artifact_path = self._artifact_run_dir / filename

        lines: list[str] = []
        lines.append(f"nodeid: {nodeid}")
        lines.append(f"when: {when}")
        lines.append(f"outcome: {getattr(report, 'outcome', 'failed')}")
        lines.append(f"rootdir: {self.config.rootpath}")
        lines.append(f"cwd: {Path.cwd()}")

        capture = getattr(getattr(self.config, "option", None), "capture", None)
        if capture is not None:
            lines.append(f"capture: {capture}")

        showlocals = getattr(getattr(self.config, "option", None), "showlocals", None)
        if showlocals is not None:
            lines.append(f"showlocals: {bool(showlocals)}")

        lines.append("")
        lines.append("=== longreprtext ===")
        longreprtext = getattr(report, "longreprtext", "") or ""
        lines.append(longreprtext.rstrip())

        sections = getattr(report, "sections", None) or []
        if sections:
            for title, content in sections:
                lines.append("")
                lines.append(f"=== {title} ===")
                lines.append((content or "").rstrip())
        elif capture == "no":
            lines.append("")
            lines.append("=== note ===")
            lines.append(
                "stdout/stderr capture is disabled (-s/--capture=no). Printed output is not available in this artifact."
            )

        artifact_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        self._artifact_paths[cache_key] = artifact_path
        return artifact_path

    def _sanitize_nodeid(self, nodeid: str) -> str:
        sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", nodeid).strip("._-")
        if not sanitized:
            return "report"
        return sanitized[:180]

    def _display_path(self, path: Path) -> str:
        root = Path(self.config.rootpath)
        try:
            return str(path.relative_to(root))
        except ValueError:
            return str(path)

    def _split_error_message(self, message: str) -> tuple[str, list[str]]:
        cleaned_lines = self._clean_message_lines(message)
        if not cleaned_lines:
            return "unknown error", []

        headline = cleaned_lines[0]
        if headline.startswith("AssertionError: assert "):
            headline = headline[len("AssertionError: ") :]

        details = self._format_detail_lines(cleaned_lines[1:])
        return headline, details

    def _clean_message_lines(self, message: str) -> list[str]:
        cleaned_lines: list[str] = []
        for raw_line in message.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("Full diff:"):
                break
            if any(pattern.match(line) for pattern in _NOISE_PATTERNS):
                continue
            cleaned_lines.append(line)

        return cleaned_lines

    def _format_detail_lines(self, lines: list[str]) -> list[str]:
        if not lines:
            return []

        diff_lines = [line for line in lines if line.startswith(("- ", "+ "))]
        if diff_lines:
            return self._group_diff_lines(diff_lines)

        details: list[str] = []
        index = 0
        while index < len(lines):
            line = lines[index]
            if self._is_label_line(line):
                label = line
                grouped_lines: list[str] = []
                index += 1
                while index < len(lines) and not self._is_label_line(lines[index]):
                    grouped_lines.append(lines[index])
                    index += 1
                details.extend(self._expand_labeled_details(label, grouped_lines))
                continue

            details.append(line)
            index += 1

        return details

    def _group_diff_lines(self, lines: list[str]) -> list[str]:
        details = []
        for index in range(0, len(lines), 2):
            details.append(" | ".join(lines[index : index + 2]))
        return details

    def _expand_labeled_details(self, label: str, grouped_lines: list[str]) -> list[str]:
        if not grouped_lines:
            return [label]

        if len(grouped_lines) == 1:
            return [f"{label} {grouped_lines[0]}"]

        if any(self._is_complex_detail(line) for line in grouped_lines):
            return [f"{label} {line}" for line in grouped_lines]

        return [f"{label} {' | '.join(grouped_lines)}"]

    def _is_complex_detail(self, line: str) -> bool:
        return " != " in line or len(line) > 60

    def _is_label_line(self, line: str) -> bool:
        return line.endswith(":") and not line.startswith(("- ", "+ ", "? "))

    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        del items

    def pytest_deselected(self, items: list[pytest.Item]) -> None:
        self.stats.setdefault("deselected", []).extend(items)

    def pytest_internalerror(self, excrepr: object, excinfo: object) -> bool:
        del excinfo

        self._internal_error = True
        self._diagnostics.append(f"INTERNAL ERROR: {self._internal_error_message(excrepr)}")
        return True

    def pytest_keyboard_interrupt(self, excinfo: object) -> None:
        value = getattr(excinfo, "value", None)
        if value is None:
            self._keyboard_interrupt = True
            return

        if type(value).__name__ == "Interrupted":
            return

        self._keyboard_interrupt = True

    def pytest_warning_recorded(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    @pytest.hookimpl(trylast=True)
    def pytest_sessionstart(self, session: pytest.Session) -> None:
        self._session = session

    @pytest.hookimpl(trylast=True)
    def pytest_unconfigure(self, config: pytest.Config) -> None:
        if self._final_line_emitted:
            return

        self._emit_issues()
        if self._protocol_line_suppressed(config):
            return

        self._emit_compatible_terminal_summaries()
        self._emit_final_line(self._final_outcome().render())

    def pytest_terminal_summary(
        self,
        terminalreporter: object,
        exitstatus: int,
        config: pytest.Config,
    ) -> None:
        del terminalreporter, exitstatus, config

    def _final_outcome(self) -> FinalOutcome:
        exitstatus = self._final_exitstatus()
        scope = self._resolved_scope(exitstatus)

        if self._internal_error or exitstatus == pytest.ExitCode.INTERNAL_ERROR:
            return FinalOutcome(RUN_ERROR, VERDICT_UNKNOWN, scope, ACTION_INVESTIGATE)

        if self._keyboard_interrupt:
            return FinalOutcome(RUN_INTERRUPTED, VERDICT_UNKNOWN, scope, ACTION_ABORT)

        if self._no_tests_collected(exitstatus):
            return FinalOutcome(RUN_EMPTY, VERDICT_NONE, SCOPE_NONE, ACTION_ADJUST)

        if self._ordinary_failure(exitstatus):
            if self._behavior_failure_detected() or not self._issues:
                return FinalOutcome(RUN_COMPLETE, VERDICT_FAIL, scope, ACTION_FIX)

            return FinalOutcome(RUN_BROKEN, VERDICT_BROKEN, scope, ACTION_REPAIR)

        if exitstatus == pytest.ExitCode.OK:
            action = ACTION_EXPAND if self._successful_run_requires_full_followup() else ACTION_DONE
            return FinalOutcome(RUN_COMPLETE, VERDICT_PASS, scope, action)

        if exitstatus == pytest.ExitCode.INTERRUPTED:
            return FinalOutcome(RUN_INTERRUPTED, VERDICT_UNKNOWN, scope, ACTION_ABORT)

        if exitstatus == pytest.ExitCode.USAGE_ERROR:
            return FinalOutcome(RUN_ERROR, VERDICT_UNKNOWN, scope, ACTION_INVESTIGATE)

        return FinalOutcome(RUN_ERROR, VERDICT_UNKNOWN, scope, ACTION_INVESTIGATE)

    def _emit_final_line(self, line: str) -> None:
        if self._final_line_emitted:
            return

        self._tw.line(line)
        self._final_line_emitted = True

    def _emit_issues(self) -> None:
        if self._issues_emitted:
            return

        for line in self._diagnostics:
            self._tw.line(line)

        for report in self._issues:
            for line in self._format_issue_lines(report):
                self._tw.line(line)

        self._issues_emitted = True

    def _emit_compatible_terminal_summaries(self) -> None:
        self._emit_pytest_cov_terminal_summary()

    def _emit_pytest_cov_terminal_summary(self) -> None:
        terminal_reporter = self.config.pluginmanager.getplugin("terminalreporter")
        if terminal_reporter is None:
            return

        quiet_writer = getattr(terminal_reporter, "_tw", None)
        if not getattr(quiet_writer, "_trim_quiet_writer", False):
            return

        wrapped_writer = getattr(quiet_writer, "_wrapped", None)
        if wrapped_writer is None:
            return

        cov_plugin = self.config.pluginmanager.getplugin("_cov")
        if cov_plugin is None:
            return

        summary = getattr(cov_plugin, "pytest_terminal_summary", None)
        if not callable(summary):
            return

        had_heading_flag = hasattr(cov_plugin, "_wrote_heading")
        previous_heading_flag = getattr(cov_plugin, "_wrote_heading", False)
        terminal_reporter._tw = wrapped_writer
        try:
            if had_heading_flag:
                cov_plugin._wrote_heading = False
            summary(terminal_reporter)
        except Exception as exc:  # pragma: no cover - compatibility replay must not break trim runs
            self._tw.line(f"COVERAGE SUMMARY REPLAY FAILED: {exc}")
        finally:
            if had_heading_flag:
                cov_plugin._wrote_heading = previous_heading_flag
            terminal_reporter._tw = quiet_writer

    def _protocol_line_suppressed(self, config: pytest.Config) -> bool:
        return bool(config.getoption("collectonly", default=False))

    def _final_exitstatus(self) -> int:
        if self._session is None:
            return pytest.ExitCode.INTERNAL_ERROR

        return int(getattr(self._session, "exitstatus", pytest.ExitCode.INTERNAL_ERROR))

    def _stepwise_continue_required(self) -> bool:
        if not self._stepwise_active or self._stepwise_plugin is None:
            return False

        cached_info = getattr(self._stepwise_plugin, "cached_info", None)
        return bool(getattr(cached_info, "last_failed", None))

    def _stepwise_completed_after_resume(self) -> bool:
        if not self._stepwise_active or self._stepwise_plugin is None:
            return False

        if self._stepwise_continue_required():
            return False

        return any(
            status.startswith("skipping ")
            for status in getattr(self._stepwise_plugin, "report_status", [])
        )

    def _reran_previous_failures(self) -> bool:
        if not self.config.getoption("lf", default=False) or self._last_failed_plugin is None:
            return False

        count = getattr(self._last_failed_plugin, "_previously_failed_count", None)
        report_status = getattr(self._last_failed_plugin, "_report_status", "")
        return bool(count) and isinstance(report_status, str) and report_status.startswith(
            "rerun previous "
        )

    def _successful_run_requires_full_followup(self) -> bool:
        return self._stepwise_completed_after_resume() or self._reran_previous_failures()

    def _ordinary_failure(self, exitstatus: int) -> bool:
        return bool(self._issues) or exitstatus == pytest.ExitCode.TESTS_FAILED

    def _behavior_failure_detected(self) -> bool:
        return any(
            isinstance(report, pytest.TestReport) and report.when == "call"
            for report in self._issues
        )

    def _resolved_scope(self, exitstatus: int) -> str:
        if self._no_tests_collected(exitstatus):
            return SCOPE_NONE

        if self._partial_scope_requested():
            return SCOPE_PARTIAL

        return SCOPE_FULL

    def _partial_scope_requested(self) -> bool:
        return any(
            (
                self._explicit_selection_requested(),
                self._selection_deselected_items(),
                self._reran_previous_failures(),
                self._stepwise_partial_scope(),
            )
        )

    def _explicit_selection_requested(self) -> bool:
        option = self.config.option
        return any(
            (
                bool(getattr(option, "file_or_dir", [])),
                bool(getattr(option, "keyword", "")),
                bool(getattr(option, "markexpr", "")),
                bool(getattr(option, "deselect", [])),
            )
        )

    def _selection_deselected_items(self) -> bool:
        return bool(self.stats.get("deselected"))

    def _stepwise_partial_scope(self) -> bool:
        return self._stepwise_continue_required() or self._stepwise_completed_after_resume()

    def _no_tests_collected(self, exitstatus: int) -> bool:
        return exitstatus == pytest.ExitCode.NO_TESTS_COLLECTED and not self._issues

    def _internal_error_message(self, excrepr: object) -> str:
        reprcrash = getattr(excrepr, "reprcrash", None)
        if reprcrash is not None and getattr(reprcrash, "message", ""):
            return str(reprcrash.message)

        fallback = str(excrepr).strip()
        if not fallback:
            return "unknown internal error"

        return fallback.splitlines()[-1]
