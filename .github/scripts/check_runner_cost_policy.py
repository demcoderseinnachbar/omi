#!/usr/bin/env python3
"""What a workflow may cost this repository.

Two rules, both about paying for something twice over:

* a public repository must not ask for a paid runner label, and
* a job must not give itself less time than a full checkout of this
  repository takes.

The second one is `FC-gate-timeout-below-cold-cost`: a gate's fixed time
budget has to exceed the cost of the healthy work it bounds. `fetch-depth: 0`
without a filter clones 1.29 GiB in 359k objects and measured 164 s; a job that
allows itself two minutes cannot finish that and is cancelled on every run.
Downstream gates that fail closed then report red for pull requests they never
looked at, which is exactly what happened to `backend-hermetic-e2e`.

`filter: blob:none` brings the same clone to 74 s and keeps every commit and
tree — enough for `merge-base` and `diff --name-only`, which is what such jobs
ask git. So the rule is not "raise the timeout": it is "do not pay for history
you do not read".
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

PAID_RUNNER_LABELS = ("ubuntu-latest-m",)

# Above this, a job has room for an unfiltered clone even cold. At or below it,
# the measured 164 s does not fit and the job would be cancelled rather than
# fail, which reads as an infrastructure fault rather than a budget mistake.
SHORT_TIMEOUT_MINUTES = 5


# Read by indentation rather than with a YAML parser, deliberately. This script
# is invoked straight as `python3 check_runner_cost_policy.py` with nothing
# prepared for it, so it may use the standard library and nothing else — the
# workflows that need PyYAML install it themselves first. Workflow files are
# uniform enough for this: a job is a key one level under `jobs:`, and a step's
# inputs sit in a `with:` mapping under its `uses:`.
_JOB_KEY = re.compile(r"^(?P<indent> +)(?P<name>[A-Za-z_][\w.-]*):\s*(?:#.*)?$")
# The `- ` is optional because a step's first key carries the list marker:
# `      - uses: actions/checkout@v7`.
_SETTING = re.compile(r"^\s*(?:-\s+)?(?P<key>[\w.-]+):\s*(?P<value>.*?)\s*(?:#.*)?$")


class _Job:
    """What one job says about its time budget and its checkouts."""

    def __init__(self, name: str, indent: int) -> None:
        self.name = name
        self.indent = indent
        self.budget: int | None = None
        self.unfiltered_deep_checkout = False

    def underfunded(self) -> bool:
        return (
            self.budget is not None
            and self.budget <= SHORT_TIMEOUT_MINUTES
            and self.unfiltered_deep_checkout
        )


def _cost_findings(relative: Path, text: str) -> list[str]:
    """Jobs whose time budget cannot cover the checkout they ask for."""

    findings: list[str] = []
    jobs_indent: int | None = None
    job: _Job | None = None

    # Set while reading a checkout step, so `fetch-depth` and `filter` are only
    # ever read from the step they belong to.
    in_checkout = False
    depth_zero = False
    filtered = False

    def end_step() -> None:
        nonlocal in_checkout, depth_zero, filtered
        if in_checkout and depth_zero and not filtered and job is not None:
            job.unfiltered_deep_checkout = True
        in_checkout = False
        depth_zero = False
        filtered = False

    def end_job() -> None:
        end_step()
        if job is not None and job.underfunded():
            findings.append(
                f"{relative}: job {job.name!r} allows itself {job.budget} minutes and checks "
                "out with `fetch-depth: 0` and no `filter`. A full clone of this repository "
                "measured 164 s, so the job is cancelled rather than run. Add "
                "`filter: blob:none` — it keeps every commit and tree and takes 74 s — or "
                "give the job a budget that fits the clone it asks for "
                "(FC-gate-timeout-below-cold-cost)."
            )

    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())

        if raw.rstrip() == "jobs:":
            end_job()
            job = None
            jobs_indent = indent
            continue
        if jobs_indent is None:
            continue

        # Back out to the top level: the jobs block is over.
        if indent <= jobs_indent:
            end_job()
            job = None
            jobs_indent = None
            continue

        named = _JOB_KEY.match(raw)
        if named and (job is None or len(named.group("indent")) == job.indent):
            end_job()
            job = _Job(named.group("name"), len(named.group("indent")))
            continue
        if job is None:
            continue

        setting = _SETTING.match(raw)
        if setting is None:
            continue
        key, value = setting.group("key"), setting.group("value")

        if key == "uses":
            end_step()
            in_checkout = value.startswith("actions/checkout@")
        elif key == "timeout-minutes" and indent == job.indent + 2:
            try:
                job.budget = int(value)
            except ValueError:
                job.budget = None
        elif in_checkout and key == "fetch-depth":
            depth_zero = value == "0"
        elif in_checkout and key == "filter":
            filtered = bool(value)

    end_job()
    return findings


def validate(root: Path) -> list[str]:
    workflows = root / ".github" / "workflows"
    errors: list[str] = []
    for path in sorted((*workflows.glob("*.yml"), *workflows.glob("*.yaml"))):
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(root)

        for line_number, line in enumerate(text.splitlines(), start=1):
            for label in PAID_RUNNER_LABELS:
                if label in line:
                    errors.append(
                        f"{relative}:{line_number}: paid runner label {label!r} "
                        "is forbidden; public-repository jobs must use a standard runner"
                    )

        errors.extend(_cost_findings(relative, text))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    errors = validate(args.root.resolve())
    if errors:
        print("\n".join(errors))
        return 1
    print("GitHub runner cost policy check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
