#!/usr/bin/env python3
"""Refuses a firmware change that forgets to raise the version.

The bootloader on shipped Shard devices is built with
``CONFIG_MCUBOOT_DOWNGRADE_PREVENTION=y`` and **cannot be replaced over the
air**: MCUboot sits at the start of flash with no image index of its own. There
is no wired access to this hardware either. So an image whose version is not
higher than the one already on a device can never be installed there — not
later, not with a fix, not at all.

That makes a forgotten version bump unrecoverable rather than untidy, which is
why a rule in a document is not enough and this exists.

**It only ever refuses.** It writes no file, creates no commit and touches no
working copy. The version stays a decision somebody makes in the commit that
changes the firmware; this only notices when nobody made it.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import PurePosixPath

# Everything whose contents end up in the image, or decide how it is built.
#
# Derived from what the build actually reads (`scripts/ci/build-cv1.sh`):
# `west build` is pointed at `omi/firmware/omi` with `BOARD_ROOT` at
# `omi/firmware`, sysbuild pulls in the per-image configs, and `omi.conf` is
# copied over `prj.conf` before the build starts.
FIRMWARE_PATHS = (
    "omi/firmware/omi/src/",
    "omi/firmware/omi/sysbuild/",
    "omi/firmware/omi/omi.conf",
    "omi/firmware/omi/prj.conf",
    "omi/firmware/omi/sysbuild.conf",
    "omi/firmware/omi/CMakeLists.txt",
    "omi/firmware/omi/Kconfig",
    "omi/firmware/omi/Kconfig.sysbuild",
    "omi/firmware/omi/CMakePresets.json",
    "omi/firmware/boards/",
    "omi/firmware/bootloader/mcuboot/",
    # The build script itself: change how the image is produced and the image
    # changes, even if no source did.
    "omi/firmware/scripts/ci/build-cv1.sh",
)

# Paths that live under the ones above and still change nothing in the image.
FIRMWARE_EXCEPTIONS = (
    # These gates and their tests. They decide whether a change is allowed,
    # never what the firmware is.
    "omi/firmware/scripts/ci/version_gate.py",
    "omi/firmware/scripts/ci/test_version_gate.py",
    "omi/firmware/scripts/ci/partition_gate.py",
    "omi/firmware/scripts/ci/test_partition_gate.py",
)

VERSION_FILE = "omi/firmware/omi/VERSION"

# `shard-cv1-v<version>` / `Shard CV1 v<version>`, from SHARD_RELEASES.md §2.
# Deliberately unlike the Omi scheme: `FIRMWARE_TAG_PATTERN` in the Omi backend
# does not match it, so a Shard build can never be served to an Omi user by the
# endpoint that serves theirs.
#
# It lives here rather than beside the release gate because both gates need the
# same answer to "what has been published", and two copies of that would be two
# things that can disagree.
TAG_PREFIX = "shard-cv1-v"

_PUBLISHED_TAG = re.compile(rf"^{re.escape(TAG_PREFIX)}(\d+)\.(\d+)\.(\d+)$")


def newest_published_tag(tags: list[str]) -> str | None:
    """The tag naming the highest version anybody has published, or None.

    Ordered by the numbers the tag carries rather than by the string, so that
    ``0.0.10`` comes after ``0.0.9``. A tag that is not one of ours — an Omi
    release, a personal marker, anything — is not a Shard release and is
    ignored rather than guessed at.
    """
    best: tuple[tuple[int, int, int], str] | None = None

    for tag in tags:
        found = _PUBLISHED_TAG.match(tag.strip())
        if not found:
            continue
        version = (int(found[1]), int(found[2]), int(found[3]))
        if best is None or version > best[0]:
            best = (version, tag.strip())

    return best[1] if best else None


def is_firmware_change(path: str) -> bool:
    """Whether changing *path* can change the bytes on a device.

    Documentation never can — a ``.md`` under the firmware tree is a file about
    the firmware, not part of it. Neither can the VERSION file itself: raising
    it is the thing this gate asks for, so requiring it to justify its own
    change would be circular.
    """
    path = PurePosixPath(path).as_posix()

    if path in FIRMWARE_EXCEPTIONS:
        return False
    if path == VERSION_FILE:
        return False
    if path.lower().endswith(".md"):
        return False

    return any(
        path == entry if not entry.endswith("/") else path.startswith(entry)
        for entry in FIRMWARE_PATHS
    )


def parse_version(text: str) -> tuple[int, int, int, int]:
    """Read a Zephyr ``VERSION`` file into something that can be compared.

    Returns major, minor, patchlevel and tweak. A field that is absent is zero,
    which is what Zephyr's own ``version.cmake`` assumes.

    ``EXTRAVERSION`` is deliberately ignored: it does not reach the MCUboot
    header, so it cannot affect whether a device accepts an image, and ordering
    by something the bootloader never sees would be ordering by fiction.
    """

    def field(name: str) -> int:
        found = re.search(rf"^{name}\s*=\s*(\d+)\s*$", text, re.MULTILINE)
        return int(found.group(1)) if found else 0

    return (
        field("VERSION_MAJOR"),
        field("VERSION_MINOR"),
        field("PATCHLEVEL"),
        field("VERSION_TWEAK"),
    )


def format_version(version: tuple[int, int, int, int]) -> str:
    return f"{version[0]}.{version[1]}.{version[2]}+{version[3]}"


def check(
    changed_paths: list[str],
    base_version_text: str,
    head_version_text: str,
    base_source: str = "the target branch",
) -> tuple[bool, str]:
    """Decide whether this change may go in.

    Pure, so the rule can be tested without a repository. *base_source* names
    where the baseline came from, because with the bootstrap below it is not
    always the target branch and a message that said so would be wrong.
    """
    touched = sorted(path for path in changed_paths if is_firmware_change(path))
    if not touched:
        return True, "No firmware-effective file changed; no version bump needed."

    base = parse_version(base_version_text)
    head = parse_version(head_version_text)

    if head > base:
        return True, (
            f"Firmware changed and VERSION rose "
            f"{format_version(base)} -> {format_version(head)} "
            f"(baseline: {base_source})."
        )

    listed = "\n  ".join(touched)
    unchanged = base == head
    return False, (
        f"{VERSION_FILE} is {format_version(head)}, which is "
        + ("unchanged from" if unchanged else "not higher than")
        + f" {base_source}'s {format_version(base)}.\n\n"
        f"These changes reach the firmware image:\n  {listed}\n\n"
        "Raise VERSION in this change. A device already running that version "
        "can never be given an image that is not higher: the bootloader "
        "refuses it, it cannot be replaced over the air, and there is no cable "
        "to this hardware."
    )


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout


def _version_at(ref: str) -> str:
    """The VERSION file as of *ref*, or an empty file when it did not exist."""
    try:
        return _git("show", f"{ref}:{VERSION_FILE}")
    except subprocess.CalledProcessError:
        return ""


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0] if argv else 'version_gate.py'} <target-ref>")
        return 2

    target = argv[1]

    # Against the target branch as it stands, **not** the merge base. Two
    # branches may pick the same next version; once the first is merged the
    # second is compared with the merged result and is asked to pick again.
    # Comparing with the merge base would let both through and put two
    # different images into the world under one version.
    changed = _git("diff", "--name-only", f"{target}...HEAD").split()
    if not changed:
        changed = _git("diff", "--name-only", target, "HEAD").split()

    base_text = _version_at(target)
    base_source = f"the target branch ({target})"

    # The bootstrap. Until the first Shard change reaches `main`, that branch
    # carries no VERSION file at all — and an absent file parses as 0.0.0, so
    # the released 0.0.3 would look like a rise and a firmware change under the
    # published number would pass. The published tags are what says otherwise,
    # and they are already in the checkout.
    #
    # Only when the base has nothing to say. The moment the branch itself
    # carries a VERSION, that is the baseline again — this never overrides a
    # version somebody wrote down.
    if not base_text.strip():
        published = newest_published_tag(_git("tag", "--list", f"{TAG_PREFIX}*").split())
        if published:
            base_text = _version_at(published)
            base_source = f"the published tag {published}"

    ok, message = check(changed, base_text, _version_at("HEAD"), base_source)
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
