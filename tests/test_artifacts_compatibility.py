from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pytest_trim.plugin import pytest_configure
from tests.support import DONE_FULL_LINE
from tests.support import DONE_PARTIAL_LINE
from tests.support import FIX_FULL_LINE
from tests.support import FIX_PARTIAL_LINE
from tests.support import PLUGIN_NAME
from tests.support import TRIM_PREFIX
from tests.support import artifact_path_from_lines
from tests.support import isolated_pytest_root
from tests.support import non_empty_lines
from tests.support import output_lines
from tests.support import run_trim_pytest
from tests.support import subprocess_env


def test_failure_artifact_file_contains_traceback_and_captured_sections(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    artifacts_dir = pytester.path / "artifacts"
    pytester.makepyfile(
        test_fail=(
            "import sys\n\n"
            "def test_fail():\n"
            "    print('HELLO-STDOUT')\n"
            "    sys.stderr.write('HELLO-STDERR\\n')\n"
            "    local_value = {'alpha': 1}\n"
            "    assert local_value['alpha'] == 2\n"
        )
    )

    result = run_trim_pytest(pytester, f"--trim-artifacts-dir={artifacts_dir}")

    lines = output_lines(result)
    artifact_path = artifact_path_from_lines(lines, pytester.path)

    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert artifact_path.exists()

    artifact_text = artifact_path.read_text(encoding="utf-8")
    assert "nodeid: test_fail.py::test_fail" in artifact_text
    assert "=== longreprtext ===" in artifact_text
    assert "assert local_value['alpha'] == 2" in artifact_text
    assert "=== Captured stdout call ===" in artifact_text
    assert "HELLO-STDOUT" in artifact_text
    assert "=== Captured stderr call ===" in artifact_text
    assert "HELLO-STDERR" in artifact_text
    assert lines[-1] == FIX_FULL_LINE


def test_failure_artifact_file_uses_pytest_cache_dir_by_default(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    pytester.makepyfile(
        test_fail=(
            "def test_fail():\n"
            "    assert 1 == 2\n"
        )
    )

    result = run_trim_pytest(pytester, "--trim-artifacts")

    lines = output_lines(result)
    artifact_path = artifact_path_from_lines(lines, pytester.path)

    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert artifact_path.exists()
    assert ".pytest_cache" in str(artifact_path)
    assert "pytest-trim" in str(artifact_path)
    assert lines[-1] == FIX_FULL_LINE


def test_failure_artifact_file_includes_locals_when_showlocals_is_enabled(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    artifacts_dir = pytester.path / "artifacts"
    pytester.makepyfile(
        test_fail=(
            "def test_fail():\n"
            "    local_value = {'alpha': 1, 'beta': [1, 2, 3]}\n"
            "    assert local_value['alpha'] == 2\n"
        )
    )

    result = run_trim_pytest(pytester, "-l", f"--trim-artifacts-dir={artifacts_dir}")

    lines = output_lines(result)
    artifact_path = artifact_path_from_lines(lines, pytester.path)

    assert result.ret == pytest.ExitCode.TESTS_FAILED
    artifact_text = artifact_path.read_text(encoding="utf-8")
    assert "showlocals: True" in artifact_text
    assert "local_value = {'alpha': 1, 'beta': [1, 2, 3]}" in artifact_text


def test_failure_artifact_file_notes_capture_disabled_under_s(
    pytester: pytest.Pytester,
    local_plugin_importable: Path,
) -> None:
    del local_plugin_importable

    artifacts_dir = pytester.path / "artifacts"
    pytester.makepyfile(
        test_fail=(
            "def test_fail():\n"
            "    print('LIVE-STDOUT')\n"
            "    assert 1 == 2\n"
        )
    )

    result = run_trim_pytest(pytester, "-s", f"--trim-artifacts-dir={artifacts_dir}")

    lines = output_lines(result)
    artifact_path = artifact_path_from_lines(lines, pytester.path)

    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert lines[0] == "LIVE-STDOUT"

    artifact_text = artifact_path.read_text(encoding="utf-8")
    assert "capture: no" in artifact_text
    assert "stdout/stderr capture is disabled (-s/--capture=no)." in artifact_text
    assert "=== Captured stdout call ===" not in artifact_text


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
    assert non_empty_lines(result.stdout) == [DONE_PARTIAL_LINE]
    assert result.stderr == ""


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
    assert len(lines) == 2
    assert re.fullmatch(r"test_fail\.py::test_one:\d+ - assert 1 == 2", lines[0])
    assert lines[1] == FIX_PARTIAL_LINE
    assert result.stderr == ""


def test_xdist_failure_can_write_artifact_file(tmp_path: Path) -> None:
    pytest.importorskip("xdist")

    package_root = Path(__file__).resolve().parents[1]
    artifacts_dir = tmp_path / "artifacts"
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
            f"--trim-artifacts-dir={artifacts_dir}",
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
    artifact_path = artifact_path_from_lines(lines, tmp_path)

    assert result.returncode == pytest.ExitCode.TESTS_FAILED
    assert len(lines) == 3
    assert re.fullmatch(r"test_fail\.py::test_one:\d+ - assert 1 == 2", lines[0])
    assert lines[1].startswith("  artifact: ")
    assert artifact_path.exists()
    assert "test_fail.py::test_one" in artifact_path.read_text(encoding="utf-8")
    assert lines[2] == FIX_PARTIAL_LINE
    assert result.stderr == ""


def test_pytest_cov_terminal_summary_is_visible_before_final_status_token(
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
        "--cov-fail-under=0",
        plugins=("pytest_cov",),
    )

    lines = output_lines(result)
    stdout = result.stdout.str()
    stderr = result.stderr.str()

    assert result.ret == pytest.ExitCode.OK
    assert lines[-1] == DONE_FULL_LINE
    assert any("tests coverage" in line for line in lines[:-1])
    assert any(line.startswith("Name") and "Cover" in line for line in lines[:-1])
    assert any("thing.py" in line and "%" in line for line in lines[:-1])
    assert any(line.startswith("TOTAL") and "%" in line for line in lines[:-1])
    assert "previously imported, but not measured" not in stdout
    assert "previously imported, but not measured" not in stderr


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

    lines = output_lines(result)
    stdout = result.stdout.str()
    stderr = result.stderr.str()

    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert lines[-1] == FIX_FULL_LINE
    assert any("tests coverage" in line for line in lines[:-1])
    assert any("Required test coverage of 100" in line and "not reached" in line for line in lines[:-1])
    assert "previously imported, but not measured" not in stdout
    assert "previously imported, but not measured" not in stderr


def test_plugin_is_disabled_on_xdist_worker_without_terminal_reporter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered: list[tuple[object, str]] = []
    reporter_created: list[object] = []
    wrapped_writers: list[object] = []

    class DummyPluginManager:
        def getplugin(self, name: str) -> object | None:
            return None

        def register(self, plugin: object, name: str) -> None:
            registered.append((plugin, name))

    class DummyConfig:
        pluginmanager = DummyPluginManager()

        def getoption(self, name: str, default: bool = False) -> bool:
            return {"--trim": True}.get(name, default)

    def record_reporter_creation(config: object) -> object:
        reporter_created.append(config)
        return object()

    def record_writer_wrap(writer: object) -> object:
        wrapped_writers.append(writer)
        return object()

    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    monkeypatch.setattr("pytest_trim.plugin.TrimReporter", record_reporter_creation)
    monkeypatch.setattr("pytest_trim.plugin.QuietTerminalWriter", record_writer_wrap)

    pytest_configure(DummyConfig())

    assert registered == []
    assert reporter_created == []
    assert wrapped_writers == []


def test_pytest11_autodiscovery_works_from_installed_dist_info(tmp_path: Path) -> None:
    package_root = Path(__file__).resolve().parents[1]
    src_package = package_root / "src" / "pytest_trim"
    installed_root = isolated_pytest_root(tmp_path)
    test_file = tmp_path / "test_ok.py"

    test_file.write_text(
        "def test_ok():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    missing_result = subprocess.run(
        [sys.executable, "-S", "-m", "pytest", "-q", str(test_file), "--trim"],
        capture_output=True,
        text=True,
        env=subprocess_env(installed_root, autoload_plugins=True),
        cwd=tmp_path,
        check=False,
    )

    assert missing_result.returncode == pytest.ExitCode.USAGE_ERROR
    assert "unrecognized arguments: --trim" in missing_result.stderr
    assert TRIM_PREFIX not in missing_result.stdout
    assert TRIM_PREFIX not in missing_result.stderr

    shutil.copytree(src_package, installed_root / "pytest_trim")
    dist_info = installed_root / "pytest_trim-0.1.0.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: pytest-trim\nVersion: 0.1.0\n",
        encoding="utf-8",
    )
    shutil.copytree(package_root / "src" / "pytest_trim_bootstrap", installed_root / "pytest_trim_bootstrap")
    (dist_info / "entry_points.txt").write_text(
        "[pytest11]\ntrim = pytest_trim_bootstrap\n",
        encoding="utf-8",
    )

    installed_result = subprocess.run(
        [sys.executable, "-S", "-m", "pytest", "-q", str(test_file), "--trim"],
        capture_output=True,
        text=True,
        env=subprocess_env(installed_root, autoload_plugins=True),
        cwd=tmp_path,
        check=False,
    )

    assert installed_result.returncode == 0
    assert non_empty_lines(installed_result.stdout) == [DONE_PARTIAL_LINE]
    assert installed_result.stderr == ""
