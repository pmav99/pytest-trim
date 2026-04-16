from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pytest_trim.plugin import ACTION_ADJUST
from pytest_trim.plugin import ACTION_DONE
from pytest_trim.plugin import ACTION_FIX
from pytest_trim.plugin import ACTION_REPAIR_RUN
from pytest_trim.plugin import ACTION_RUN_FULL
from pytest_trim.plugin import ACTION_STOP
from pytest_trim.plugin import RUN_BROKEN
from pytest_trim.plugin import RUN_COMPLETE
from pytest_trim.plugin import RUN_ERROR
from pytest_trim.plugin import RUN_INTERRUPTED
from pytest_trim.plugin import RUN_NO_TESTS
from pytest_trim.plugin import SCOPE_FULL
from pytest_trim.plugin import SCOPE_NONE
from pytest_trim.plugin import SCOPE_PARTIAL
from pytest_trim.plugin import VERDICT_FAIL
from pytest_trim.plugin import VERDICT_NONE
from pytest_trim.plugin import VERDICT_PASS
from pytest_trim.plugin import VERDICT_UNKNOWN
from pytest_trim.plugin import pytest_configure
from pytest_trim.plugin import render_final_line


PLUGIN_NAME = "pytest_trim.plugin"


@pytest.fixture
def local_plugin_importable(monkeypatch: pytest.MonkeyPatch) -> Path:
    src_dir = Path(__file__).resolve().parents[1] / "src"
    monkeypatch.syspath_prepend(str(src_dir))

    existing = os.environ.get("PYTHONPATH")
    pythonpath = str(src_dir) if not existing else f"{src_dir}{os.pathsep}{existing}"
    monkeypatch.setenv("PYTHONPATH", pythonpath)
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    return src_dir


def run_trim_pytest(
    pytester: pytest.Pytester,
    *args: str,
    plugins: tuple[str, ...] = (),
) -> pytest.RunResult:
    plugin_args: list[str] = []
    for plugin in plugins:
        plugin_args.extend(["-p", plugin])

    return pytester.runpytest("-p", PLUGIN_NAME, *plugin_args, "--trim", *args)


def non_empty_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def output_lines(result: pytest.RunResult) -> list[str]:
    return non_empty_lines(result.stdout.str())


def final_line(run: str, verdict: str, scope: str, action: str) -> str:
    return f"RUN={run} VERDICT={verdict} SCOPE={scope} ACTION={action}"


DONE_FULL_LINE = final_line(RUN_COMPLETE, VERDICT_PASS, SCOPE_FULL, ACTION_DONE)
DONE_PARTIAL_LINE = final_line(RUN_COMPLETE, VERDICT_PASS, SCOPE_PARTIAL, ACTION_DONE)
RUN_FULL_PARTIAL_LINE = final_line(RUN_COMPLETE, VERDICT_PASS, SCOPE_PARTIAL, ACTION_RUN_FULL)
FIX_FULL_LINE = final_line(RUN_COMPLETE, VERDICT_FAIL, SCOPE_FULL, ACTION_FIX)
FIX_PARTIAL_LINE = final_line(RUN_COMPLETE, VERDICT_FAIL, SCOPE_PARTIAL, ACTION_FIX)
REPAIR_FULL_LINE = final_line(RUN_BROKEN, VERDICT_FAIL, SCOPE_FULL, ACTION_REPAIR_RUN)
REPAIR_PARTIAL_LINE = final_line(RUN_BROKEN, VERDICT_FAIL, SCOPE_PARTIAL, ACTION_REPAIR_RUN)
NO_TESTS_LINE = final_line(RUN_NO_TESTS, VERDICT_NONE, SCOPE_NONE, ACTION_ADJUST)
ERROR_FULL_LINE = final_line(RUN_ERROR, VERDICT_UNKNOWN, SCOPE_FULL, ACTION_STOP)
INTERRUPTED_FULL_LINE = final_line(RUN_INTERRUPTED, VERDICT_UNKNOWN, SCOPE_FULL, ACTION_STOP)


