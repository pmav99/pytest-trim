from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.support import DONE_FULL_LINE
from tests.support import DONE_PARTIAL_LINE
from tests.support import EMPTY_LINE
from tests.support import EXPAND_PARTIAL_LINE
from tests.support import FIX_FULL_LINE
from tests.support import FIX_PARTIAL_LINE
from tests.support import PLUGIN_NAME
from tests.support import non_empty_lines
from tests.support import output_lines
from tests.support import run_trim_pytest
from tests.support import subprocess_env


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
    assert output_lines(result) == [EMPTY_LINE]


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
    assert non_empty_lines(result.stdout) == [EMPTY_LINE]


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
    assert output_lines(second_result) == [EXPAND_PARTIAL_LINE]


def test_failedfirst_clean_rerun_stays_full_done(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    test_file = pytester.path / "test_failedfirst.py"
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

    second_result = run_trim_pytest(pytester, "--ff")

    assert second_result.ret == pytest.ExitCode.OK
    assert output_lines(second_result) == [DONE_FULL_LINE]


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
    assert output_lines(result) == [EMPTY_LINE]


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


def test_stepwise_failure_emits_fix_partial_status(
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


def test_stepwise_resume_to_end_emits_expand_partial_status(
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
    assert output_lines(second_result) == [EXPAND_PARTIAL_LINE]


def test_failure_reporting_stops_after_first_failure_with_x(
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

    result = run_trim_pytest(pytester, "-x")

    lines = output_lines(result)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert len(lines) == 2
    assert re.fullmatch(r"test_ordering\.py::test_first:\d+ - assert False", lines[0])
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
