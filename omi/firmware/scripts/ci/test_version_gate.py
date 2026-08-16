#!/usr/bin/env python3
"""What the version gate lets through, and what it stops.

Run with ``python3 -m unittest`` from ``omi/firmware/scripts/ci``. No
dependencies, no repository, no network — the rule is pure so that it can be
checked here rather than only in anger.
"""

import unittest

from version_gate import check, format_version, is_firmware_change, parse_version

V_0_0_2 = "VERSION_MAJOR = 0\nVERSION_MINOR = 0\nPATCHLEVEL = 2\nVERSION_TWEAK = 0\n"
V_0_0_3 = "VERSION_MAJOR = 0\nVERSION_MINOR = 0\nPATCHLEVEL = 3\nVERSION_TWEAK = 0\n"

SOURCE = "omi/firmware/omi/src/lib/core/transport.c"
CONFIG = "omi/firmware/omi/omi.conf"
DOCS = "omi/firmware/SHARD_RELEASES.md"


class WhatCountsAsAFirmwareChange(unittest.TestCase):
    def test_application_sources_do(self):
        self.assertTrue(is_firmware_change(SOURCE))
        self.assertTrue(is_firmware_change("omi/firmware/omi/src/mic.c"))

    def test_the_production_config_does(self):
        self.assertTrue(is_firmware_change(CONFIG))
        self.assertTrue(is_firmware_change("omi/firmware/omi/sysbuild.conf"))
        self.assertTrue(is_firmware_change("omi/firmware/omi/sysbuild/mcuboot.conf"))

    def test_the_board_and_the_bootloader_do(self):
        self.assertTrue(
            is_firmware_change("omi/firmware/boards/omi/omi_nrf5340_cpuapp.dts")
        )
        self.assertTrue(
            is_firmware_change("omi/firmware/bootloader/mcuboot/mcuboot.conf")
        )

    def test_the_partition_layout_does(self):
        # Where the persistent partitions sit is part of what a device gets,
        # and moving them is the one change that quietly costs somebody their
        # stored settings.
        self.assertTrue(
            is_firmware_change("omi/firmware/boards/omi/pm_static.yml")
        )

    def test_the_build_script_does(self):
        # Change how the image is produced and the image changes, even if no
        # source did.
        self.assertTrue(
            is_firmware_change("omi/firmware/scripts/ci/build-cv1.sh")
        )

    def test_documentation_never_does(self):
        self.assertFalse(is_firmware_change(DOCS))
        self.assertFalse(is_firmware_change("omi/firmware/AGENTS.md"))
        self.assertFalse(is_firmware_change("omi/firmware/omi/README.md"))

    def test_this_gate_does_not(self):
        # It decides whether a change is allowed, never what the firmware is.
        self.assertFalse(
            is_firmware_change("omi/firmware/scripts/ci/version_gate.py")
        )
        self.assertFalse(
            is_firmware_change("omi/firmware/scripts/ci/test_version_gate.py")
        )

    def test_the_version_file_does_not_justify_itself(self):
        # Raising it is what the gate asks for; requiring it to justify its own
        # change would be circular.
        self.assertFalse(is_firmware_change("omi/firmware/omi/VERSION"))

    def test_the_rest_of_the_repository_does_not(self):
        self.assertFalse(is_firmware_change("app/lib/main.dart"))
        self.assertFalse(is_firmware_change("backend/routers/firmware.py"))
        self.assertFalse(is_firmware_change("omi/firmware/devkit/something.c"))


