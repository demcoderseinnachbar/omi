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
) -> tuple[bool, str]:
    """Decide whether this change may go in.

    Pure, so the rule can be tested without a repository.
    """
    touched = sorted(path for path in changed_paths if is_firmware_change(path))
    if not touched:
        return True, "No firmware-effective file changed; no version bump needed."

    base = parse_version(base_version_text)
    head = parse_version(head_version_text)

    if head > base:
        return True, (
            f"Firmware changed and VERSION rose "
            f"{format_version(base)} -> {format_version(head)}."
        )

    listed = "\n  ".join(touched)
    unchanged = base == head
    return False, (
        f"{VERSION_FILE} is {format_version(head)}, which is "
        + ("unchanged from" if unchanged else "not higher than")
        + f" the target branch's {format_version(base)}.\n\n"
        f"These changes reach the firmware image:\n  {listed}\n\n"
        "Raise VERSION in this change. A device already running the target "
        "branch's version can never be given an image that is not higher: the "
        "bootloader refuses it, it cannot be replaced over the air, and there "
        "is no cable to this hardware."
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

    ok, message = check(changed, _version_at(target), _version_at("HEAD"))
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
