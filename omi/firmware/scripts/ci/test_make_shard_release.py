#!/usr/bin/env python3
"""What a release may be assembled from, and what is refused.

Run with ``python3 -m unittest`` from ``omi/firmware/scripts/ci``.

The images here are synthetic — built by ``signed_image`` below in the same
shape MCUboot writes. The reader they exercise was also checked against the
published ``0.0.3`` artefact, and reproduces all three hashes recorded for it in
SHARD_RELEASES.md §3.
"""

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from make_shard_release import (
    HEADER,
    IMAGE_MAGIC,
    MANIFEST_NAME,
    SUMS_NAME,
    TLV_ENTRY,
    TLV_INFO,
    TLV_INFO_MAGIC,
    TLV_SHA256,
    Refused,
    parse_image,
    sha256_file,
    write_release,
)

RSA2048_PSS = 0x20


def signed_image(
    version=(0, 0, 4, 0),
    payload=b"the firmware itself" * 16,
    header_size=512,
    magic=IMAGE_MAGIC,
    sha=True,
    signature=True,
    corrupt_sha=False,
):
    """An MCUboot image in the shape the real build writes one.

    The real header is padded to 512 bytes with the payload after it, which is
    why the reader must use ``hdr_size`` rather than the struct's own length.
    """
    major, minor, revision, build = version
    header = HEADER.pack(
        magic, 0x10000, header_size, 0, len(payload), 0, major, minor, revision, build, 0
    )
    covered = header + bytes(header_size - HEADER.size) + payload

    entries = b""
    if sha:
        digest = bytes(32) if corrupt_sha else hashlib.sha256(covered).digest()
        entries += TLV_ENTRY.pack(TLV_SHA256, len(digest)) + digest
    if signature:
        entries += TLV_ENTRY.pack(RSA2048_PSS, 256) + bytes(256)

    trailer = TLV_INFO.pack(TLV_INFO_MAGIC, TLV_INFO.size + len(entries)) + entries
    return covered + trailer


def package(path, images=(("omi.signed.bin", None),), kinds=("application",)):
    """A DFU package in the shape sysbuild produces one."""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "format-version": 1,
                    "files": [{"type": kind, "file": "omi.signed.bin"} for kind in kinds],
                    "name": "omi",
                }
            ),
        )
        for name, blob in images:
            archive.writestr(name, blob if blob is not None else signed_image())
    return path


def assemble(directory, version="0.0.4", images=(("omi.signed.bin", None),), kinds=("application",)):
    built = package(directory / "dfu_application.zip", images=images, kinds=kinds)
    return write_release(
        package=built,
        out=directory / "out",
        version=version,
        tag=f"shard-cv1-v{version}",
        commit="935ff3dbaff98d95c0922d572aa5f32d0e4ca46e",
        built_at="2026-08-17T09:00:00Z",
        ncs="v2.9.0",
        container="ghcr.io/zephyrproject-rtos/ci:v0.26.13@sha256:b0ac63",
    )


class ReadingTheImage(unittest.TestCase):
    def test_it_reads_both_forms_of_the_version(self):
        image = parse_image(signed_image(version=(0, 0, 4, 0)))

        # The product version is what a device reports; the image version is
        # what the bootloader compares. They differ on purpose.
        self.assertEqual(image.version, "0.0.4")
        self.assertEqual(image.image_version, "0.0.4+0")

    def test_the_payload_hash_is_the_hash_of_the_bytes_it_covers(self):
        blob = signed_image()
        image = parse_image(blob)

        fields = HEADER.unpack_from(blob, 0)
        header_size, payload_size = fields[2], fields[4]
        self.assertEqual(
            image.payload_sha256,
            hashlib.sha256(blob[: header_size + payload_size]).hexdigest(),
        )

    def test_the_image_hash_covers_the_whole_signed_image(self):
        blob = signed_image()

        self.assertEqual(parse_image(blob).image_sha256, hashlib.sha256(blob).hexdigest())

    def test_it_names_what_signed_the_image(self):
        self.assertEqual(parse_image(signed_image()).signature, "RSA-2048, PSS")


class WhatTheReaderRefuses(unittest.TestCase):
    def test_something_that_is_not_an_mcuboot_image(self):
        with self.assertRaises(Refused) as refusal:
            parse_image(signed_image(magic=0xDEADBEEF))

        self.assertIn("MCUboot magic", str(refusal.exception))

    def test_an_image_whose_recorded_hash_does_not_match_its_bytes(self):
        # The bootloader checks this before accepting an image, so such a build
        # could not be installed — and the value would otherwise have gone into
        # the archive as the hash that identifies the firmware itself.
        with self.assertRaises(Refused) as refusal:
            parse_image(signed_image(corrupt_sha=True))

        self.assertIn("not the hash of the bytes it covers", str(refusal.exception))

    def test_an_image_with_no_hash_at_all(self):
        with self.assertRaises(Refused) as refusal:
            parse_image(signed_image(sha=False))

        self.assertIn("no SHA-256 TLV", str(refusal.exception))

    def test_an_unsigned_image(self):
        with self.assertRaises(Refused) as refusal:
            parse_image(signed_image(signature=False))

        self.assertIn("no signature TLV", str(refusal.exception))

    def test_a_truncated_image(self):
        with self.assertRaises(Refused):
            parse_image(signed_image()[:20])