class ReadingTheVersionFile(unittest.TestCase):
    def test_all_four_fields(self):
        self.assertEqual(parse_version(V_0_0_2), (0, 0, 2, 0))

    def test_a_missing_field_is_zero(self):
        self.assertEqual(parse_version("VERSION_MAJOR = 1\n"), (1, 0, 0, 0))

    def test_extraversion_is_ignored(self):
        # It never reaches the MCUboot header, so it cannot decide whether a
        # device accepts an image.
        with_extra = V_0_0_2 + "EXTRAVERSION = rc1\n"
        self.assertEqual(parse_version(with_extra), parse_version(V_0_0_2))

    def test_whitespace_and_order_do_not_matter(self):
        jumbled = "PATCHLEVEL=2\nVERSION_TWEAK = 0\nVERSION_MINOR = 0\nVERSION_MAJOR = 0\n"
        self.assertEqual(parse_version(jumbled), (0, 0, 2, 0))

    def test_ordering_is_numeric_and_not_by_string(self):
        # `0.0.10` sorts before `0.0.9` as text, and the whole point is that it
        # must not here.
        nine = "VERSION_MAJOR = 0\nVERSION_MINOR = 0\nPATCHLEVEL = 9\n"
        ten = "VERSION_MAJOR = 0\nVERSION_MINOR = 0\nPATCHLEVEL = 10\n"
        self.assertGreater(parse_version(ten), parse_version(nine))

    def test_every_field_orders(self):
        base = parse_version(V_0_0_2)
        for text, why in [
            ("VERSION_MAJOR = 1\nVERSION_MINOR = 0\nPATCHLEVEL = 0\n", "major"),
            ("VERSION_MAJOR = 0\nVERSION_MINOR = 1\nPATCHLEVEL = 0\n", "minor"),
            ("VERSION_MAJOR = 0\nVERSION_MINOR = 0\nPATCHLEVEL = 3\n", "patch"),
            (V_0_0_2 .replace("VERSION_TWEAK = 0", "VERSION_TWEAK = 1"), "tweak"),
        ]:
            self.assertGreater(parse_version(text), base, msg=why)

    def test_it_prints_the_way_mcuboot_writes_it(self):
        self.assertEqual(format_version((0, 0, 2, 0)), "0.0.2+0")


class WhatTheGateDecides(unittest.TestCase):
    def test_firmware_changed_and_version_unchanged_is_refused(self):
        ok, message = check([SOURCE], V_0_0_2, V_0_0_2)

        self.assertFalse(ok)
        self.assertIn("unchanged from", message)
        self.assertIn(SOURCE, message, "it must say which change needs the bump")

    def test_firmware_changed_and_version_raised_is_allowed(self):
        ok, message = check([SOURCE], V_0_0_2, V_0_0_3)

        self.assertTrue(ok)
        self.assertIn("0.0.2+0 -> 0.0.3+0", message)

    def test_a_lower_version_is_refused(self):
        ok, message = check([SOURCE], V_0_0_3, V_0_0_2)

        self.assertFalse(ok)
        self.assertIn("not higher than", message)

    def test_documentation_alone_needs_no_bump(self):
        ok, message = check([DOCS], V_0_0_2, V_0_0_2)

        self.assertTrue(ok)
        self.assertIn("no version bump needed", message)

    def test_documentation_beside_firmware_still_needs_one(self):
        ok, _ = check([DOCS, SOURCE], V_0_0_2, V_0_0_2)

        self.assertFalse(ok)

    def test_changing_only_the_version_is_allowed(self):
        # Preparing a release without touching sources is a legitimate change.
        ok, _ = check(["omi/firmware/omi/VERSION"], V_0_0_2, V_0_0_3)

        self.assertTrue(ok)

    def test_two_branches_that_pick_the_same_number(self):
        # The case the whole comparison target is chosen for. Both branches
        # raise 0.0.2 to 0.0.3 independently. The first merges. The second is
        # then compared with the *merged* target — 0.0.3 against 0.0.3 — and is
        # asked to pick again, instead of two different images going out under
        # one version.
        first_merges, _ = check([SOURCE], V_0_0_2, V_0_0_3)
        self.assertTrue(first_merges)

        second_after_that, message = check([SOURCE], V_0_0_3, V_0_0_3)
        self.assertFalse(second_after_that)
        self.assertIn("unchanged from", message)

    def test_a_first_version_file_is_a_rise(self):
        # Nothing to compare with reads as (0, 0, 0, 0), so the first VERSION
        # any firmware change introduces counts as raising it.
        ok, _ = check([SOURCE], "", V_0_0_2)

        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
