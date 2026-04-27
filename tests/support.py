from __future__ import annotations

import importlib.metadata
import os
import shutil
from pathlib import Path

import pytest

from pytest_trim.plugin import ACTION_ABORT
from pytest_trim.plugin import ACTION_ADJUST
from pytest_trim.plugin import ACTION_DONE
from pytest_trim.plugin import ACTION_EXPAND
from pytest_trim.plugin import ACTION_FIX
from pytest_trim.plugin import ACTION_INVESTIGATE
from pytest_trim.plugin import ACTION_REPAIR
from pytest_trim.plugin import RUN_BROKEN
from pytest_trim.plugin import RUN_COMPLETE
from pytest_trim.plugin import RUN_EMPTY
from pytest_trim.plugin import RUN_ERROR
from pytest_trim.plugin import RUN_INTERRUPTED
from pytest_trim.plugin import SCOPE_FULL
from pytest_trim.plugin import SCOPE_NONE
from pytest_trim.plugin import SCOPE_PARTIAL
from pytest_trim.plugin import TRIM_PREFIX
from pytest_trim.plugin import VERDICT_BROKEN
from pytest_trim.plugin import VERDICT_FAIL
from pytest_trim.plugin import VERDICT_NONE
from pytest_trim.plugin import VERDICT_PASS
from pytest_trim.plugin import VERDICT_UNKNOWN
from pytest_trim.plugin import TrimCounts
from pytest_trim.plugin import render_counts_line


PLUGIN_NAME = "pytest_trim_bootstrap"
ISOLATED_PYTEST_DISTRIBUTIONS = ("pytest", "pluggy", "packaging", "iniconfig", "Pygments")


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
    return [line for line in non_empty_lines(result.stdout.str()) if not line.startswith(f"{TRIM_PREFIX}counts ")]


def artifact_path_from_lines(lines: list[str], root: Path) -> Path:
    artifact_lines = [line for line in lines if line.startswith("  artifact: ")]
    assert len(artifact_lines) == 1

    artifact_text = artifact_lines[0][len("  artifact: ") :]
    artifact_path = Path(artifact_text)
    if artifact_path.is_absolute():
        return artifact_path

    return root / artifact_path


def final_line(run: str, verdict: str, scope: str, action: str) -> str:
    return f"{TRIM_PREFIX}result RUN={run} VERDICT={verdict} SCOPE={scope} ACTION={action}"


def counts_line(
    *,
    selected: int = 0,
    executed: int = 0,
    passed: int = 0,
    failed: int = 0,
    errors: int = 0,
    collection_errors: int = 0,
    skipped: int = 0,
    xfailed: int = 0,
    xpassed: int = 0,
    deselected: int = 0,
) -> str:
    return render_counts_line(
        TrimCounts(
            selected=selected,
            executed=executed,
            passed=passed,
            failed=failed,
            errors=errors,
            collection_errors=collection_errors,
            skipped=skipped,
            xfailed=xfailed,
            xpassed=xpassed,
            deselected=deselected,
        )
    )


DONE_FULL_LINE = final_line(RUN_COMPLETE, VERDICT_PASS, SCOPE_FULL, ACTION_DONE)
DONE_PARTIAL_LINE = final_line(RUN_COMPLETE, VERDICT_PASS, SCOPE_PARTIAL, ACTION_DONE)
EXPAND_PARTIAL_LINE = final_line(RUN_COMPLETE, VERDICT_PASS, SCOPE_PARTIAL, ACTION_EXPAND)
FIX_FULL_LINE = final_line(RUN_COMPLETE, VERDICT_FAIL, SCOPE_FULL, ACTION_FIX)
FIX_PARTIAL_LINE = final_line(RUN_COMPLETE, VERDICT_FAIL, SCOPE_PARTIAL, ACTION_FIX)
REPAIR_FULL_LINE = final_line(RUN_BROKEN, VERDICT_BROKEN, SCOPE_FULL, ACTION_REPAIR)
REPAIR_PARTIAL_LINE = final_line(RUN_BROKEN, VERDICT_BROKEN, SCOPE_PARTIAL, ACTION_REPAIR)
EMPTY_LINE = final_line(RUN_EMPTY, VERDICT_NONE, SCOPE_NONE, ACTION_ADJUST)
ERROR_FULL_LINE = final_line(RUN_ERROR, VERDICT_UNKNOWN, SCOPE_FULL, ACTION_INVESTIGATE)
INTERRUPTED_FULL_LINE = final_line(RUN_INTERRUPTED, VERDICT_UNKNOWN, SCOPE_FULL, ACTION_ABORT)


def _link_distribution_contents(root: Path, distribution_name: str) -> None:
    distribution = importlib.metadata.distribution(distribution_name)
    copied_entries: set[str] = set()

    for file in distribution.files or ():
        top_level_entry = file.parts[0]
        if top_level_entry in copied_entries or top_level_entry in {".", ".."}:
            continue

        copied_entries.add(top_level_entry)
        source = Path(distribution.locate_file(Path(top_level_entry)))
        target = root / Path(top_level_entry).name
        if target.exists():
            continue

        if source.is_dir():
            try:
                os.symlink(source, target, target_is_directory=True)
            except OSError:
                shutil.copytree(source, target)
            continue

        shutil.copy2(source, target)


def isolated_pytest_root(tmp_path: Path) -> Path:
    # Build a minimal import root so subprocess tests can avoid ambient site-packages.
    root = tmp_path / "isolated-site"
    root.mkdir()

    for distribution_name in ISOLATED_PYTEST_DISTRIBUTIONS:
        _link_distribution_contents(root, distribution_name)

    return root


def subprocess_env(
    *pythonpaths: Path,
    autoload_plugins: bool = False,
    inherit_pythonpath: bool = False,
) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTEST_PLUGINS", None)

    path_entries = [str(path) for path in pythonpaths]
    if inherit_pythonpath:
        existing = env.get("PYTHONPATH")
        if existing:
            path_entries.append(existing)

    if path_entries:
        env["PYTHONPATH"] = os.pathsep.join(path_entries)
    else:
        env.pop("PYTHONPATH", None)

    if autoload_plugins:
        env.pop("PYTEST_DISABLE_PLUGIN_AUTOLOAD", None)
    else:
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"

    return env
