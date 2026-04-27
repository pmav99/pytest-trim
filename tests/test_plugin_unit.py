from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

import pytest_trim.plugin as plugin


class FakeParser:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def addoption(self, name: str, **kwargs: object) -> None:
        self.calls.append((name, kwargs))


class FakePluginManager:
    def __init__(self, plugins: dict[str, object] | None = None) -> None:
        self._plugins = plugins or {}
        self.registered: list[tuple[object, str]] = []

    def getplugin(self, name: str) -> object | None:
        return self._plugins.get(name)

    def register(self, obj: object, name: str) -> None:
        self.registered.append((obj, name))


class FakeCache:
    def __init__(self, root: Path) -> None:
        self.root = root

    def mkdir(self, name: str) -> str:
        target = self.root / name
        target.mkdir(parents=True, exist_ok=True)
        return str(target)


class FakeConfig:
    def __init__(
        self,
        root: Path,
        *,
        getoptions: dict[str, object] | None = None,
        option_attrs: dict[str, object] | None = None,
        plugins: dict[str, object] | None = None,
        cache: object | None = None,
    ) -> None:
        self.rootpath = root
        self.pluginmanager = FakePluginManager(plugins)
        self.cache = cache
        option_defaults = {
            "file_or_dir": [],
            "keyword": "",
            "markexpr": "",
            "deselect": [],
            "capture": "fd",
            "showlocals": False,
        }
        self.option = SimpleNamespace(**(option_defaults | (option_attrs or {})))
        self._options = {
            "--trim": False,
            "--trim-artifacts": False,
            "--trim-artifacts-dir": None,
            "collectonly": False,
            "failedfirst": False,
            "stepwise": False,
            "lf": False,
            **(getoptions or {}),
        }

    def getoption(self, name: str, default: object = None) -> object:
        return self._options.get(name, default)


class RecordingWriter:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def line(self, text: str = "") -> None:
        self.lines.append(text)


def make_reporter(
    tmp_path: Path,
    *,
    getoptions: dict[str, object] | None = None,
    option_attrs: dict[str, object] | None = None,
    plugins: dict[str, object] | None = None,
    cache: object | None = None,
) -> tuple[plugin.TrimReporter, FakeConfig]:
    config = FakeConfig(
        tmp_path,
        getoptions=getoptions,
        option_attrs=option_attrs,
        plugins=plugins,
        cache=cache,
    )
    return plugin.TrimReporter(config), config


def make_test_report(
    *,
    nodeid: str = "test_sample.py::test_case",
    outcome: str = "failed",
    longrepr: object = "boom",
    when: str = "call",
) -> pytest.TestReport:
    return pytest.TestReport(
        nodeid=nodeid,
        location=("test_sample.py", 1, "test_case"),
        keywords={},
        outcome=outcome,
        longrepr=longrepr,
        when=when,
    )


def make_collect_report(
    *,
    nodeid: str = "test_sample.py",
    outcome: str = "failed",
    longrepr: object = ("test_sample.py", 7, "collect failed"),
) -> pytest.CollectReport:
    return pytest.CollectReport(
        nodeid=nodeid,
        outcome=outcome,
        longrepr=longrepr,
        result=[],
    )


def test_reload_module_and_register_options() -> None:
    reloaded = importlib.reload(plugin)
    parser = FakeParser()

    reloaded.pytest_addoption(parser)

    assert reloaded.FinalOutcome(
        reloaded.RUN_COMPLETE,
        reloaded.VERDICT_PASS,
        reloaded.SCOPE_FULL,
        reloaded.ACTION_DONE,
    ).render() == reloaded.render_final_line(
        reloaded.RUN_COMPLETE,
        reloaded.VERDICT_PASS,
        reloaded.SCOPE_FULL,
        reloaded.ACTION_DONE,
    )
    assert [name for name, _ in parser.calls] == [
        "--trim",
        "--trim-artifacts",
        "--trim-artifacts-dir",
    ]


