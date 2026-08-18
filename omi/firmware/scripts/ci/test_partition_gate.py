#!/usr/bin/env python3
"""What the partition gate accepts, and what it stops.

Run with ``python3 -m unittest`` from ``omi/firmware/scripts/ci``.
"""

import unittest

from partition_gate import EXPECTED, check, parse_partitions

# The layout shipped hardware has, in the shape the build writes it.
SHIPPED = """\
app:
  address: 0x10200
  end_address: 0xf8000
  region: flash_primary
  size: 0xe7e00
littlefs_storage:
  address: 0xfa000
  end_address: 0x100000
  region: flash_primary
  size: 0x6000
mcuboot:
  address: 0x0
  end_address: 0x10000
  region: flash_primary
  size: 0x10000
mcuboot_primary:
  address: 0x10000
  orig_span: &id001
  - mcuboot_pad
  - app
  region: flash_primary
  size: 0xf0000
  span: *id001
settings_storage:
  address: 0xf8000
  end_address: 0xfa000
  region: flash_primary
  size: 0x2000
"""

# What an unpinned build produced instead: the two swapped, and eight kilobytes
# left over. Internally consistent, and wrong for a device already in the field.
DRIFTED = SHIPPED.replace("0xfa000\n  end_address: 0x100000", "0xf6000\n  end_address: 0xfc000").replace(
    "address: 0xf8000\n  end_address: 0xfa000", "address: 0xfc000\n  end_address: 0xfe000"
)


class ReadingTheTable(unittest.TestCase):
    def test_addresses_and_sizes_are_numbers(self):
        parsed = parse_partitions(SHIPPED)

        self.assertEqual(parsed["settings_storage"]["address"], 0xF8000)
        self.assertEqual(parsed["settings_storage"]["size"], 0x2000)
        self.assertEqual(parsed["littlefs_storage"]["address"], 0xFA000)

    def test_a_span_does_not_break_it(self):
        # `span` and `orig_span` are lists and anchors, not scalars. They must
        # be skipped rather than crash the parser.
        parsed = parse_partitions(SHIPPED)

        self.assertIn("mcuboot_primary", parsed)
        self.assertEqual(parsed["mcuboot_primary"]["size"], 0xF0000)

    def test_every_partition_is_seen(self):
        parsed = parse_partitions(SHIPPED)

        self.assertEqual(
            sorted(parsed),
            ["app", "littlefs_storage", "mcuboot", "mcuboot_primary", "settings_storage"],
        )


class WhatTheGateDecides(unittest.TestCase):
    def test_the_shipped_layout_passes(self):
        ok, message = check(parse_partitions(SHIPPED))

        self.assertTrue(ok, message)

    def test_the_drifted_layout_is_refused(self):
        # The exact situation this exists for.
        ok, message = check(parse_partitions(DRIFTED))

        self.assertFalse(ok)
        self.assertIn("settings_storage.address", message)
        self.assertIn("0xf8000", message)

    def test_a_missing_partition_is_refused(self):
        without = parse_partitions(SHIPPED)
        del without["settings_storage"]

        ok, message = check(without)

        self.assertFalse(ok)
        self.assertIn("missing", message)

    def test_a_changed_size_is_refused(self):
        # Same address, more room. Still a different contract.
        wrong = parse_partitions(SHIPPED)
        wrong["settings_storage"]["size"] = 0x4000

        ok, message = check(wrong)

        self.assertFalse(ok)
        self.assertIn("settings_storage.size", message)

    def test_it_says_which_field_is_wrong_and_what_was_wanted(self):
        wrong = parse_partitions(SHIPPED)
        wrong["littlefs_storage"]["address"] = 0xF6000

        _, message = check(wrong)

        self.assertIn("0xf6000", message)
        self.assertIn("0xfa000", message)

    def test_the_expectation_is_the_shipped_layout(self):
        # Written out so that changing it is a deliberate act somebody has to
        # explain, not a quiet edit.
        self.assertEqual(EXPECTED["settings_storage"], {"address": 0xF8000, "size": 0x2000})
        self.assertEqual(EXPECTED["littlefs_storage"], {"address": 0xFA000, "size": 0x6000})


if __name__ == "__main__":
    unittest.main()
