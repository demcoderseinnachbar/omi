#!/usr/bin/env python3
"""What the release gate lets through, and what it stops.

Run with ``python3 -m unittest`` from ``omi/firmware/scripts/ci``.
"""

import contextlib
import io
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from release_gate import (
    NO_RELEASE,
    REFUSE,
    RELEASE,
    TAG_PREFIX,
    VERSION_FILE,
    check,
    main,
    release_version,
)

SOURCE = "omi/firmware/omi/src/haptic.c"


def version_file(major=0, minor=0, patch=3, tweak=0):
    """A VERSION file in the shape Zephyr reads and this fork writes."""
    return (
        f"VERSION_MAJOR = {major}\n"
        f"VERSION_MINOR = {minor}\n"
        f"PATCHLEVEL = {patch}\n"
        f"VERSION_TWEAK = {tweak}\n"
        "EXTRAVERSION =\n"
    )


SHIPPED = version_file(patch=3)  # 0.0.3, the released version
NEXT = version_file(patch=4)  # what a bump looks like


class WhatCountsAsARelease(unittest.TestCase):
    def test_a_raised_patch_level_is_a_release(self):
        decision, message, version = check(SHIPPED, NEXT, [])

        self.assertEqual(decision, RELEASE, message)
        self.assertEqual(version, "0.0.4")

    def test_a_raised_minor_is_a_release(self):
        decision, _, version = check(SHIPPED, version_file(minor=1, patch=0), [])

        self.assertEqual(decision, RELEASE)
        self.assertEqual(version, "0.1.0")

    def test_an_unchanged_version_is_not(self):
        # The ordinary outcome of almost every push to main.
        decision, message, _ = check(SHIPPED, SHIPPED, [])

        self.assertEqual(decision, NO_RELEASE, message)

    def test_the_current_version_is_reported_even_when_there_is_no_release(self):
        # Not decoration. A push that changes the firmware without raising the
        # version has to be able to name the draft it just overtook, and that
        # draft is named after the version on the branch right now.
        _, _, version = check(SHIPPED, SHIPPED, [])

        self.assertEqual(version, "0.0.3")

        _, _, version = check("", NEXT, [])

        self.assertEqual(version, "0.0.4")

    def test_a_tweak_on_its_own_is_not_a_release(self):
        # The tag carries X.Y.Z alone, so 0.0.3+0 and 0.0.3+1 would want one
        # tag between them — and the second would reuse a published number for
        # different bytes.
        decision, message, _ = check(SHIPPED, version_file(patch=3, tweak=1), [])

        self.assertEqual(decision, NO_RELEASE)
        self.assertIn("tweak", message)

    def test_no_predecessor_means_no_release_rather_than_a_release(self):
        # A shallow clone, a new branch, a rewritten history. Nothing is wrong,
        # but nothing is established either — and the safe answer is the one
        # that costs a manual run instead of a version number.
        decision, message, _ = check("", NEXT, [])

        self.assertEqual(decision, NO_RELEASE)
        self.assertIn("no rise can be established", message)


class WhatItRefuses(unittest.TestCase):
    def test_a_version_that_went_backwards(self):
        decision, message, _ = check(version_file(patch=4), SHIPPED, [])

        self.assertEqual(decision, REFUSE)
        self.assertIn("backwards", message)
        self.assertIn("downgrade prevention", message)

    def test_a_version_that_is_already_tagged(self):
        decision, message, _ = check(SHIPPED, NEXT, [f"{TAG_PREFIX}0.0.4"])

        self.assertEqual(decision, REFUSE)
        self.assertIn("already exists", message)

    def test_an_unrelated_tag_does_not_block_it(self):
        decision, _, version = check(
            SHIPPED, NEXT, [f"{TAG_PREFIX}0.0.3", f"{TAG_PREFIX}0.0.2"]
        )

        self.assertEqual(decision, RELEASE)
        self.assertEqual(version, "0.0.4")

    def test_a_version_file_missing_a_field(self):
        # `parse_version` reads an absent field as zero, which is right for
        # comparing and wrong for naming: this would otherwise release 0.0.0.
        without_patch = "VERSION_MAJOR = 0\nVERSION_MINOR = 1\nVERSION_TWEAK = 0\n"

        decision, message, _ = check(SHIPPED, without_patch, [])

        self.assertEqual(decision, REFUSE)
        self.assertIn("PATCHLEVEL", message)

    def test_a_missing_version_file(self):
        decision, message, _ = check(SHIPPED, "", [])

        self.assertEqual(decision, REFUSE)
        self.assertIn("missing or empty", message)