def subprocess_env(*pythonpaths: Path, autoload_plugins: bool = False) -> dict[str, str]:
    env = os.environ.copy()

    path_entries = [str(path) for path in pythonpaths]
    existing = env.get("PYTHONPATH")
    if existing:
        path_entries.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(path_entries)

    if autoload_plugins:
        env.pop("PYTEST_DISABLE_PLUGIN_AUTOLOAD", None)
    else:
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"

    return env


def test_render_final_line_uses_new_protocol_order() -> None:
    assert render_final_line(RUN_COMPLETE, VERDICT_PASS, SCOPE_FULL, ACTION_DONE) == DONE_FULL_LINE


def test_all_passes_emit_standard_pass_message(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_ok=(
            "def test_one():\n"
            "    assert True\n\n"
            "def test_two():\n"
            "    assert 3 == 3\n"
        )
    )

    result = run_trim_pytest(pytester)

    assert result.ret == pytest.ExitCode.OK
    assert output_lines(result) == [DONE_FULL_LINE]


def test_single_test_failure_emits_one_line(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_fail=(
            "def test_boom():\n"
            "    assert 1 == 2\n"
        )
    )

    result = run_trim_pytest(pytester)

    lines = output_lines(result)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert len(lines) == 2
    assert re.fullmatch(r"test_fail\.py::test_boom:\d+ - assert 1 == 2", lines[0])
    assert lines[1] == FIX_FULL_LINE


def test_assertion_explanations_keep_useful_detail_without_pytest_hints(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_diff=(
            "def test_list_diff():\n"
            "    assert [1, 2, 3] == [1, 2, 3, 4]\n"
        )
    )

    result = run_trim_pytest(pytester, "--ff", "--nf", "--sw")

    lines = output_lines(result)
    assert result.ret == pytest.ExitCode.INTERRUPTED
    assert len(lines) == 3
    assert re.fullmatch(
        r"test_diff\.py::test_list_diff:\d+ - assert \[1, 2, 3\] == \[1, 2, 3, 4\]",
        lines[0],
    )
    assert lines[1] == "  detail: Right contains one more item: 4"
    assert lines[2] == FIX_PARTIAL_LINE


@pytest.mark.parametrize("verbosity", ["-v", "-vv", "-vvv", "--verbose"])
def test_verbose_assertion_explanations_ignore_full_diff_block(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
    verbosity: str,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_diff=(
            "def test_list_diff():\n"
            "    assert [1, 2, 3] == [1, 2, 3, 4]\n"
        )
    )

    result = run_trim_pytest(pytester, verbosity)

    lines = output_lines(result)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert len(lines) == 3
    assert re.fullmatch(
        r"test_diff\.py::test_list_diff:\d+ - assert \[1, 2, 3\] == \[1, 2, 3, 4\]",
        lines[0],
    )
    assert lines[1] == "  detail: Right contains one more item: 4"
    assert lines[2] == FIX_FULL_LINE


def test_rich_assertion_output_caps_detail_lines(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_diff=(
            "def test_dict_diff():\n"
            "    assert {'a': 1, 'b': 2, 'c': 3} == {'a': 9, 'b': 8, 'c': 7}\n"
        )
    )

    result = run_trim_pytest(pytester)

    lines = output_lines(result)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert len(lines) == 5
    assert re.fullmatch(r"test_diff\.py::test_dict_diff:\d+ - assert .* == .*", lines[0])
    assert lines[1].startswith("  detail: Differing items:")
    assert lines[2].startswith("  detail: Differing items:")
    assert lines[3] == "  detail: (+1 more details omitted)"
    assert lines[4] == FIX_FULL_LINE


