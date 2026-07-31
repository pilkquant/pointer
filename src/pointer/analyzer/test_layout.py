"""Test layout detection and oracle-readiness assessment.

Detects test files, test directories, and test frameworks WITHOUT executing tests.
"""

from __future__ import annotations

import re
from pathlib import Path

from pointer.analyzer.filesystem import read_text_safely, safe_walk
from pointer.models import TestAnalysis, TestFileInfo

# Test file patterns
TEST_FILE_PATTERNS = [
    re.compile(r"^test_.*\.py$"),
    re.compile(r".*_test\.py$"),
    re.compile(r"^tests?\.py$"),
]

# Test directory names
TEST_DIR_NAMES = {"test", "tests", "testing", "_test", "_tests"}

# Framework detection patterns
FRAMEWORK_PATTERNS = {
    "pytest": re.compile(r"\bimport\s+pytest\b|\bfrom\s+pytest\b", re.MULTILINE),
    "unittest": re.compile(r"\bimport\s+unittest\b|\bfrom\s+unittest\b", re.MULTILINE),
    "hypothesis": re.compile(r"\bimport\s+hypothesis\b|\bfrom\s+hypothesis\b", re.MULTILINE),
    "nose": re.compile(r"\bimport\s+nose\b|\bfrom\s+nose\b", re.MULTILINE),
    "nose2": re.compile(r"\bimport\s+nose2\b|\bfrom\s+nose2\b", re.MULTILINE),
    "tox": re.compile(r"\bimport\s+tox\b|\bfrom\s+tox\b", re.MULTILINE),
    "nox": re.compile(r"\bimport\s+nox\b|\bfrom\s+nox\b", re.MULTILINE),
}

# Fixture/conftest patterns
FIXTURE_PATTERN = re.compile(r"@pytest\.fixture|@fixture", re.MULTILINE)
PARAMETRIZE_PATTERN = re.compile(r"@pytest\.mark\.parametrize|@parametrize", re.MULTILINE)


def detect(root: Path) -> TestAnalysis:
    """Detect test layout and assess oracle readiness."""
    analysis = TestAnalysis()
    all_files = safe_walk(root)

    test_dirs_set: set[str] = set()
    frameworks_set: set[str] = set()
    fixture_count = 0

    for fpath, rel in all_files:
        # Check for conftest.py
        if fpath.name == "conftest.py":
            analysis.has_conftest = True
            frameworks_set.add("pytest")
            test_dirs_set.add(str(fpath.parent.relative_to(root)))

        # Check for test files
        is_test = False
        for pattern in TEST_FILE_PATTERNS:
            if pattern.match(fpath.name):
                is_test = True
                break

        # Also check if file is in a test directory
        parent_parts = fpath.parts
        in_test_dir = any(part in TEST_DIR_NAMES for part in parent_parts)

        if is_test or (in_test_dir and fpath.suffix == ".py"):
            # Determine framework
            framework = "unknown"
            source = read_text_safely(fpath)
            if source:
                for fw_name, fw_pattern in FRAMEWORK_PATTERNS.items():
                    if fw_pattern.search(source):
                        frameworks_set.add(fw_name)
                        if framework == "unknown":
                            framework = fw_name

                # Check for fixtures
                if FIXTURE_PATTERN.search(source):
                    analysis.has_fixtures = True
                    fixture_count += 1
                if PARAMETRIZE_PATTERN.search(source):
                    analysis.has_fixtures = True

            analysis.test_files.append(TestFileInfo(path=rel, framework=framework))
            test_dirs_set.add(str(fpath.parent.relative_to(root)))

    analysis.test_dirs = sorted(test_dirs_set)
    analysis.frameworks_detected = sorted(frameworks_set)

    # Assess oracle readiness
    _assess_oracle_readiness(analysis, fixture_count)

    return analysis


def _assess_oracle_readiness(analysis: TestAnalysis, fixture_count: int = 0) -> None:
    """Assess how ready the test suite is for differential verification."""
    test_count = len(analysis.test_files)
    has_pytest = "pytest" in analysis.frameworks_detected
    has_hypothesis = "hypothesis" in analysis.frameworks_detected
    has_unittest = "unittest" in analysis.frameworks_detected

    reasons: list[str] = []

    if test_count == 0:
        analysis.oracle_readiness = "low"
        analysis.oracle_readiness_reason = (
            "No test files detected — differential verification would require building an oracle from scratch."
        )
        return

    if test_count >= 10 and has_pytest:
        analysis.oracle_readiness = "high"
        reasons.append(f"{test_count} test files detected")
        reasons.append("pytest framework available for golden-master capture")
    elif test_count >= 3 and (has_pytest or has_unittest):
        analysis.oracle_readiness = "medium"
        reasons.append(f"{test_count} test files detected")
        reasons.append("test framework available")
    else:
        analysis.oracle_readiness = "low"
        reasons.append(f"Only {test_count} test files detected")

    if has_hypothesis:
        reasons.append("hypothesis available for property-based differential testing")

    if analysis.has_fixtures:
        reasons.append(f"fixtures detected ({fixture_count} fixture definitions)")

    if analysis.has_conftest:
        reasons.append("conftest.py present (shared fixtures/config)")

    analysis.oracle_readiness_reason = "; ".join(reasons) + "."
