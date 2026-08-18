#!/usr/bin/env python3
"""What the version gate lets through, and what it stops.

Run with ``python3 -m unittest`` from ``omi/firmware/scripts/ci``. No
dependencies, no repository, no network — the rule is pure so that it can be
checked here rather than only in anger.
"""

import contextlib
import io
import os
import shutil
import subprocess
import tempfile
import unittest

from version_gate import (
    TAG_PREFIX,
    VERSION_FILE,
    check,
    format_version,
    is_firmware_change,
    main,
    newest_published_tag,
    parse_version,
)

V_0_0_2 = "VERSION_MAJOR = 0\nVERSION_MINOR = 0\nPATCHLEVEL = 2\nVERSION_TWEAK = 0\n"
V_0_0_3 = "VERSION_MAJOR = 0\nVERSION_MINOR = 0\nPATCHLEVEL = 3\nVERSION_TWEAK = 0\n"
V_0_0_4 = "VERSION_MAJOR = 0\nVERSION_MINOR = 0\nPATCHLEVEL = 4\nVERSION_TWEAK = 0\n"

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
        # any firmware change introduces counts as raising it. This is the pure
        # rule; where the baseline comes from is decided before it — see
        # `TheBootstrapBaseline` below, which is what stops that reading being
        # applied to a branch that simply never carried the file.
        ok, _ = check([SOURCE], "", V_0_0_2)

        self.assertTrue(ok)


class WhichTagNamesThePublishedVersion(unittest.TestCase):
    def test_it_finds_the_highest(self):
        self.assertEqual(
            newest_published_tag(
                [f"{TAG_PREFIX}0.0.2", f"{TAG_PREFIX}0.0.3", f"{TAG_PREFIX}0.0.1"]
            ),
            f"{TAG_PREFIX}0.0.3",
        )

    def test_it_orders_numerically_and_not_by_string(self):
        # `0.0.9` sorts after `0.0.10` as text, and picking the wrong one would
        # let a published version be reused.
        self.assertEqual(
            newest_published_tag([f"{TAG_PREFIX}0.0.9", f"{TAG_PREFIX}0.0.10"]),
            f"{TAG_PREFIX}0.0.10",
        )

    def test_somebody_elses_tags_are_not_shard_releases(self):
        self.assertIsNone(newest_published_tag(["Omi_CV1_v3.0.21", "v1.0", "phase-2"]))

    def test_nothing_published_is_not_a_version(self):
        # A repository before its first release. No baseline is invented.
        self.assertIsNone(newest_published_tag([]))


class TheBootstrapBaseline(unittest.TestCase):
    """The real historical state, end to end through git.

    `main` never carried `omi/firmware/omi/VERSION` — the file was introduced
    on the branch that produced the first release. An absent file parses as
    0.0.0, so without the bootstrap the published 0.0.3 looks like a rise and a
    firmware change under the published number passes.

    Driven through `main()` rather than `check()` on purpose: what was wrong was
    the baseline, and the baseline is chosen by the wiring.
    """

    def git(self, *args):
        subprocess.run(
            ["git", *args], cwd=self.repo, check=True, capture_output=True, text=True
        )

    def write(self, path, text):
        full = os.path.join(self.repo, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as handle:
            handle.write(text)

    def gate(self):
        """Run the gate against `main`, in the repository, and report its exit."""
        here = os.getcwd()
        os.chdir(self.repo)
        try:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = main(["version_gate.py", "main"])
            return code, out.getvalue()
        finally:
            os.chdir(here)

    def setUp(self):
        self.repo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)

        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "gate@example.invalid")
        self.git("config", "user.name", "Gate Test")

        # `main`, as it actually is: firmware, and no VERSION file anywhere.
        self.write(SOURCE, "int shipped(void) { return 0; }\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "main without a VERSION file")

        # The branch that introduced the version and produced the release.
        self.git("checkout", "-q", "-b", "shard")
        self.write(VERSION_FILE, V_0_0_3)
        self.git("add", "-A")
        self.git("commit", "-qm", "the released 0.0.3")
        self.git("tag", "-a", f"{TAG_PREFIX}0.0.3", "-m", "released")

    def test_a_firmware_change_under_the_published_version_is_refused(self):
        self.write(SOURCE, "int shipped(void) { return 1; }\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "change the firmware, leave VERSION alone")

        code, message = self.gate()

        self.assertEqual(code, 1, message)
        self.assertIn(f"{TAG_PREFIX}0.0.3", message)
        self.assertIn("unchanged from", message)

    def test_the_same_change_with_the_next_version_is_allowed(self):
        self.write(SOURCE, "int shipped(void) { return 1; }\n")
        self.write(VERSION_FILE, V_0_0_4)
        self.git("add", "-A")
        self.git("commit", "-qm", "change the firmware and raise VERSION")

        code, message = self.gate()

        self.assertEqual(code, 0, message)
        self.assertIn("0.0.3+0 -> 0.0.4+0", message)

    def test_without_any_release_nothing_is_invented(self):
        # A repository before its first release keeps the old reading: there is
        # no published line to be measured against, and inventing one would
        # refuse the very first firmware change anybody made.
        self.git("tag", "-d", f"{TAG_PREFIX}0.0.3")
        self.write(SOURCE, "int shipped(void) { return 1; }\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "change the firmware before any release")

        code, _ = self.gate()

        self.assertEqual(code, 0)

    def test_a_version_on_the_base_still_wins(self):
        # The bootstrap must never override a version somebody wrote down. Once
        # `main` carries one, that is the baseline again.
        self.git("checkout", "-q", "main")
        self.write(VERSION_FILE, V_0_0_4)
        self.git("add", "-A")
        self.git("commit", "-qm", "main now carries 0.0.4")

        self.git("checkout", "-q", "shard")
        self.write(SOURCE, "int shipped(void) { return 1; }\n")
        self.write(VERSION_FILE, V_0_0_4)
        self.git("add", "-A")
        self.git("commit", "-qm", "firmware change, still 0.0.4")

        code, message = self.gate()

        # Refused against main's 0.0.4, not against the tag's 0.0.3.
        self.assertEqual(code, 1, message)
        self.assertIn("the target branch", message)
        self.assertIn("0.0.4", message)


if __name__ == "__main__":
    unittest.main()