def test_pytest_configure_respects_trim_and_xdist(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    terminal_reporter = SimpleNamespace(_tw=object())

    disabled = FakeConfig(tmp_path, plugins={"terminalreporter": terminal_reporter})
    plugin.pytest_configure(disabled)
    assert disabled.pluginmanager.registered == []
    assert not isinstance(terminal_reporter._tw, plugin.QuietTerminalWriter)

    enabled = FakeConfig(
        tmp_path,
        getoptions={"--trim": True},
        plugins={"terminalreporter": terminal_reporter},
    )
    plugin.pytest_configure(enabled)
    assert isinstance(terminal_reporter._tw, plugin.QuietTerminalWriter)
    assert enabled.pluginmanager.registered
    assert enabled.pluginmanager.registered[0][1] == "trimreporter"

    already_registered_terminal = SimpleNamespace(_tw=object())
    already_registered = FakeConfig(
        tmp_path,
        getoptions={"--trim": True},
        plugins={
            "terminalreporter": already_registered_terminal,
            "trimreporter": object(),
        },
    )
    plugin.pytest_configure(already_registered)
    assert already_registered.pluginmanager.registered == []
    assert not isinstance(already_registered_terminal._tw, plugin.QuietTerminalWriter)

    no_terminal = FakeConfig(tmp_path, getoptions={"--trim": True})
    plugin.pytest_configure(no_terminal)
    assert len(no_terminal.pluginmanager.registered) == 1
    assert no_terminal.pluginmanager.registered[0][1] == "trimreporter"

    worker = FakeConfig(tmp_path, getoptions={"--trim": True})
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    plugin.pytest_configure(worker)
    monkeypatch.delenv("PYTEST_XDIST_WORKER")
    assert len(worker.pluginmanager.registered) == 1
    worker_plugin, worker_name = worker.pluginmanager.registered[0]
    assert isinstance(worker_plugin, plugin.TrimWorkerReporter)
    assert worker_name == "trimworkerreporter"

    existing_worker = FakeConfig(
        tmp_path,
        getoptions={"--trim": True},
        plugins={"trimworkerreporter": object()},
    )
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    plugin.pytest_configure(existing_worker)
    monkeypatch.delenv("PYTEST_XDIST_WORKER")
    assert existing_worker.pluginmanager.registered == []


def test_terminal_writer_helpers_are_quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    wrapped = SimpleNamespace(marker="wrapped")
    quiet = plugin.QuietTerminalWriter(wrapped)

    assert quiet.marker == "wrapped"
    assert quiet._trim_quiet_writer is True
    quiet.write("hidden", flush=True, red=True)
    quiet.line("hidden", yellow=True)
    quiet.sep("-", "title", fullwidth=5, blue=True)
    quiet.write_raw("hidden", flush=True)
    quiet._write_source(["a"], ["  "])
    assert quiet.flush() is None

    class FakeStdout:
        def __init__(self) -> None:
            self.buffer: list[str] = []
            self.flushed = False

        def write(self, text: str) -> None:
            self.buffer.append(text)

        def flush(self) -> None:
            self.flushed = True

    fake_stdout = FakeStdout()
    monkeypatch.setattr(plugin.sys, "stdout", fake_stdout)

    writer = plugin.TrimTerminalWriter()
    writer.line("visible")

    assert fake_stdout.buffer == ["visible\n"]
    assert fake_stdout.flushed is True


def test_cov_summary_replay_survives_module_reload_identity_mismatch(tmp_path: Path) -> None:
    class WrappedWriter:
        def __init__(self) -> None:
            self.events: list[tuple[str, str]] = []

        def write(self, content: str, **kwargs: object) -> None:
            del kwargs
            self.events.append(("write", content))

        def write_sep(self, sep: str, title: str) -> None:
            self.events.append(("sep", f"{sep}:{title}"))

    class TerminalReporter:
        def __init__(self, writer: object) -> None:
            self._tw = writer

        def write(self, content: str, **kwargs: object) -> None:
            self._tw.write(content, **kwargs)

        def write_sep(self, sep: str, title: str) -> None:
            self._tw.write_sep(sep, title)

    old_quiet_writer_type = plugin.QuietTerminalWriter
    wrapped_writer = WrappedWriter()
    quiet_writer = old_quiet_writer_type(wrapped_writer)
    reloaded = importlib.reload(plugin)

    def emit_cov_summary(terminalreporter: object) -> None:
        terminalreporter.write_sep("=", "tests coverage")
        terminalreporter.write("TOTAL 1 0 100%\n")

    cov_plugin = SimpleNamespace(_wrote_heading=True, pytest_terminal_summary=emit_cov_summary)
    terminal_reporter = TerminalReporter(quiet_writer)
    config = FakeConfig(tmp_path, plugins={"terminalreporter": terminal_reporter, "_cov": cov_plugin})
    reporter = reloaded.TrimReporter(config)

    reporter._emit_pytest_cov_terminal_summary()

    assert wrapped_writer.events == [("sep", "=:tests coverage"), ("write", "TOTAL 1 0 100%\n")]
    assert terminal_reporter._tw is quiet_writer
    assert cov_plugin._wrote_heading is True


@pytest.mark.parametrize(
    ("writer", "cov_plugin"),
    [
        (object(), SimpleNamespace(pytest_terminal_summary=lambda _: None)),
        (SimpleNamespace(_trim_quiet_writer=True), SimpleNamespace(pytest_terminal_summary=lambda _: None)),
        (
            SimpleNamespace(_trim_quiet_writer=True, _wrapped=object()),
            SimpleNamespace(pytest_terminal_summary=None),
        ),
    ],
)
def test_cov_summary_replay_skips_incompatible_replay_targets(
    tmp_path: Path,
    writer: object,
    cov_plugin: object,
) -> None:
    terminal_reporter = SimpleNamespace(_tw=writer)
    config = FakeConfig(tmp_path, plugins={"terminalreporter": terminal_reporter, "_cov": cov_plugin})
    reporter = plugin.TrimReporter(config)

    reporter._emit_pytest_cov_terminal_summary()

    assert terminal_reporter._tw is writer


def test_cov_summary_replay_handles_cov_plugins_without_heading_flag(tmp_path: Path) -> None:
    class WrappedWriter:
        def __init__(self) -> None:
            self.events: list[tuple[str, str]] = []

        def write(self, content: str, **kwargs: object) -> None:
            del kwargs
            self.events.append(("write", content))

        def write_sep(self, sep: str, title: str) -> None:
            self.events.append(("sep", f"{sep}:{title}"))

    class TerminalReporter:
        def __init__(self, writer: object) -> None:
            self._tw = writer

        def write(self, content: str, **kwargs: object) -> None:
            self._tw.write(content, **kwargs)

        def write_sep(self, sep: str, title: str) -> None:
            self._tw.write_sep(sep, title)

    def emit_cov_summary(terminalreporter: object) -> None:
        terminalreporter.write_sep("-", "headingless coverage")
        terminalreporter.write("TOTAL 1 0 100%\n")

    wrapped_writer = WrappedWriter()
    quiet_writer = plugin.QuietTerminalWriter(wrapped_writer)
    terminal_reporter = TerminalReporter(quiet_writer)
    cov_plugin = SimpleNamespace(pytest_terminal_summary=emit_cov_summary)
    config = FakeConfig(tmp_path, plugins={"terminalreporter": terminal_reporter, "_cov": cov_plugin})
    reporter = plugin.TrimReporter(config)

    reporter._emit_pytest_cov_terminal_summary()

    assert wrapped_writer.events == [("sep", "-:headingless coverage"), ("write", "TOTAL 1 0 100%\n")]
    assert terminal_reporter._tw is quiet_writer
    assert not hasattr(cov_plugin, "_wrote_heading")


def test_report_collection_and_misc_hooks(tmp_path: Path) -> None:
    reporter, _ = make_reporter(tmp_path)
    failed_call = make_test_report(longrepr="boom", when="call")
    passed_call = make_test_report(outcome="passed", longrepr=None, when="call")
    passed_setup = make_test_report(outcome="passed", longrepr=None, when="setup")
    failed_collect = make_collect_report()
    passed_collect = make_collect_report(outcome="passed", longrepr=None)

    reporter.pytest_runtest_logreport(failed_call)
    reporter.pytest_runtest_logreport(passed_call)
    reporter.pytest_runtest_logreport(passed_setup)
    reporter.pytest_collectreport(failed_collect)
    reporter.pytest_collectreport(passed_collect)
    reporter.pytest_deselected([SimpleNamespace(nodeid="test_other.py::test_case")])
    reporter.pytest_collection_modifyitems([])
    reporter.pytest_sessionfinish(SimpleNamespace(), 0)
    reporter.pytest_warning_recorded("warning", when="config")

    assert reporter.stats["failed"] == [failed_call]
    assert reporter.stats["passed"] == [passed_call]
    assert reporter.stats["error"] == [failed_collect]
    assert len(reporter.stats["deselected"]) == 1
    assert reporter._issues == [failed_call, failed_collect]


def test_lineno_and_error_parts_support_all_repr_shapes(tmp_path: Path) -> None:
    reporter, _ = make_reporter(tmp_path)

    class EmptyCrashChain:
        def __init__(self) -> None:
            self.chain = [(None, None, None)]

        def __str__(self) -> str:
            return "RuntimeError: fallback chain message"

    assert reporter._get_lineno(SimpleNamespace(longrepr=None)) is None

    chain_longrepr = SimpleNamespace(
        longrepr="not a file match",
        chain=[
            (SimpleNamespace(reprentries=[SimpleNamespace(reprfileloc=SimpleNamespace(lineno=23))]), None, None),
            (SimpleNamespace(reprentries=[]), None, None),
        ],
    )
    assert reporter._get_lineno(SimpleNamespace(longrepr=chain_longrepr)) == 23

    string_longrepr = SimpleNamespace(longrepr='File "demo.py", line 17, in test_case')
    assert reporter._get_lineno(SimpleNamespace(longrepr=string_longrepr)) == 17
    assert reporter._get_lineno(SimpleNamespace(longrepr=("demo.py", 11, "boom"))) == 11

    assert reporter._get_error_message_parts(SimpleNamespace(longrepr=None)) == ("unknown error", [])

    chain_error = SimpleNamespace(
        chain=[
            (None, SimpleNamespace(message="AssertionError: assert 1 == 2\nextra detail"), None),
            (None, None, None),
        ]
    )
    assert reporter._get_error_message_parts(SimpleNamespace(longrepr=chain_error)) == (
        "assert 1 == 2",
        ["extra detail"],
    )

    assert reporter._get_error_message_parts(
        SimpleNamespace(longrepr=("demo.py", 8, "AssertionError: assert left == right\nmore"))
    ) == ("assert left == right", ["more"])
    assert reporter._get_error_message_parts(SimpleNamespace(longrepr=EmptyCrashChain())) == (
        "RuntimeError: fallback chain message",
        [],
    )
    assert reporter._get_error_message_parts(SimpleNamespace(longrepr="   ")) == ("unknown error", [])
    assert reporter._get_error_message_parts(SimpleNamespace(longrepr="one\nRuntimeError: boom")) == (
        "RuntimeError: boom",
        [],
    )


def test_message_cleaning_and_detail_helpers(tmp_path: Path) -> None:
    reporter, _ = make_reporter(tmp_path)

    assert reporter._split_error_message(
        "\n"
        "  \n"
        "Use -v to get more diff\n"
        "Full diff:\n"
        "ignored"
    ) == ("unknown error", [])

    noise_report = SimpleNamespace(
        nodeid="test_demo.py::test_case",
        longrepr=(
            "demo.py",
            8,
            "AssertionError: assert left == right\n"
            "Use -v to get more diff\n"
            "label:\n"
            "a\n"
            "b\n"
            "Full diff:\n"
            "ignore me",
        ),
    )
    assert reporter._format_issue_lines(noise_report) == [
        "test_demo.py::test_case:8 - assert left == right",
        "  detail: label: a | b",
    ]

    diff_report = SimpleNamespace(
        nodeid="test_demo.py::test_case",
        longrepr=("demo.py", 8, "AssertionError: assert left == right\n- left\n+ right\n- three"),
    )
    assert reporter._format_issue_lines(diff_report) == [
        "test_demo.py::test_case:8 - assert left == right",
        "  detail: - left | + right",
        "  detail: - three",
    ]

    complex_label_report = SimpleNamespace(
        nodeid="test_demo.py::test_case",
        longrepr=("demo.py", 8, "AssertionError: assert left == right\nlabel:\nshort\nx != y"),
    )
    assert reporter._format_issue_lines(complex_label_report) == [
        "test_demo.py::test_case:8 - assert left == right",
        "  detail: label: short",
        "  detail: label: x != y",
    ]

    assert reporter._expand_labeled_details("label:", []) == ["label:"]
    assert reporter._expand_labeled_details("label:", ["only"]) == ["label: only"]


def test_issue_line_formatting_caps_details_and_appends_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    reporter, _ = make_reporter(tmp_path)
    report = SimpleNamespace(
        nodeid="test_demo.py::test_case",
        longrepr=("demo.py", 9, "RuntimeError: boom\none\ntwo\nthree"),
    )

    monkeypatch.setattr(reporter, "_artifact_detail_line", lambda report: "  artifact: demo.txt")
    assert reporter._format_issue_lines(report) == [
        "test_demo.py::test_case:9 - RuntimeError: boom",
        "  detail: one",
        "  detail: two",
        "  detail: (+1 more details omitted)",
        "  artifact: demo.txt",
    ]

    no_lineno_report = SimpleNamespace(
        nodeid="test_demo.py::test_case",
        longrepr=SimpleNamespace(
            chain=[
                (None, SimpleNamespace(message="RuntimeError: boom\none\ntwo\nthree"), None),
            ]
        ),
    )
    monkeypatch.setattr(reporter, "_artifact_detail_line", lambda report: None)
    assert reporter._format_issue_lines(no_lineno_report) == [
        "test_demo.py::test_case - RuntimeError: boom",
        "  detail: one",
        "  detail: two",
        "  detail: (+1 more details omitted)",
    ]


def test_artifact_path_helpers_cover_relative_absolute_cache_and_fallback(tmp_path: Path) -> None:
    reporter, config = make_reporter(tmp_path)
    cache = FakeCache(tmp_path / "cache-root")
    reporter.config.cache = cache

    assert reporter._resolve_artifacts_base_dir("artifacts") == tmp_path / "artifacts"
    assert reporter._resolve_artifacts_base_dir(str(tmp_path / "absolute")) == tmp_path / "absolute"
    assert reporter._resolve_artifacts_base_dir(None) == tmp_path / "cache-root" / "pytest-trim"

    reporter.config.cache = object()
    assert reporter._resolve_artifacts_base_dir(None) == tmp_path / ".pytest_cache" / "pytest-trim"

    assert reporter._sanitize_nodeid("!!!") == "report"
    assert reporter._sanitize_nodeid("pkg/test_demo.py::test_case[param]") == "pkg_test_demo.py_test_case_param"
    assert reporter._display_path(tmp_path / "artifact.txt") == "artifact.txt"
    assert reporter._display_path(Path("/tmp/outside.txt")) == "/tmp/outside.txt"
    assert config.rootpath == tmp_path


def test_write_artifact_supports_sections_notes_and_cache(tmp_path: Path) -> None:
    reporter, _ = make_reporter(
        tmp_path,
        getoptions={"--trim-artifacts": True, "--trim-artifacts-dir": str(tmp_path / "artifacts")},
        option_attrs={"capture": "sys", "showlocals": True},
    )
    report = SimpleNamespace(
        nodeid="pkg/test_demo.py::test_case",
        when="call",
        outcome="failed",
        longreprtext="traceback text\n",
        sections=[("Captured stdout call", "hello stdout\n")],
    )

    first_path = reporter._write_artifact(report)
    second_path = reporter._write_artifact(report)

    assert first_path == second_path
    text = first_path.read_text(encoding="utf-8")
    assert "nodeid: pkg/test_demo.py::test_case" in text
    assert "when: call" in text
    assert "outcome: failed" in text
    assert "capture: sys" in text
    assert "showlocals: True" in text
    assert "=== longreprtext ===" in text
    assert "traceback text" in text
    assert "=== Captured stdout call ===" in text
    assert "hello stdout" in text

    note_reporter, _ = make_reporter(
        tmp_path,
        getoptions={"--trim-artifacts": True, "--trim-artifacts-dir": str(tmp_path / "note-artifacts")},
        option_attrs={"capture": "no", "showlocals": None},
    )
    note_path = note_reporter._write_artifact(SimpleNamespace(longreprtext="", sections=[]))
    note_text = note_path.read_text(encoding="utf-8")
    assert "nodeid: unknown" in note_text
    assert "when: collect" in note_text
    assert "outcome: failed" in note_text
    assert "capture: no" in note_text
    assert "showlocals:" not in note_text
    assert "=== note ===" in note_text

    no_option_reporter, _ = make_reporter(
        tmp_path,
        getoptions={"--trim-artifacts": True, "--trim-artifacts-dir": str(tmp_path / "none-artifacts")},
    )
    no_option_reporter.config.option = None
    none_path = no_option_reporter._write_artifact(
        SimpleNamespace(nodeid="test_none.py::test_case", longreprtext="", sections=[])
    )
    none_text = none_path.read_text(encoding="utf-8")
    assert "capture:" not in none_text
    assert "showlocals:" not in none_text


def test_artifact_detail_line_returns_none_or_relative_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    reporter, _ = make_reporter(tmp_path)
    assert reporter._artifact_detail_line(SimpleNamespace()) is None

    reporter._artifact_run_dir = tmp_path / "artifacts"
    reporter._artifact_run_dir.mkdir()
    reporter._artifact_write_failed = True
    assert reporter._artifact_detail_line(SimpleNamespace()) is None

    reporter._artifact_write_failed = False
    artifact_path = reporter._artifact_run_dir / "demo.txt"
    monkeypatch.setattr(reporter, "_write_artifact", lambda report: artifact_path)
    assert reporter._artifact_detail_line(SimpleNamespace()) == "  artifact: artifacts/demo.txt"


def test_internal_error_interrupt_and_exitstatus_helpers(tmp_path: Path) -> None:
    reporter, _ = make_reporter(tmp_path)

    class EmptyString:
        def __str__(self) -> str:
            return " \n "

    class MultiLineString:
        def __str__(self) -> str:
            return "one\ntwo"

    assert reporter._internal_error_message(
        SimpleNamespace(reprcrash=SimpleNamespace(message="explicit crash"))
    ) == "explicit crash"
    assert reporter._internal_error_message(EmptyString()) == "unknown internal error"
    assert reporter._internal_error_message(MultiLineString()) == "two"

    assert reporter.pytest_internalerror(SimpleNamespace(reprcrash=SimpleNamespace(message="boom")), object()) is True
    assert reporter._internal_error is True
    assert reporter._diagnostics[-1] == "INTERNAL ERROR: boom"

    none_interrupt, _ = make_reporter(tmp_path)
    none_interrupt.pytest_keyboard_interrupt(SimpleNamespace(value=None))
    assert none_interrupt._keyboard_interrupt is True

    class Interrupted(Exception):
        pass

    builtin_interrupt, _ = make_reporter(tmp_path)
    builtin_interrupt.pytest_keyboard_interrupt(SimpleNamespace(value=Interrupted()))
    assert builtin_interrupt._keyboard_interrupt is False

    runtime_interrupt, _ = make_reporter(tmp_path)
    runtime_interrupt.pytest_keyboard_interrupt(SimpleNamespace(value=RuntimeError("stop")))
    assert runtime_interrupt._keyboard_interrupt is True

    no_session, _ = make_reporter(tmp_path)
    assert no_session._final_exitstatus() == pytest.ExitCode.INTERNAL_ERROR

    with_session, _ = make_reporter(tmp_path)
    with_session.pytest_sessionstart(SimpleNamespace(exitstatus=pytest.ExitCode.OK))
    assert with_session._final_exitstatus() == pytest.ExitCode.OK


def test_emitters_and_unconfigure_are_idempotent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    reporter, _ = make_reporter(tmp_path)
    reporter._tw = RecordingWriter()
    reporter._diagnostics = ["diag"]
    reporter._issues = [SimpleNamespace(nodeid="test_demo.py::test_case")]
    monkeypatch.setattr(reporter, "_format_issue_lines", lambda report: ["issue-1", "issue-2"])

    reporter._emit_issues()
    reporter._emit_issues()
    assert reporter._tw.lines == ["diag", "issue-1", "issue-2"]

    reporter._emit_final_line("FINAL")
    reporter._emit_final_line("FINAL")
    assert reporter._tw.lines[-1] == "FINAL"
    assert reporter._tw.lines.count("FINAL") == 1

    calls: list[str] = []
    configured, config = make_reporter(tmp_path)
    monkeypatch.setattr(configured, "_emit_issues", lambda: calls.append("issues"))
    monkeypatch.setattr(configured, "_emit_final_line", lambda line: calls.append(line))
    monkeypatch.setattr(
        configured,
        "_final_outcome",
        lambda: plugin.FinalOutcome(
            plugin.RUN_COMPLETE,
            plugin.VERDICT_PASS,
            plugin.SCOPE_FULL,
            plugin.ACTION_DONE,
        ),
    )
    configured.pytest_unconfigure(config)
    configured.pytest_terminal_summary(object(), 0, config)
    assert calls == ["issues", plugin.render_final_line("COMPLETE", "PASS", "FULL", "DONE")]

    collect_only, collect_only_config = make_reporter(tmp_path, getoptions={"collectonly": True})
    collect_only_calls: list[str] = []
    monkeypatch.setattr(collect_only, "_emit_issues", lambda: collect_only_calls.append("issues"))
    monkeypatch.setattr(
        collect_only,
        "_final_outcome",
        lambda: pytest.fail("collect-only runs must not compute protocol footer rows"),
    )
    collect_only.pytest_unconfigure(collect_only_config)
    assert collect_only_calls == ["issues"]

    finished, config = make_reporter(tmp_path)
    finished._final_line_emitted = True
    finished.pytest_unconfigure(config)


def test_footer_and_count_edge_helpers_cover_idempotent_paths(tmp_path: Path) -> None:
    reporter, _ = make_reporter(tmp_path)
    reporter._tw = RecordingWriter()

    reporter._final_line_emitted = True
    reporter._emit_footer(plugin.TrimCounts(), plugin.FinalOutcome("COMPLETE", "PASS", "FULL", "DONE"))
    assert reporter._tw.lines == []

    reporter._stdout_tracker = None
    reporter._restore_stdout_tracker()

    reporter._selected_count = None
    reporter._xdist_collected_nodeids = {"test_a.py::test_one", "test_a.py::test_two"}
    assert reporter._resolved_selected_count() == 2

    reporter.stats["error"] = [make_collect_report()]
    assert reporter._resolved_selected_count() == 0
    reporter.stats.pop("error")

    reporter._xdist_collected_nodeids = set()
    reporter._item_outcomes = {"test_a.py::test_one": "passed"}
    assert reporter._resolved_selected_count() == 1

    reporter._xdist_deselected_nodeids = {"test_a.py::test_two"}
    assert reporter._resolved_deselected_count() == 1

    assert reporter._outcome_bucket(SimpleNamespace(failed=False, skipped=False, passed=False, when="call")) is None


def test_xdist_hooks_record_unique_selected_and_deselected_items(tmp_path: Path) -> None:
    reporter, _ = make_reporter(tmp_path)

    reporter.pytest_xdist_node_collection_finished(
        object(),
        ["test_a.py::test_one", "test_a.py::test_two"],
    )
    reporter.pytest_xdist_node_collection_finished(
        object(),
        ["test_a.py::test_one", "test_a.py::test_two"],
    )

    assert reporter._selected_count == 2

    reporter.pytest_testnodedown(
        SimpleNamespace(
            workeroutput={
                "trim_deselected_nodeids": [
                    "test_a.py::test_three",
                    42,
                ]
            }
        ),
        None,
    )
    reporter.pytest_testnodedown(
        SimpleNamespace(workeroutput={"trim_deselected_nodeids": ["test_a.py::test_three"]}),
        None,
    )
    reporter.pytest_testnodedown(SimpleNamespace(workeroutput=None), None)
    reporter.pytest_testnodedown(
        SimpleNamespace(workeroutput={"trim_deselected_nodeids": "test_a.py::test_four"}),
        None,
    )

    assert reporter._resolved_deselected_count() == 1


def test_trim_worker_reporter_exports_deselected_nodeids(tmp_path: Path) -> None:
    config = SimpleNamespace(workeroutput={})
    reporter = plugin.TrimWorkerReporter(config)

    reporter.pytest_deselected(
        [
            SimpleNamespace(nodeid="test_a.py::test_two"),
            SimpleNamespace(nodeid="test_a.py::test_three"),
        ]
    )
    reporter.pytest_sessionfinish(SimpleNamespace(), 0)

    assert config.workeroutput["trim_deselected_nodeids"] == [
        "test_a.py::test_three",
        "test_a.py::test_two",
    ]

    no_output_reporter = plugin.TrimWorkerReporter(SimpleNamespace())
    no_output_reporter.pytest_sessionfinish(SimpleNamespace(), 0)


def test_selection_followup_and_scope_helpers(tmp_path: Path) -> None:
    reporter, _ = make_reporter(tmp_path)
    assert reporter._stepwise_continue_required() is False
    assert reporter._stepwise_completed_after_resume() is False
    assert reporter._reran_previous_failures() is False
    assert reporter._successful_run_requires_full_followup() is False
    assert reporter._partial_scope_requested() is False
    assert reporter._explicit_selection_requested() is False
    assert reporter._selection_deselected_items() is False
    assert reporter._stepwise_partial_scope() is False
    assert reporter._resolved_scope(pytest.ExitCode.OK) == plugin.SCOPE_FULL
    assert reporter._no_tests_collected(pytest.ExitCode.NO_TESTS_COLLECTED) is True
    assert reporter._ordinary_failure(pytest.ExitCode.TESTS_FAILED) is True
    assert reporter._behavior_failure_detected() is False

    selection_reporter, _ = make_reporter(
        tmp_path,
        option_attrs={
            "file_or_dir": ["tests/test_scope_selection.py"],
            "keyword": "name",
            "markexpr": "slow",
            "deselect": ["tests/test_scope_selection.py::test_case"],
        },
    )
    selection_reporter.stats["deselected"] = [object()]
    assert selection_reporter._explicit_selection_requested() is True
    assert selection_reporter._selection_deselected_items() is True
    assert selection_reporter._partial_scope_requested() is True
    assert selection_reporter._resolved_scope(pytest.ExitCode.OK) == plugin.SCOPE_PARTIAL

    stepwise_plugin = SimpleNamespace(
        cached_info=SimpleNamespace(last_failed="test_case"),
        report_status=["skipping passed tests"],
    )
    stepwise_reporter, _ = make_reporter(
        tmp_path,
        getoptions={"stepwise": True},
        plugins={"stepwiseplugin": stepwise_plugin},
    )
    assert stepwise_reporter._stepwise_continue_required() is True
    assert stepwise_reporter._stepwise_completed_after_resume() is False
    assert stepwise_reporter._stepwise_partial_scope() is True

    resumed_plugin = SimpleNamespace(
        cached_info=SimpleNamespace(last_failed=None),
        report_status=["skipping previously passed items"],
    )
    resumed_reporter, _ = make_reporter(
        tmp_path,
        getoptions={"stepwise": True},
        plugins={"stepwiseplugin": resumed_plugin},
    )
    assert resumed_reporter._stepwise_continue_required() is False
    assert resumed_reporter._stepwise_completed_after_resume() is True
    assert resumed_reporter._successful_run_requires_full_followup() is True

    rerun_plugin = SimpleNamespace(
        _previously_failed_count=2,
        _report_status="rerun previous failures first",
    )
    rerun_reporter, _ = make_reporter(
        tmp_path,
        getoptions={"lf": True},
        plugins={"lfplugin": rerun_plugin},
    )
    assert rerun_reporter._reran_previous_failures() is True
    assert rerun_reporter._successful_run_requires_full_followup() is True

    failedfirst_reporter, _ = make_reporter(
        tmp_path,
        getoptions={"failedfirst": True},
        plugins={"lfplugin": rerun_plugin},
    )
    assert failedfirst_reporter._reran_previous_failures() is False
    assert failedfirst_reporter._successful_run_requires_full_followup() is False

    report = make_test_report(outcome="failed", longrepr="boom", when="call")
    rerun_reporter._issues = [report]
    assert rerun_reporter._behavior_failure_detected() is True


@pytest.mark.parametrize(
    ("exitstatus", "prepare", "expected"),
    [
        pytest.param(
            pytest.ExitCode.INTERNAL_ERROR,
            lambda reporter: None,
            ("ERROR", "UNKNOWN", "FULL", "INVESTIGATE"),
            id="internal-error-exitstatus",
        ),
        pytest.param(
            pytest.ExitCode.OK,
            lambda reporter: setattr(reporter, "_internal_error", True),
            ("ERROR", "UNKNOWN", "FULL", "INVESTIGATE"),
            id="internal-error-flag",
        ),
        pytest.param(
            pytest.ExitCode.OK,
            lambda reporter: setattr(reporter, "_keyboard_interrupt", True),
            ("INTERRUPTED", "UNKNOWN", "FULL", "ABORT"),
            id="keyboard-interrupt-flag",
        ),
        pytest.param(
            pytest.ExitCode.NO_TESTS_COLLECTED,
            lambda reporter: None,
            ("EMPTY", "NONE", "NONE", "ADJUST"),
            id="no-tests-collected",
        ),
        pytest.param(
            pytest.ExitCode.TESTS_FAILED,
            lambda reporter: reporter._issues.append(make_test_report(longrepr="boom", when="call")),
            ("COMPLETE", "FAIL", "FULL", "FIX"),
            id="test-failure-with-report",
        ),
        pytest.param(
            pytest.ExitCode.TESTS_FAILED,
            lambda reporter: None,
            ("COMPLETE", "FAIL", "FULL", "FIX"),
            id="test-failure-exitstatus",
        ),
        pytest.param(
            pytest.ExitCode.TESTS_FAILED,
            lambda reporter: reporter._issues.append(make_collect_report()),
            ("BROKEN", "BROKEN", "FULL", "REPAIR"),
            id="collection-failure",
        ),
        pytest.param(
            pytest.ExitCode.OK,
            lambda reporter: None,
            ("COMPLETE", "PASS", "FULL", "DONE"),
            id="clean-pass",
        ),
        pytest.param(
            pytest.ExitCode.OK,
            lambda reporter: setattr(
                reporter,
                "_successful_run_requires_full_followup",
                lambda: True,
            ),
            ("COMPLETE", "PASS", "FULL", "EXPAND"),
            id="pass-needs-followup",
        ),
        pytest.param(
            pytest.ExitCode.INTERRUPTED,
            lambda reporter: None,
            ("INTERRUPTED", "UNKNOWN", "FULL", "ABORT"),
            id="interrupted-exitstatus",
        ),
        pytest.param(
            pytest.ExitCode.USAGE_ERROR,
            lambda reporter: None,
            ("ERROR", "UNKNOWN", "FULL", "INVESTIGATE"),
            id="usage-error",
        ),
        pytest.param(
            pytest.ExitCode.NO_TESTS_COLLECTED + 99,
            lambda reporter: None,
            ("ERROR", "UNKNOWN", "FULL", "INVESTIGATE"),
            id="unknown-exitstatus",
        ),
    ],
)
def test_final_outcome_classifies_major_exit_paths(
    tmp_path: Path,
    exitstatus: int,
    prepare,
    expected: tuple[str, str, str, str],
) -> None:
    reporter, _ = make_reporter(tmp_path)
    reporter.pytest_sessionstart(SimpleNamespace(exitstatus=exitstatus))
    prepare(reporter)

    outcome = reporter._final_outcome()

    assert (outcome.run, outcome.verdict, outcome.scope, outcome.action) == expected
