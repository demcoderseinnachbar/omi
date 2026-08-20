#!/usr/bin/env python3
"""Unit tests for check_runner_cost_policy.py."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from check_runner_cost_policy import validate


def write_workflow(root: Path, name: str, runs_on: str) -> None:
    workflows = root / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / name).write_text(
        f"name: fixture\njobs:\n  test:\n    runs-on: {runs_on}\n    steps: []\n",
        encoding="utf-8",
    )


def write_checkout_job(
    root: Path,
    name: str,
    *,
    timeout: int | None,
    filtered: bool,
    depth: int = 0,
) -> None:
    """A job that checks out, with the two knobs this policy is about."""

    workflows = root / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    budget = f"    timeout-minutes: {timeout}\n" if timeout is not None else ""
    blobs = "          filter: blob:none\n" if filtered else ""
    (workflows / name).write_text(
        "name: fixture\n"
        "jobs:\n"
        "  scope:\n"
        "    runs-on: ubuntu-latest\n"
        f"{budget}"
        "    steps:\n"
        "      - uses: actions/checkout@v7\n"
        "        with:\n"
        f"          fetch-depth: {depth}\n"
        f"{blobs}",
        encoding="utf-8",
    )


class RunnerCostPolicyTests(unittest.TestCase):
    def test_accepts_standard_public_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_workflow(root, "standard.yml", "ubuntu-latest")
            self.assertEqual(validate(root), [])

    def test_rejects_paid_runner_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_workflow(root, "paid.yml", "ubuntu-latest-m")
            self.assertEqual(
                validate(root),
                [
                    ".github/workflows/paid.yml:4: paid runner label 'ubuntu-latest-m' "
                    "is forbidden; public-repository jobs must use a standard runner"
                ],
            )

    def test_checks_yaml_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_workflow(root, "paid.yaml", "ubuntu-latest-m")
            self.assertEqual(len(validate(root)), 1)


class CheckoutCostTests(unittest.TestCase):
    """A job must not give itself less time than its own checkout costs.

    This is the shape `backend-hermetic-e2e` had: two minutes for a clone that
    measured 164 s, so the job was cancelled on every run and the gate behind it
    reported red for pull requests it had never read.
    """

    def test_rejects_deep_unfiltered_checkout_under_a_short_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_checkout_job(root, "scope.yml", timeout=2, filtered=False)

            errors = validate(root)

            self.assertEqual(len(errors), 1)
            self.assertIn("filter: blob:none", errors[0])
            self.assertIn("FC-gate-timeout-below-cold-cost", errors[0])

    def test_accepts_the_same_checkout_once_it_is_filtered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_checkout_job(root, "scope.yml", timeout=2, filtered=True)
            self.assertEqual(validate(root), [])

    def test_accepts_a_deep_checkout_that_gave_itself_room(self) -> None:
        # The other honest way out of the class: pay for the clone in time.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_checkout_job(root, "build.yml", timeout=60, filtered=False)
            self.assertEqual(validate(root), [])

    def test_ignores_a_shallow_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_checkout_job(root, "quick.yml", timeout=2, filtered=False, depth=1)
            self.assertEqual(validate(root), [])

    def test_ignores_a_job_without_a_timeout(self) -> None:
        # No budget means no budget to fall below. The default is six hours.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_checkout_job(root, "open.yml", timeout=None, filtered=False)
            self.assertEqual(validate(root), [])

    def test_reads_fetch_depth_only_from_the_step_it_belongs_to(self) -> None:
        # A later step carrying `fetch-depth: 0` must not be attributed to an
        # earlier checkout, and a non-checkout step must not be read as one.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflows = root / ".github" / "workflows"
            workflows.mkdir(parents=True, exist_ok=True)
            (workflows / "mixed.yml").write_text(
                "name: fixture\n"
                "jobs:\n"
                "  scope:\n"
                "    runs-on: ubuntu-latest\n"
                "    timeout-minutes: 2\n"
                "    steps:\n"
                "      - uses: actions/checkout@v7\n"
                "        with:\n"
                "          fetch-depth: 0\n"
                "          filter: blob:none\n"
                "      - uses: some/other-action@v1\n"
                "        with:\n"
                "          fetch-depth: 0\n",
                encoding="utf-8",
            )

            self.assertEqual(validate(root), [])

    def test_finds_only_the_underfunded_job_in_a_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflows = root / ".github" / "workflows"
            workflows.mkdir(parents=True, exist_ok=True)
            (workflows / "two.yml").write_text(
                "name: fixture\n"
                "jobs:\n"
                "  generous:\n"
                "    runs-on: ubuntu-latest\n"
                "    timeout-minutes: 30\n"
                "    steps:\n"
                "      - uses: actions/checkout@v7\n"
                "        with:\n"
                "          fetch-depth: 0\n"
                "  tight:\n"
                "    runs-on: ubuntu-latest\n"
                "    timeout-minutes: 2\n"
                "    steps:\n"
                "      - uses: actions/checkout@v7\n"
                "        with:\n"
                "          fetch-depth: 0\n",
                encoding="utf-8",
            )

            errors = validate(root)

            self.assertEqual(len(errors), 1)
            self.assertIn("'tight'", errors[0])
            self.assertNotIn("generous", errors[0])


if __name__ == "__main__":
    unittest.main()
