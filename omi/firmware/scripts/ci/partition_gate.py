#!/usr/bin/env python3
"""Refuses a build whose persistent partitions have moved.

The addresses of ``settings_storage`` and ``littlefs_storage`` are a
compatibility contract, not a layout preference. A firmware update writes only
the application slot; if these move, the new firmware looks for its settings
where nothing wrote them, and a device loses its clock, its microphone gain and
its dim ratio. There is no cable to this hardware and no way to put them back.

Upstream leaves both to the partition manager with the same constraint and no
ordering between them, so two placements are equally valid. ``pm_static.yml``
pins them — and this checks that the pinning actually took, because trusting a
file to have had an effect is not the same as seeing the effect.

Reads the generated ``partitions.yml``, which is what the build really produced.
"""

from __future__ import annotations

import sys

# What shipped hardware already has. Changing these needs a planned storage
# migration and a product decision, not an edit here.
EXPECTED = {
    "settings_storage": {"address": 0xF8000, "size": 0x2000},
    "littlefs_storage": {"address": 0xFA000, "size": 0x6000},
}


def parse_partitions(text: str) -> dict[str, dict[str, int]]:
    """Read the generated partition table.

    Deliberately a small parser rather than a YAML dependency: the file is a
    flat mapping of names to scalar fields, and a CI step that needs a package
    installed is a CI step that stops working on somebody else's machine.
    """
    found: dict[str, dict[str, int]] = {}
    current: str | None = None

    for line in text.splitlines():
        if line and not line[0].isspace() and line.rstrip().endswith(":"):
            current = line.rstrip()[:-1]
            found[current] = {}
            continue
        if current is None:
            continue
        stripped = line.strip()
        for field in ("address", "size", "end_address"):
            prefix = f"{field}:"
            if stripped.startswith(prefix):
                value = stripped[len(prefix) :].strip()
                try:
                    found[current][field] = int(value, 0)
                except ValueError:
                    # A non-numeric value — a span, a device reference. Not
                    # something this check is about.
                    pass
    return found


def check(partitions: dict[str, dict[str, int]]) -> tuple[bool, str]:
    """Whether the persistent partitions are where they must be."""
    problems: list[str] = []

    for name, expected in EXPECTED.items():
        actual = partitions.get(name)
        if actual is None:
            problems.append(f"{name} is missing from the partition table")
            continue
        for field, wanted in expected.items():
            got = actual.get(field)
            if got != wanted:
                problems.append(
                    f"{name}.{field} is "
                    + (f"{got:#x}" if got is not None else "absent")
                    + f", expected {wanted:#x}"
                )

    if problems:
        listed = "\n  ".join(problems)
        return False, (
            "The persistent partitions are not where shipped hardware has "
            f"them:\n  {listed}\n\n"
            "A firmware update writes only the application slot. Moving these "
            "leaves a device looking for settings at an address nothing wrote "
            "to — and there is no cable to this hardware to put them back. "
            "Check boards/omi/pm_static.yml, and do not change the expected "
            "values without a planned storage migration."
        )

    settled = ", ".join(
        f"{name} {values['address']:#x}/{values['size']:#x}"
        for name, values in EXPECTED.items()
    )
    return True, f"Persistent partitions are where they belong: {settled}."


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0] if argv else 'partition_gate.py'} <partitions.yml>")
        return 2

    with open(argv[1], encoding="utf-8") as handle:
        ok, message = check(parse_partitions(handle.read()))

    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