def test_string_diffs_are_grouped_into_compact_detail_lines(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_diff=(
            "def test_string_diff():\n"
            "    assert 'abc' == 'axc'\n"
        )
    )

    result = run_trim_pytest(pytester)

    lines = output_lines(result)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert len(lines) == 3
    assert re.fullmatch(r"test_diff\.py::test_string_diff:\d+ - assert 'abc' == 'axc'", lines[0])
    assert lines[1] == "  detail: - axc | + abc"
    assert lines[2] == FIX_FULL_LINE


@pytest.mark.parametrize("verbosity", ["-v", "-vv", "-vvv", "--verbose"])
def test_verbose_rich_assertion_output_still_caps_useful_details(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
    verbosity: str,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_diff=(
            "def test_dict_diff():\n"
            "    assert {'a': 1, 'b': 2, 'c': 3} == {'a': 9, 'b': 8, 'c': 7}\n"
        )
    )

    result = run_trim_pytest(pytester, verbosity)

    lines = output_lines(result)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert len(lines) == 5
    assert re.fullmatch(r"test_diff\.py::test_dict_diff:\d+ - assert .* == .*", lines[0])
    assert lines[1].startswith("  detail: Differing items:")
    assert lines[2].startswith("  detail: Differing items:")
    assert lines[3] == "  detail: (+1 more details omitted)"
    assert lines[4] == FIX_FULL_LINE


def test_multiple_failures_emit_one_line_each(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_failures=(
            "def test_first():\n"
            "    assert False\n\n"
            "def test_second():\n"
            "    raise RuntimeError('boom')\n"
        )
    )

    result = run_trim_pytest(pytester)

    lines = output_lines(result)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert len(lines) == 3
    assert re.fullmatch(r"test_failures\.py::test_first:\d+ - assert False", lines[0])
    assert re.fullmatch(
        r"test_failures\.py::test_second:\d+ - RuntimeError: boom",
        lines[1],
    )
    assert lines[2] == FIX_FULL_LINE


def test_setup_failure_is_reported(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_setup=(
            "import pytest\n\n"
            "@pytest.fixture\n"
            "def broken_fixture():\n"
            "    raise RuntimeError('boom in setup')\n\n"
            "def test_uses_fixture(broken_fixture):\n"
            "    assert True\n"
        )
    )

    result = run_trim_pytest(pytester)

    lines = output_lines(result)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert len(lines) == 2
    assert re.fullmatch(
        r"test_setup\.py::test_uses_fixture:\d+ - RuntimeError: boom in setup",
        lines[0],
    )
    assert lines[1] == REPAIR_FULL_LINE


def test_teardown_failure_is_reported(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_teardown=(
            "import pytest\n\n"
            "@pytest.fixture\n"
            "def broken_teardown():\n"
            "    yield\n"
            "    raise RuntimeError('boom in teardown')\n\n"
            "def test_ok(broken_teardown):\n"
            "    assert True\n"
        )
    )

    result = run_trim_pytest(pytester)

    lines = output_lines(result)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert len(lines) == 2
    assert re.fullmatch(
        r"test_teardown\.py::test_ok:\d+ - RuntimeError: boom in teardown",
        lines[0],
    )
    assert lines[1] == REPAIR_FULL_LINE


def test_call_and_teardown_failures_emit_one_issue_block_each(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_multi=(
            "import pytest\n\n"
            "@pytest.fixture\n"
            "def broken_teardown():\n"
            "    yield\n"
            "    raise RuntimeError('boom in teardown')\n\n"
            "def test_both_failures(broken_teardown):\n"
            "    assert 1 == 2\n"
        )
    )

    result = run_trim_pytest(pytester)

    lines = output_lines(result)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert len(lines) == 3
    assert re.fullmatch(r"test_multi\.py::test_both_failures:\d+ - assert 1 == 2", lines[0])
    assert re.fullmatch(
        r"test_multi\.py::test_both_failures:\d+ - RuntimeError: boom in teardown",
        lines[1],
    )
    assert lines[2] == FIX_FULL_LINE