class WhatThePackageMustBe(unittest.TestCase):
    def test_a_package_carrying_a_second_image_is_refused(self):
        # App core only. A net-core image would update something this release
        # line has never claimed to update.
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(Refused) as refusal:
                assemble(
                    Path(raw),
                    images=(
                        ("omi.signed.bin", signed_image()),
                        ("net_core.signed.bin", signed_image()),
                    ),
                )

        self.assertIn("2 images", str(refusal.exception))

    def test_a_package_declaring_a_net_core_is_refused(self):
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(Refused) as refusal:
                assemble(Path(raw), kinds=("application", "netcore"))

        self.assertIn("expected the application core alone", str(refusal.exception))

    def test_an_image_that_disagrees_with_the_release_version_is_refused(self):
        # Both are derived from the same VERSION file, so they cannot disagree
        # unless the build used a different tree than the one being released.
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(Refused) as refusal:
                assemble(
                    Path(raw),
                    version="0.0.5",
                    images=(("omi.signed.bin", signed_image(version=(0, 0, 4, 0))),),
                )

        self.assertIn("0.0.4+0", str(refusal.exception))
        self.assertIn("0.0.5", str(refusal.exception))

    def test_a_refused_package_is_not_left_behind_under_the_release_name(self):
        # §5: a candidate and a release carry the same filename, and a file
        # picker shows the name. A refused artefact must not sit in the
        # directory whose whole purpose is "the files to upload".
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            with self.assertRaises(Refused):
                assemble(directory, kinds=("netcore",))

            self.assertEqual(list((directory / "out").glob("*.zip")), [])


class TheThreeFiles(unittest.TestCase):
    def test_a_release_is_exactly_three_files(self):
        with tempfile.TemporaryDirectory() as raw:
            written = assemble(Path(raw))

            self.assertEqual(
                sorted(path.name for path in written),
                [MANIFEST_NAME, SUMS_NAME, "Shard_CV1_appcore_v0.0.4.zip"],
            )
            self.assertEqual(len(list((Path(raw) / "out").iterdir())), 3)

    def test_the_asset_is_named_after_the_version(self):
        with tempfile.TemporaryDirectory() as raw:
            asset = assemble(Path(raw), version="1.2.3", images=(
                ("omi.signed.bin", signed_image(version=(1, 2, 3, 0))),
            ))[0]

            self.assertEqual(asset.name, "Shard_CV1_appcore_v1.2.3.zip")

    def test_the_sums_are_the_hashes_of_the_files_that_were_written(self):
        with tempfile.TemporaryDirectory() as raw:
            asset, manifest, sums = assemble(Path(raw))

            recorded = {}
            for line in sums.read_text(encoding="utf-8").splitlines():
                digest, name = line.split("  ", 1)
                recorded[name] = digest

            self.assertEqual(recorded[asset.name], sha256_file(asset))
            self.assertEqual(recorded[manifest.name], sha256_file(manifest))

    def test_the_sums_do_not_list_themselves(self):
        # A file cannot carry its own hash. The chain ends at the release page.
        with tempfile.TemporaryDirectory() as raw:
            sums = assemble(Path(raw))[2]

            self.assertNotIn(SUMS_NAME, sums.read_text(encoding="utf-8"))

    def test_the_manifest_records_the_hash_of_the_asset_beside_it(self):
        with tempfile.TemporaryDirectory() as raw:
            asset, manifest, _ = assemble(Path(raw))

            self.assertIn(sha256_file(asset), manifest.read_text(encoding="utf-8"))

    def test_the_manifest_records_where_the_build_came_from(self):
        with tempfile.TemporaryDirectory() as raw:
            manifest = assemble(Path(raw))[1].read_text(encoding="utf-8")

            for expected in (
                "0.0.4",  # version
                "shard-cv1-v0.0.4",  # tag
                "935ff3dbaff98d95c0922d572aa5f32d0e4ca46e",  # commit
                "2026-08-17T09:00:00Z",  # build date
                "v2.9.0",  # NCS
                "ghcr.io/zephyrproject-rtos/ci",  # container
                "Shard_CV1_appcore_v0.0.4.zip",  # published file name
            ):
                self.assertIn(expected, manifest)

    def test_the_manifest_carries_all_three_hashes(self):
        with tempfile.TemporaryDirectory() as raw:
            asset, manifest, _ = assemble(Path(raw))
            text = manifest.read_text(encoding="utf-8")

            with zipfile.ZipFile(asset) as archive:
                image = parse_image(archive.read("omi.signed.bin"))

            self.assertIn(sha256_file(asset), text)
            self.assertIn(image.image_sha256, text)
            self.assertIn(image.payload_sha256, text)

    def test_the_manifest_says_what_the_build_did_not_prove(self):
        # The one thing a green build must never be read as saying.
        with tempfile.TemporaryDirectory() as raw:
            manifest = assemble(Path(raw))[1].read_text(encoding="utf-8")

            self.assertIn("did not put it on a device", manifest)
            self.assertIn("Not established", manifest)

    def test_the_manifest_carries_no_key_value_block(self):
        # §4: that shape is what the Omi backend parses. A Shard release must
        # not invite a reader to assume it is served to anything.
        with tempfile.TemporaryDirectory() as raw:
            manifest = assemble(Path(raw))[1].read_text(encoding="utf-8")

            self.assertNotIn("KEY_VALUE", manifest)


if __name__ == "__main__":
    unittest.main()
