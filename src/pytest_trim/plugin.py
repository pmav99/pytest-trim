"""Minimal, agent-friendly pytest output."""

from __future__ import annotations

import os
import re
import sys

import pytest

PASS_MESSAGE = "PASS"
FAIL_MESSAGE = "FAIL"
REPEAT_MESSAGE = "REPEAT"
RERUN_MESSAGE = "RERUN"
NO_TESTS_MESSAGE = "NO_TESTS"
ERROR_MESSAGE = "ERROR"
_DETAIL_LIMIT = 2
_NOISE_PATTERNS = (
    re.compile(r"^Use -v to get more diff$"),
    re.compile(r"^Use -vv to show.*$"),
    re.compile(r"^Omitting \d+ identical items, use -vv to show$"),
    re.compile(r"^\.\.\.Full output truncated \(\d+ lines hidden\), use '-vv' to show$"),
)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--agent",
        action="store_true",
        default=False,
        help="Enable minimal agent-friendly output format",
    )


@pytest.hookimpl(trylast=True)
def pytest_configure(config: pytest.Config) -> None:
    if not config.getoption("--agent", default=False):
        return

    terminal_reporter = config.pluginmanager.getplugin("terminalreporter")
    if os.environ.get("PYTEST_XDIST_WORKER") and terminal_reporter is None:
        return

    if terminal_reporter is not None:
        terminal_reporter._tw = QuietTerminalWriter(terminal_reporter._tw)

    config.pluginmanager.register(AgentReporter(config), "agentreporter")


class QuietTerminalWriter:
    """Terminal writer proxy that suppresses visible output while preserving API access."""

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


class AgentTerminalWriter:
    """Tiny stdout-backed writer for compact agent output."""

    def line(self, text: str = "") -> None:
        sys.stdout.write(f"{text}\n")
        sys.stdout.flush()


class AgentReporter:
    """Replacement terminal reporter with compact failure blocks and a final status token."""

    def __init__(self, config: pytest.Config) -> None:
        self.config = config
        self.stats: dict[str, list[object]] = {}
        self._issues: list[object] = []
        self._tw = AgentTerminalWriter()
        self._session: pytest.Session | None = None
        self._stepwise_plugin = config.pluginmanager.getplugin("stepwiseplugin")
        self._stepwise_active = bool(config.getoption("stepwise"))
        self._issues_emitted = False
        self._status_emitted = False

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

        return lines

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

    def pytest_internalerror(self, excrepr: object) -> None:
        self._tw.line(f"INTERNAL ERROR: {excrepr}")
        self._emit_status(ERROR_MESSAGE)

    def pytest_warning_recorded(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    @pytest.hookimpl(trylast=True)
    def pytest_sessionstart(self, session: pytest.Session) -> None:
        self._session = session

    @pytest.hookimpl(trylast=True)
    def pytest_unconfigure(self, config: pytest.Config) -> None:
        del config

        if self._status_emitted:
            return

        self._emit_issues()
        self._emit_status(self._status_message(self._final_exitstatus()))

    def pytest_terminal_summary(
        self,
        terminalreporter: object,
        exitstatus: int,
        config: pytest.Config,
    ) -> None:
        del terminalreporter, exitstatus, config

    def _status_message(self, exitstatus: int) -> str:
        if self._stepwise_continue_required():
            return REPEAT_MESSAGE

        if self._stepwise_completed_after_resume():
            return RERUN_MESSAGE

        if self._issues or exitstatus == pytest.ExitCode.TESTS_FAILED:
            return FAIL_MESSAGE

        if exitstatus == pytest.ExitCode.OK:
            return PASS_MESSAGE

        if exitstatus == pytest.ExitCode.NO_TESTS_COLLECTED:
            return NO_TESTS_MESSAGE

        return ERROR_MESSAGE

    def _emit_status(self, status: str) -> None:
        if self._status_emitted:
            return

        self._tw.line(status)
        self._status_emitted = True

    def _emit_issues(self) -> None:
        if self._issues_emitted:
            return

        for report in self._issues:
            for line in self._format_issue_lines(report):
                self._tw.line(line)

        self._issues_emitted = True

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
