#!/usr/bin/env python3
"""Decides whether a push to ``main`` produced a Shard release candidate.

``version_gate.py`` refuses a change that forgets to raise the version. This
answers the other question, once the change is on ``main``: has the version
actually gone up, and is the release it implies still unclaimed?

**It only ever refuses or declines.** It writes no file, creates no tag, picks
no number and publishes nothing. Three answers, and the difference between the
last two matters:

``release``
    ``X.Y.Z`` rose and no tag claims it. A candidate may be built.
``no release``
    Nothing to do. The ordinary outcome of almost every push.
``refuse``
    Something is wrong in a way that must not be built past — the version went
    backwards, is malformed, or names a release that already exists.

Uncertainty resolves to *no release*, never to *release*. A missed candidate
costs one manual run; a wrong one spends a version number that can never be
reused, because the bootloader on shipped hardware refuses anything that is not
higher and cannot be replaced over the air.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

from version_gate import VERSION_FILE, is_firmware_change, parse_version

# `shard-cv1-v<version>` / `Shard CV1 v<version>`, from SHARD_RELEASES.md §2.
# Deliberately unlike the Omi scheme: `FIRMWARE_TAG_PATTERN` in the Omi
# backend does not match it, so a Shard build can never be served to an Omi
# user by the endpoint that serves theirs.
TAG_PREFIX = "shard-cv1-v"

# The three fields the tag is made of. VERSION_TWEAK is not among them, on
# purpose — see `release_version` below.
REQUIRED_FIELDS = ("VERSION_MAJOR", "VERSION_MINOR", "PATCHLEVEL")

RELEASE = "release"
NO_RELEASE = "no release"
REFUSE = "refuse"


def release_version(version: tuple[int, int, int, int]) -> str:
    """The ``X.Y.Z`` a release is named after.

    ``VERSION_TWEAK`` is left out because the tag has no room for it: the image
    and the DFU manifest read ``0.0.3+0`` while the product version — the tag,
    the release, the asset, what a device reports over BLE — is ``0.0.3``. Two
    builds differing only in the tweak would want one tag, and the second would
    either overwrite a published release or reuse a published number for
    different bytes. Both are forbidden by SHARD_RELEASES.md §2, so a tweak on
    its own is not a release.
    """
    return f"{version[0]}.{version[1]}.{version[2]}"


def missing_fields(text: str) -> list[str]:
    """Fields a VERSION file has to state rather than leave to a default.

    ``parse_version`` reads an absent field as zero, which is right for
    comparing but wrong for naming: a VERSION file that has lost its
    ``PATCHLEVEL`` line would silently release ``0.0.0``.
    """
    return [
        name
        for name in REQUIRED_FIELDS
        if not re.search(rf"^{name}\s*=\s*(\d+)\s*$", text, re.MULTILINE)
    ]


def check(
    before_version_text: str,
    head_version_text: str,
    existing_tags: list[str],
) -> tuple[str, str, str]:
    """Decide what this push means. Pure, so the rule can be tested.

    Returns the decision, a message for a person, and the version — empty
    unless the decision is ``release``.
    """
    if not head_version_text.strip():
        return REFUSE, f"{VERSION_FILE} is missing or empty at HEAD.", ""

    absent = missing_fields(head_version_text)
    if absent:
        return (
            REFUSE,
            f"{VERSION_FILE} does not state {', '.join(absent)}. A release is "
            "named after a version somebody wrote down, never after a default.",
            "",
        )

    head = parse_version(head_version_text)
    version = release_version(head)

    # No predecessor to compare with: a fresh branch, a shallow clone, a
    # rewritten history. Nothing is wrong, but nothing is established either.
    if not before_version_text.strip():
        return (
            NO_RELEASE,
            "No previous VERSION to compare with, so no rise can be "
            f"established. {VERSION_FILE} reads {version}.",
            version,
        )

    before = parse_version(before_version_text)
    previous = release_version(before)

    if head[:3] < before[:3]:
        return (
            REFUSE,
            f"{VERSION_FILE} went backwards on this branch: {previous} -> "
            f"{version}. A device already running {previous} can never be given "
            f"{version} — the bootloader has downgrade prevention compiled in "
            "and cannot be replaced over the air, and there is no cable to this "
            "hardware. Raise the version instead of lowering it.",
            "",
        )

    if head[:3] == before[:3]:
        tweak = (
            " The tweak rose, and a tweak on its own is not a release: the tag "
            "carries X.Y.Z alone."
            if head[3] != before[3]
            else ""
        )
        return (
            NO_RELEASE,
            f"{VERSION_FILE} is unchanged at {version}.{tweak}",
            version,
        )

    tag = f"{TAG_PREFIX}{version}"
    if tag in existing_tags:
        return (
            REFUSE,
            f"{tag} already exists. A version that has been tagged is never "
            "reused for different firmware bytes — the release under that "
            "number has already been published for other bytes, and replacing "
            "it would leave its recorded hashes identifying nothing. This costs "
            "a new version.",
            "",
        )

    return (
        RELEASE,
        f"{VERSION_FILE} rose {previous} -> {version} and {tag} is unclaimed. "
        "A candidate may be built.",
        version,
    )


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout


def _version_at(ref: str) -> str:
    """The VERSION file as of *ref*, or empty when there is no such file."""
    try:
        return _git("show", f"{ref}:{VERSION_FILE}")
    except subprocess.CalledProcessError:
        return ""


def _emit(**values: str) -> None:
    """Hand the decision to whatever is running this.

    Under GitHub Actions that is ``$GITHUB_OUTPUT``; anywhere else, stdout. The
    format is the same either way, so a person running this by hand sees
    exactly what the workflow will act on.
    """
    lines = [f"{name}={value}" for name, value in values.items()]
    destination = os.environ.get("GITHUB_OUTPUT")
    if destination:
        with open(destination, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    for line in lines:
        print(line)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0] if argv else 'release_gate.py'} <before-ref>")
        return 2

    before = argv[1]

    # A push that created the branch reports an all-zero "before", and a
    # rewritten history reports a commit that is no longer there. The previous
    # commit is the honest fallback; when even that is absent there is nothing
    # to compare with and the answer is no release, never a release.
    try:
        _git("rev-parse", "--verify", f"{before}^{{commit}}")
    except subprocess.CalledProcessError:
        try:
            before = _git("rev-parse", "--verify", "HEAD~1^{commit}").strip()
        except subprocess.CalledProcessError:
            before = ""

    tags = _git("tag", "--list", f"{TAG_PREFIX}*").split()

    decision, message, version = check(
        _version_at(before) if before else "",
        _version_at("HEAD"),
        tags,
    )

    print(message)

    if decision == REFUSE:
        return 1

    # Whether this push changed the firmware itself, as opposed to a document
    # about it. Decided by `version_gate.is_firmware_change`, so "reaches the
    # image" means one thing in this repository and is written down once.
    #
    # It matters when the version did *not* rise: a firmware change under a
    # number that already has a draft leaves that draft describing bytes the
    # branch no longer has. The workflow uses this to mark such a draft rather
    # than let it wait quietly to be published.
    changed = _git("diff", "--name-only", before, "HEAD").split() if before else []
    firmware_changed = any(is_firmware_change(path) for path in changed)

    _emit(
        release="true" if decision == RELEASE else "false",
        version=version,
        tag=f"{TAG_PREFIX}{version}" if version else "",
        firmware_changed="true" if firmware_changed else "false",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