def test_collection_syntax_error_is_reported_with_line_number(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_syntax=(
            "def test_ok():\n"
            "    assert True\n\n"
            "def broken_syntax(\n"
            "    pass\n"
        )
    )

    result = run_trim_pytest(pytester)

    lines = output_lines(result)
    assert result.ret == pytest.ExitCode.INTERRUPTED
    assert len(lines) == 2
    assert re.fullmatch(r"test_syntax\.py:\d+ - .*SyntaxError.*", lines[0])
    assert lines[1] == REPAIR_FULL_LINE


def test_collection_import_error_is_reported(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_import=(
            "import definitely_missing_package\n\n"
            "def test_never_runs():\n"
            "    assert True\n"
        )
    )

    result = run_trim_pytest(pytester)

    lines = output_lines(result)
    assert result.ret == pytest.ExitCode.INTERRUPTED
    assert len(lines) == 2
    assert re.fullmatch(
        r"test_import\.py - E\s+ModuleNotFoundError: No module named 'definitely_missing_package'",
        lines[0],
    )
    assert lines[1] == REPAIR_FULL_LINE


@pytest.mark.parametrize(
    ("traceback_style", "expected_pattern"),
    [
        ("line", r"test_fail\.py::test_fail - assert 1 == 2"),
        ("short", r"test_fail\.py::test_fail:\d+ - assert 1 == 2"),
        ("native", r"test_fail\.py::test_fail - assert 1 == 2"),
        ("no", r"test_fail\.py::test_fail - assert 1 == 2"),
    ],
)
def test_traceback_style_variants_keep_machine_friendly_headline(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
    traceback_style: str,
    expected_pattern: str,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_fail=(
            "def test_fail():\n"
            "    assert 1 == 2\n"
        )
    )

    result = run_trim_pytest(pytester, f"--tb={traceback_style}")

    lines = output_lines(result)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert len(lines) == 2
    assert re.fullmatch(expected_pattern, lines[0])
    assert lines[1] == FIX_FULL_LINE


def test_exception_group_is_reported_compactly(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_group=(
            "def test_group():\n"
            "    raise ExceptionGroup('boom', [ValueError('one'), RuntimeError('two')])\n"
        )
    )

    result = run_trim_pytest(pytester)

    lines = output_lines(result)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert lines == [
        "test_group.py::test_group - ExceptionGroup: boom (2 sub-exceptions)",
        FIX_FULL_LINE,
    ]


def test_plugin_is_inactive_without_trim_flag(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_default=(
            "def test_ok():\n"
            "    assert True\n"
        )
    )

    result = pytester.runpytest("-p", PLUGIN_NAME)

    assert result.ret == pytest.ExitCode.OK
    result.stdout.fnmatch_lines(["*collected 1 item*", "*test_default.py .*", "*1 passed*"])


def test_pass_with_stepwise_from_clean_state_uses_plain_pass_message(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_clean_stepwise=(
            "def test_one():\n"
            "    assert True\n\n"
            "def test_two():\n"
            "    assert True\n"
        )
    )

    result = run_trim_pytest(pytester, "--sw")

    assert result.ret == pytest.ExitCode.OK
    assert output_lines(result) == [DONE_FULL_LINE]


def test_no_tests_collected_emits_no_tests_status(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_example=(
            "def test_ok():\n"
            "    assert True\n"
        )
    )

    result = run_trim_pytest(pytester, "-k", "does_not_match_anything")

    assert result.ret == pytest.ExitCode.NO_TESTS_COLLECTED
    assert output_lines(result) == [NO_TESTS_LINE]


def test_no_tests_subprocess_keeps_pytest_exit_code(tmp_path: Path) -> None:
    package_root = Path(__file__).resolve().parents[1]
    test_file = tmp_path / "test_ok.py"
    test_file.write_text(
        "def test_one():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            PLUGIN_NAME,
            "--trim",
            "-k",
            "does_not_match_anything",
            str(test_file),
        ],
        capture_output=True,
        text=True,
        env=subprocess_env(package_root / "src"),
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == pytest.ExitCode.NO_TESTS_COLLECTED
    assert non_empty_lines(result.stdout) == [NO_TESTS_LINE]