class TheNamingScheme(unittest.TestCase):
    def test_the_tag_is_the_product_version_without_the_tweak(self):
        self.assertEqual(release_version((1, 2, 3, 7)), "1.2.3")

    def test_the_tag_cannot_be_served_to_an_omi_user(self):
        # `FIRMWARE_TAG_PATTERN` in the Omi backend, verbatim. A Shard release
        # must not match it: the endpoint that serves Omi firmware reads tags,
        # and a matching one would offer this build to somebody else's pendant.
        omi_pattern = re.compile(
            r"^(?:Omi_CV1|Omi_DK2|OmiGlass|OpenGlass|Friend)_v[0-9]+(?:\.[0-9]+){1,2}$"
        )

        self.assertIsNone(omi_pattern.match(f"{TAG_PREFIX}0.0.4"))


class TheFirstCandidateOnABranchWithoutAVersion(unittest.TestCase):
    """The bootstrap, end to end through git.

    Until the first Shard change reaches `main`, that branch has no VERSION
    file. Without a baseline the gate answers *no release* whatever the version
    says — so the first candidate could never be drafted, and the only way to
    get one would be to push the released version's bytes to `main` first.
    That would leave `main` claiming to be a version that is already published
    for other bytes, which SHARD_RELEASES.md §2 forbids.
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

    def gate(self, before):
        here = os.getcwd()
        os.chdir(self.repo)
        try:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = main(["release_gate.py", "push", before])
            return code, out.getvalue()
        finally:
            os.chdir(here)

    def setUp(self):
        self.repo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)

        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "gate@example.invalid")
        self.git("config", "user.name", "Gate Test")

        self.write(SOURCE, "int shipped(void) { return 0; }\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "main without a VERSION file")
        self.before = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        # The release that exists in the world, tagged but never on `main`.
        self.write(VERSION_FILE, version_file(patch=3))
        self.git("add", "-A")
        self.git("commit", "-qm", "the released 0.0.3")
        self.git("tag", "-a", f"{TAG_PREFIX}0.0.3", "-m", "released")
        self.git("reset", "-q", "--hard", self.before)

    def test_one_push_carrying_the_next_version_is_a_candidate(self):
        self.write(SOURCE, "int shipped(void) { return 1; }\n")
        self.write(VERSION_FILE, version_file(patch=4))
        self.git("add", "-A")
        self.git("commit", "-qm", "the haptic fix and 0.0.4, in one push")

        code, out = self.gate(self.before)

        self.assertEqual(code, 0, out)
        self.assertIn("rose 0.0.3 -> 0.0.4", out)
        self.assertIn("release=true", out)
        self.assertIn(f"tag={TAG_PREFIX}0.0.4", out)

    def test_the_published_version_never_becomes_a_candidate_again(self):
        # Before the bootstrap this read as a rise from nothing and would have
        # drafted a second release under a published number. Now the tag is the
        # baseline, the version is seen to be unchanged, and no candidate is
        # produced.
        #
        # Not a refusal: refusing a firmware change under the published version
        # is the PR gate's job, and this one deliberately resolves anything
        # short of a clear rise to *no release*. What it does emit is
        # `firmware_changed`, which is how the workflow marks a waiting draft as
        # superseded rather than letting it be published as current.
        self.write(SOURCE, "int shipped(void) { return 1; }\n")
        self.write(VERSION_FILE, version_file(patch=3))
        self.git("add", "-A")
        self.git("commit", "-qm", "firmware change under the published version")

        code, out = self.gate(self.before)

        self.assertEqual(code, 0, out)
        self.assertIn("unchanged at 0.0.3", out)
        self.assertIn("release=false", out)
        self.assertIn("firmware_changed=true", out)

    def test_without_any_release_there_is_still_nothing_to_compare(self):
        self.git("tag", "-d", f"{TAG_PREFIX}0.0.3")
        self.write(VERSION_FILE, version_file(patch=4))
        self.git("add", "-A")
        self.git("commit", "-qm", "a first VERSION, nothing published yet")

        code, out = self.gate(self.before)

        self.assertEqual(code, 0, out)
        self.assertIn("release=false", out)



class RecoveringAFailedCandidate(unittest.TestCase):
    """The real 0.0.4 recovery, kept as a test.

    A candidate run can fail before it drafts anything. The version it was for
    is then stuck: `main` moves on carrying the same VERSION, the rise the push
    gate looks for never comes back, and no later push can produce that
    candidate. Raising the version to get another attempt would spend a number
    on nothing and claim a change that did not happen.

    So `recovery` mode asks a different question — is this version newer than
    the one that is *published* — and it is reached only by a deliberate manual
    run. The push path is untouched, which the last two tests here pin down.
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

    def gate(self, *argv):
        here = os.getcwd()
        os.chdir(self.repo)
        try:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = main(["release_gate.py", *argv])
            return code, out.getvalue()
        finally:
            os.chdir(here)

    def commit(self, message, version=None, source=None):
        if version is not None:
            self.write(VERSION_FILE, version_file(patch=version))
        if source is not None:
            self.write(SOURCE, source)
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def setUp(self):
        self.repo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)

        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "gate@example.invalid")
        self.git("config", "user.name", "Gate Test")

        # 0.0.3, published: the tag exists and is the baseline a recovery run
        # measures against.
        self.commit("the released 0.0.3", version=3, source="int shipped(void);")
        self.git("tag", "-a", TAG_PREFIX + "0.0.3", "-m", "released")

        # The push that raised the version. Its candidate run failed before
        # drafting anything, which leaves no trace here — that is the point.
        self.before_the_fix = self.commit("raise VERSION to 0.0.4", version=4)

        # The pipeline fix. Same VERSION, no firmware touched.
        self.write("omi/firmware/scripts/ci/make_shard_release.py", "# fixed")
        self.git("add", "-A")
        self.git("commit", "-qm", "fix the packager")

    def test_the_push_after_the_fix_produces_nothing(self):
        # A: what actually happened. Correct, and the reason recovery exists.
        code, out = self.gate("push", self.before_the_fix)

        self.assertEqual(code, 0, out)
        self.assertIn("unchanged at 0.0.4", out)
        self.assertIn("release=false", out)

    def test_a_recovery_run_rebuilds_the_same_unpublished_candidate(self):
        # B: the version is newer than the published one and unclaimed, so the
        # candidate it was always owed can still be built — without touching
        # VERSION.
        code, out = self.gate("recovery")

        self.assertEqual(code, 0, out)
        self.assertIn("rose 0.0.3 -> 0.0.4", out)
        self.assertIn("release=true", out)
        self.assertIn("tag=" + TAG_PREFIX + "0.0.4", out)

    def test_a_recovery_run_never_supersedes(self):
        # A retry is not the branch overtaking a draft, so the workflow must
        # never be told the firmware moved on.
        _, out = self.gate("recovery")

        self.assertIn("firmware_changed=false", out)

    def test_a_recovery_run_at_the_published_version_produces_nothing(self):
        # C: nothing is owed. The published version is not rebuilt.
        self.commit("back to the published version", version=3)

        code, out = self.gate("recovery")

        self.assertEqual(code, 0, out)
        self.assertIn("unchanged at 0.0.3", out)
        self.assertIn("release=false", out)

    def test_a_recovery_run_below_the_published_version_is_refused(self):
        # D: a device on 0.0.3 could never take 0.0.2.
        self.commit("go backwards", version=2)

        code, out = self.gate("recovery")

        self.assertEqual(code, 1, out)
        self.assertIn("went backwards", out)

    def test_a_recovery_run_without_any_release_invents_no_baseline(self):
        # E: nothing published, so nothing established. Never a release.
        self.git("tag", "-d", TAG_PREFIX + "0.0.3")

        code, out = self.gate("recovery")

        self.assertEqual(code, 0, out)
        self.assertIn("No previous VERSION to compare with", out)
        self.assertIn("release=false", out)

    def test_a_recovery_run_will_not_reclaim_a_published_version(self):
        # The invariant a retry must never break: a tagged version is spent.
        self.commit("back to the published version", version=3)
        self.git("tag", "-a", TAG_PREFIX + "0.0.4", "-m", "published later")
        self.commit("and up again", version=4)

        code, out = self.gate("recovery")

        self.assertEqual(code, 1, out)
        self.assertIn("already exists", out)

    def test_the_ordinary_rise_still_produces_a_candidate(self):
        # F: the automatic path is untouched.
        before = self.commit("no change", source="int shipped(void); /* x */")
        self.commit("raise to 0.0.5", version=5)

        code, out = self.gate("push", before)

        self.assertEqual(code, 0, out)
        self.assertIn("rose 0.0.4 -> 0.0.5", out)
        self.assertIn("release=true", out)

    def test_an_ordinary_push_without_a_rise_still_produces_nothing(self):
        # G: and it is still quiet the rest of the time.
        before = self.commit("documentation only", source="int shipped(void); /* a */")
        self.commit("more documentation", source="int shipped(void); /* y */")

        code, out = self.gate("push", before)

        self.assertEqual(code, 0, out)
        self.assertIn("release=false", out)


class HowTheGateIsCalled(unittest.TestCase):
    """The mode is named, never inferred from the number of arguments."""

    def run_gate(self, *argv):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = main(["release_gate.py", *argv])
        return code, out.getvalue()

    def test_a_bare_ref_is_not_a_mode(self):
        code, out = self.run_gate("HEAD~1")

        self.assertEqual(code, 2)
        self.assertIn("usage:", out)

    def test_push_without_a_ref_is_refused(self):
        code, out = self.run_gate("push")

        self.assertEqual(code, 2)
        self.assertIn("usage:", out)

    def test_recovery_takes_no_ref(self):
        code, out = self.run_gate("recovery", "HEAD~1")

        self.assertEqual(code, 2)
        self.assertIn("usage:", out)

if __name__ == "__main__":
    unittest.main()
