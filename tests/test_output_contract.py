from __future__ import annotations

import re
from pathlib import Path

import pytest

from pytest_trim.plugin import ACTION_DONE
from pytest_trim.plugin import RUN_COMPLETE
from pytest_trim.plugin import SCOPE_FULL
from pytest_trim.plugin import VERDICT_PASS
from pytest_trim.plugin import render_final_line
from tests.support import DONE_FULL_LINE
from tests.support import ERROR_FULL_LINE
from tests.support import FIX_FULL_LINE
from tests.support import FIX_PARTIAL_LINE
from tests.support import INTERRUPTED_FULL_LINE
from tests.support import PLUGIN_NAME
from tests.support import REPAIR_FULL_LINE
from tests.support import TRIM_PREFIX
from tests.support import output_lines
from tests.support import run_trim_pytest


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

    result = run_trim_pytest(pytester, "--sw")

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
    assert lines[0].startswith("test_import.py - ")
    assert "ModuleNotFoundError" in lines[0]
    assert "definitely_missing_package" in lines[0]
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
    assert len(lines) == 2
    assert lines[0].startswith("test_group.py::test_group - ExceptionGroup: boom")
    assert "ValueError" not in lines[0]
    assert "RuntimeError" not in lines[0]
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
    assert len(lines) == 2
    assert lines[0].startswith("test_strict_xpass.py::test_xpass - ")
    assert "XPASS" in lines[0]
    assert "strict pass" in lines[0]
    assert lines[1] == FIX_FULL_LINE


def test_internal_error_emits_diagnostic_block_without_traceback_noise(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makeconftest(
        "def pytest_sessionstart(session):\n"
        "    raise RuntimeError('boom')\n"
    )

    result = run_trim_pytest(pytester)
    stdout = result.stdout.str()

    assert result.ret == pytest.ExitCode.INTERNAL_ERROR
    assert output_lines(result)[0].startswith("INTERNAL ERROR: ")
    assert output_lines(result)[0].endswith("boom")
    assert output_lines(result)[1] == ERROR_FULL_LINE
    assert "Traceback (most recent call last)" not in stdout
    assert "INTERNALERROR>" not in stdout


def test_abnormal_exit_emits_interrupted_status(
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

    assert not any(line.startswith(TRIM_PREFIX) for line in stdout.splitlines())
    assert not any(line.startswith(TRIM_PREFIX) for line in stderr.splitlines())


def test_collect_only_suppresses_protocol_line(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_collect=(
            "def test_one():\n"
            "    assert True\n"
        )
    )

    result = pytester.runpytest_subprocess("-p", PLUGIN_NAME, "--trim", "--collect-only")
    stdout = result.stdout.str()
    stderr = result.stderr.str()

    assert result.ret == pytest.ExitCode.OK
    assert not any(line.startswith(TRIM_PREFIX) for line in stdout.splitlines())
    assert not any(line.startswith(TRIM_PREFIX) for line in stderr.splitlines())


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
    stdout = result.stdout.str()
    stderr = result.stderr.str()

    assert result.ret == pytest.ExitCode.OK
    assert TRIM_PREFIX not in stdout
    assert TRIM_PREFIX not in stderr
    result.stdout.fnmatch_lines(["*collected 1 item*", "*test_default.py .*", "*1 passed*"])


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

    lines = output_lines(result)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert len(lines) == 2
    assert re.fullmatch(r"test_plain\.py::test_fail_no_trace - (?:Failed: )?plain boom", lines[0])
    assert not re.search(r"test_plain\.py::test_fail_no_trace:\d+ - ", lines[0])
    assert lines[1] == FIX_FULL_LINE