def test_last_failed_clean_rerun_requests_one_full_follow_up(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    test_file = pytester.path / "test_last_failed.py"
    test_file.write_text(
        "def test_first():\n"
        "    assert False\n\n"
        "def test_second():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    first_result = run_trim_pytest(pytester)
    assert first_result.ret == pytest.ExitCode.TESTS_FAILED

    test_file.write_text(
        "def test_first():\n"
        "    assert True\n\n"
        "def test_second():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    second_result = run_trim_pytest(pytester, "--lf")

    assert second_result.ret == pytest.ExitCode.OK
    assert output_lines(second_result) == [RUN_FULL_PARTIAL_LINE]


def test_last_failed_failure_stays_partial_fix_signal(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_last_failed=(
            "def test_first():\n"
            "    assert False\n\n"
            "def test_second():\n"
            "    assert True\n"
        )
    )

    first_result = run_trim_pytest(pytester)
    assert first_result.ret == pytest.ExitCode.TESTS_FAILED

    second_result = run_trim_pytest(pytester, "--lf")

    lines = output_lines(second_result)
    assert second_result.ret == pytest.ExitCode.TESTS_FAILED
    assert len(lines) == 2
    assert re.fullmatch(r"test_last_failed\.py::test_first:\d+ - assert False", lines[0])
    assert lines[1] == FIX_PARTIAL_LINE


def test_last_failed_without_cached_failures_falls_back_to_full_run(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_ok=(
            "def test_one():\n"
            "    assert True\n"
        )
    )

    result = run_trim_pytest(pytester, "--lf")

    assert result.ret == pytest.ExitCode.OK
    assert output_lines(result) == [DONE_FULL_LINE]


def test_last_failed_without_cached_failures_can_emit_no_tests(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_ok=(
            "def test_one():\n"
            "    assert True\n"
        )
    )

    result = run_trim_pytest(pytester, "--lf", "--lfnf=none")

    assert result.ret == pytest.ExitCode.NO_TESTS_COLLECTED
    assert output_lines(result) == [NO_TESTS_LINE]


def test_maxfail_reports_only_seen_failures(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_maxfail=(
            "def test_first():\n"
            "    assert False\n\n"
            "def test_second():\n"
            "    assert False\n"
        )
    )

    result = run_trim_pytest(pytester, "--maxfail=1")

    lines = output_lines(result)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert len(lines) == 2
    assert re.fullmatch(r"test_maxfail\.py::test_first:\d+ - assert False", lines[0])
    assert lines[1] == FIX_FULL_LINE


def test_stepwise_failure_emits_repeat_status(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_stepwise=(
            "def test_first():\n"
            "    assert False\n\n"
            "def test_second():\n"
            "    assert True\n"
        )
    )

    result = run_trim_pytest(pytester, "--sw")

    lines = output_lines(result)
    assert result.ret == pytest.ExitCode.INTERRUPTED
    assert len(lines) == 2
    assert re.fullmatch(r"test_stepwise\.py::test_first:\d+ - assert False", lines[0])
    assert lines[1] == FIX_PARTIAL_LINE


def test_stepwise_resume_to_end_emits_rerun_status(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    test_file = pytester.path / "test_resume.py"
    test_file.write_text(
        "def test_first():\n"
        "    assert False\n\n"
        "def test_second():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    first_result = run_trim_pytest(pytester, "--sw")

    first_lines = output_lines(first_result)
    assert first_result.ret == pytest.ExitCode.INTERRUPTED
    assert len(first_lines) == 2
    assert re.fullmatch(r"test_resume\.py::test_first:\d+ - assert False", first_lines[0])
    assert first_lines[1] == FIX_PARTIAL_LINE

    test_file.write_text(
        "def test_first():\n"
        "    assert True\n\n"
        "def test_second():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    second_result = run_trim_pytest(pytester, "--sw")

    assert second_result.ret == pytest.ExitCode.OK
    assert output_lines(second_result) == [RUN_FULL_PARTIAL_LINE]


def test_failure_reporting_works_with_ff_nf_and_x(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_ordering=(
            "def test_first():\n"
            "    assert False\n\n"
            "def test_second():\n"
            "    assert False\n"
        )
    )

    result = run_trim_pytest(pytester, "--ff", "--nf", "-x")

    lines = output_lines(result)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert len(lines) == 2
    assert re.fullmatch(r"test_ordering\.py::test_first:\d+ - assert False", lines[0])
    assert lines[1] == FIX_FULL_LINE


def test_parametrized_tests_use_full_nodeid(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_params=(
            "import pytest\n\n"
            "@pytest.mark.parametrize('value', [0, 1], ids=['zero', 'one'])\n"
            "def test_param(value):\n"
            "    assert value\n"
        )
    )

    result = run_trim_pytest(pytester)

    lines = output_lines(result)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert len(lines) == 2
    assert re.fullmatch(
        r"test_params\.py::test_param\[zero\]:\d+ - assert 0",
        lines[0],
    )
    assert lines[1] == FIX_FULL_LINE


def test_skip_xfail_xpass_and_deselected_do_not_emit_lines(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_outcomes=(
            "import pytest\n\n"
            "def test_skip():\n"
            "    pytest.skip('not today')\n\n"
            "@pytest.mark.xfail(reason='expected failure')\n"
            "def test_xfail():\n"
            "    assert False\n\n"
            "@pytest.mark.xfail(reason='unexpected pass')\n"
            "def test_xpass():\n"
            "    assert True\n\n"
            "def test_deselected():\n"
            "    assert True\n"
        )
    )

    result = run_trim_pytest(pytester, "-k", "not deselected")

    assert result.ret == pytest.ExitCode.OK
    assert output_lines(result) == [DONE_PARTIAL_LINE]


def test_strict_xpass_is_reported_as_failure(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_strict_xpass=(
            "import pytest\n\n"
            "@pytest.mark.xfail(reason='strict pass', strict=True)\n"
            "def test_xpass():\n"
            "    assert True\n"
        )
    )

    result = run_trim_pytest(pytester)

    lines = output_lines(result)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert lines == [
        "test_strict_xpass.py::test_xpass - [XPASS(strict)] strict pass",
        FIX_FULL_LINE,
    ]


def test_internal_error_emits_error_status(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makeconftest(
        "def pytest_sessionstart(session):\n"
        "    raise RuntimeError('boom')\n"
    )

    result = run_trim_pytest(pytester)

    assert result.ret == pytest.ExitCode.INTERNAL_ERROR
    assert output_lines(result)[-1] == ERROR_FULL_LINE


def test_abnormal_exit_emits_error_status(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_exit=(
            "import pytest\n\n"
            "def test_exit():\n"
            "    pytest.exit('bye')\n"
        )
    )

    result = run_trim_pytest(pytester)

    assert result.ret == pytest.ExitCode.INTERRUPTED
    assert output_lines(result) == [INTERRUPTED_FULL_LINE]


def test_usage_error_does_not_claim_final_status_token(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    result = pytester.runpytest("-p", PLUGIN_NAME, "--trim", "--definitely-invalid-option")

    stdout = result.stdout.str()
    stderr = result.stderr.str()

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "unrecognized arguments: --definitely-invalid-option" in stderr
    for token in (
        DONE_FULL_LINE,
        DONE_PARTIAL_LINE,
        RUN_FULL_PARTIAL_LINE,
        FIX_FULL_LINE,
        FIX_PARTIAL_LINE,
        REPAIR_FULL_LINE,
        REPAIR_PARTIAL_LINE,
        NO_TESTS_LINE,
        ERROR_FULL_LINE,
        INTERRUPTED_FULL_LINE,
    ):
        assert token not in stdout.splitlines()
        assert token not in stderr.splitlines()


def test_terminal_summary_hooks_still_run_without_extra_output(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makeconftest(
        "from pathlib import Path\n\n"
        "def pytest_terminal_summary(terminalreporter, exitstatus, config):\n"
        "    del exitstatus, config\n"
        "    Path('summary-called.txt').write_text('yes', encoding='utf-8')\n"
        "    terminalreporter.write_line('should stay hidden')\n"
    )
    pytester.makepyfile(
        test_ok=(
            "def test_one():\n"
            "    assert True\n"
        )
    )

    result = run_trim_pytest(pytester)

    assert result.ret == pytest.ExitCode.OK
    assert output_lines(result) == [DONE_FULL_LINE]
    assert (pytester.path / "summary-called.txt").read_text(encoding="utf-8") == "yes"


def test_terminal_summary_prints_before_final_status_token(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makeconftest(
        "def pytest_terminal_summary(terminalreporter, exitstatus, config):\n"
        "    del terminalreporter, exitstatus, config\n"
        "    print('SUMMARY-PRINT')\n"
    )
    pytester.makepyfile(
        test_ok=(
            "def test_one():\n"
            "    assert True\n"
        )
    )

    result = run_trim_pytest(pytester)

    assert result.ret == pytest.ExitCode.OK
    assert output_lines(result) == ["SUMMARY-PRINT", DONE_FULL_LINE]


def test_terminal_summary_write_raw_stays_hidden(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makeconftest(
        "def pytest_terminal_summary(terminalreporter, exitstatus, config):\n"
        "    del exitstatus, config\n"
        "    terminalreporter._tw.write_raw('RAW-LEAK\\n')\n"
    )
    pytester.makepyfile(
        test_ok=(
            "def test_one():\n"
            "    assert True\n"
        )
    )

    result = run_trim_pytest(pytester)

    assert result.ret == pytest.ExitCode.OK
    assert output_lines(result) == [DONE_FULL_LINE]


def test_capture_disabled_output_still_finishes_with_final_status_token(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_ok=(
            "def test_one():\n"
            "    print('TEST-OUTPUT')\n"
            "    assert True\n"
        )
    )

    result = run_trim_pytest(pytester, "-s")

    assert result.ret == pytest.ExitCode.OK
    assert output_lines(result) == ["TEST-OUTPUT", DONE_FULL_LINE]


def test_capture_disabled_stderr_output_still_finishes_with_final_status_token(
    tmp_path: Path,
) -> None:
    package_root = Path(__file__).resolve().parents[1]
    test_file = tmp_path / "test_err.py"
    test_file.write_text(
        "import sys\n\n"
        "def test_one():\n"
        "    sys.stderr.write('ERR-LINE\\n')\n"
        "    assert True\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            PLUGIN_NAME,
            "--trim",
            "-s",
            str(test_file),
        ],
        capture_output=True,
        text=True,
        env=subprocess_env(package_root / "src"),
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 0
    assert non_empty_lines(result.stdout)[-1] == DONE_PARTIAL_LINE
    assert result.stderr.splitlines() == ["ERR-LINE"]


def test_late_exitstatus_mutation_changes_final_status_token(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makeconftest(
        "import pytest\n\n"
        "def pytest_terminal_summary(terminalreporter, exitstatus, config):\n"
        "    del exitstatus, config\n"
        "    terminalreporter._session.exitstatus = pytest.ExitCode.TESTS_FAILED\n"
    )
    pytester.makepyfile(
        test_ok=(
            "def test_one():\n"
            "    assert True\n"
        )
    )

    result = run_trim_pytest(pytester)

    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert output_lines(result) == [FIX_FULL_LINE]


def test_xdist_run_keeps_final_status_token(tmp_path: Path) -> None:
    pytest.importorskip("xdist")

    package_root = Path(__file__).resolve().parents[1]
    test_file = tmp_path / "test_ok.py"
    test_file.write_text(
        "def test_one():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "xdist.plugin",
            "-p",
            PLUGIN_NAME,
            "--trim",
            "-n",
            "2",
            str(test_file),
        ],
        capture_output=True,
        text=True,
        env=subprocess_env(package_root / "src"),
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 0
    assert non_empty_lines(result.stdout)[-1] == DONE_PARTIAL_LINE


def test_xdist_failure_keeps_trimmed_headline_before_final_status_token(tmp_path: Path) -> None:
    pytest.importorskip("xdist")

    package_root = Path(__file__).resolve().parents[1]
    test_file = tmp_path / "test_fail.py"
    test_file.write_text(
        "def test_one():\n"
        "    assert 1 == 2\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "xdist.plugin",
            "-p",
            PLUGIN_NAME,
            "--trim",
            "-n",
            "2",
            str(test_file),
        ],
        capture_output=True,
        text=True,
        env=subprocess_env(package_root / "src"),
        cwd=tmp_path,
        check=False,
    )

    lines = non_empty_lines(result.stdout)
    assert result.returncode == pytest.ExitCode.TESTS_FAILED
    assert re.fullmatch(r"test_fail\.py::test_one:\d+ - assert 1 == 2", lines[-2])
    assert lines[-1] == FIX_PARTIAL_LINE


def test_pytest_cov_fail_under_changes_final_status_token(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    pytest.importorskip("pytest_cov")
    del local_plugin_importable

    pytester.makepyfile(
        thing=(
            "def meaning():\n"
            "    return 42\n\n"
            "def unused():\n"
            "    return 0\n"
        ),
        test_ok=(
            "import thing\n\n"
            "def test_one():\n"
            "    assert thing.meaning() == 42\n"
        ),
    )

    result = run_trim_pytest(
        pytester,
        "--cov=thing",
        "--cov-fail-under=100",
        plugins=("pytest_cov",),
    )

    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert output_lines(result) == [FIX_FULL_LINE]


def test_plugin_is_disabled_on_xdist_worker_without_terminal_reporter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered: list[tuple[object, str]] = []

    class DummyPluginManager:
        def getplugin(self, name: str) -> object | None:
            assert name == "terminalreporter"
            return None

        def register(self, plugin: object, name: str) -> None:
            registered.append((plugin, name))

    class DummyConfig:
        pluginmanager = DummyPluginManager()

        def getoption(self, name: str, default: bool = False) -> bool:
            assert name == "--trim"
            return True

    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")

    pytest_configure(DummyConfig())

    assert registered == []


def test_pytrace_false_failure_omits_line_number_cleanly(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_plain=(
            "import pytest\n\n"
            "def test_fail_no_trace():\n"
            "    pytest.fail('plain boom', pytrace=False)\n"
        )
    )

    result = run_trim_pytest(pytester)

    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert output_lines(result) == [
        "test_plain.py::test_fail_no_trace - Failed: plain boom",
        FIX_FULL_LINE,
    ]


def test_pytest11_autodiscovery_works_from_installed_dist_info(tmp_path: Path) -> None:
    package_root = Path(__file__).resolve().parents[1]
    src_package = package_root / "src" / "pytest_trim"
    installed_root = tmp_path / "installed"
    installed_package = installed_root / "pytest_trim"
    dist_info = installed_root / "pytest_trim-0.1.0.dist-info"
    test_file = tmp_path / "test_ok.py"

    shutil.copytree(src_package, installed_package)
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: pytest-trim\nVersion: 0.1.0\n",
        encoding="utf-8",
    )
    (dist_info / "entry_points.txt").write_text(
        "[pytest11]\ntrim = pytest_trim.plugin\n",
        encoding="utf-8",
    )
    test_file.write_text(
        "def test_ok():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(test_file), "--trim"],
        capture_output=True,
        text=True,
        env=subprocess_env(installed_root, autoload_plugins=True),
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 0
    assert non_empty_lines(result.stdout)[-1] == DONE_PARTIAL_LINE
