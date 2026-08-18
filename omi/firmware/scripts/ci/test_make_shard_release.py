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


# The manifest sysbuild actually writes for this board, field for field, read
# off a real `dfu_application.zip`. The earlier fixture here declared a single
# entry with no `image_index` and no `board` — the shape a release *ends up*
# having rather than the shape a build *produces*. Every test passed, and the
# first real candidate run refused the build package it was handed.
APP_CORE = {
    "type": "application",
    "board": "omi",
    "soc": "nrf5340",
    "load_address": 66048,
    "image_index": "0",
    "slot_index_primary": "1",
    "slot_index_secondary": "2",
    "version_MCUBOOT": "0.0.4+0",
    "size": 249148,
    "file": "omi.signed.bin",
    "modtime": 1786861789,
}

RADIO_CORE = {
    "type": "application",
    "board": "omi/nrf5340/cpunet",
    "soc": "nrf5340",
    "load_address": 16812032,
    "image_index": "1",
    "slot_index_primary": "3",
    "slot_index_secondary": "4",
    "version_MCUBOOT": None,
    "size": 175092,
    "file": "ipc_radio.bin",
    "modtime": 1786861789,
}

# Not a valid MCUboot image on purpose: nothing may parse the radio core, and a
# test that handed it a real one could not show that.
RADIO_BLOB = b"the radio core, which a Shard release does not publish"


def package(path, entries=None, images=None):
    """A DFU package in the shape sysbuild produces one — both cores."""
    entries = [dict(APP_CORE), dict(RADIO_CORE)] if entries is None else entries
    if images is None:
        images = (("omi.signed.bin", None), ("ipc_radio.bin", RADIO_BLOB))

    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "format-version": 1,
                    "time": 1786862021,
                    "files": entries,
                    "name": "omi",
                }
            ),
        )
        for name, blob in images:
            archive.writestr(name, blob if blob is not None else signed_image())
    return path


def assemble(directory, version="0.0.4", entries=None, images=None):
    built = package(directory / "dfu_application.zip", entries=entries, images=images)
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
    def test_a_third_image_this_line_does_not_know_is_refused(self):
        # Not "everything except the app core is dropped". An image nobody has
        # decided about stops the release; dropping it silently would be a
        # decision made by omission.
        stranger = dict(RADIO_CORE, image_index="2", board="omi/nrf5340/cpuppr",
                        file="stranger.bin")
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(Refused) as refusal:
                assemble(
                    Path(raw),
                    entries=[dict(APP_CORE), dict(RADIO_CORE), stranger],
                    images=(
                        ("omi.signed.bin", None),
                        ("ipc_radio.bin", RADIO_BLOB),
                        ("stranger.bin", RADIO_BLOB),
                    ),
                )

        self.assertIn("does not know", str(refusal.exception))
        self.assertIn("stranger.bin", str(refusal.exception))

    def test_a_second_image_at_the_app_core_index_is_refused(self):
        twin = dict(APP_CORE, file="other.signed.bin")
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(Refused) as refusal:
                assemble(
                    Path(raw),
                    entries=[dict(APP_CORE), twin],
                    images=(("omi.signed.bin", None), ("other.signed.bin", None)),
                )

        self.assertIn("2 images at index 0", str(refusal.exception))

    def test_a_package_with_no_application_core_is_refused(self):
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(Refused) as refusal:
                assemble(
                    Path(raw),
                    entries=[dict(RADIO_CORE)],
                    images=(("ipc_radio.bin", RADIO_BLOB),),
                )

        self.assertIn("0 images at index 0", str(refusal.exception))

    def test_an_app_core_for_another_board_is_refused(self):
        # The index alone is not identity: index 0 of some other product is not
        # this product's application core.
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(Refused) as refusal:
                assemble(Path(raw), entries=[dict(APP_CORE, board="somebody_else")])

        self.assertIn("not the", str(refusal.exception))

    def test_a_manifest_naming_an_image_the_package_lacks_is_refused(self):
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(Refused) as refusal:
                assemble(
                    Path(raw),
                    entries=[dict(APP_CORE, file="absent.bin")],
                    images=(("omi.signed.bin", None),),
                )

        self.assertIn("does not contain it", str(refusal.exception))

    def test_a_package_without_a_manifest_is_refused(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            built = directory / "dfu_application.zip"
            with zipfile.ZipFile(built, "w") as archive:
                archive.writestr("omi.signed.bin", signed_image())

            with self.assertRaises(Refused) as refusal:
                write_release(
                    package=built,
                    out=directory / "out",
                    version="0.0.4",
                    tag="shard-cv1-v0.0.4",
                    commit="935ff3db",
                    built_at="2026-08-17T09:00:00Z",
                    ncs="v2.9.0",
                    container="ghcr.io/zephyrproject-rtos/ci@sha256:b0ac63",
                )

        self.assertIn("no manifest.json", str(refusal.exception))

    def test_a_manifest_that_is_not_json_is_refused(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            built = directory / "dfu_application.zip"
            with zipfile.ZipFile(built, "w") as archive:
                archive.writestr("manifest.json", "{not json")
                archive.writestr("omi.signed.bin", signed_image())

            with self.assertRaises(Refused) as refusal:
                write_release(
                    package=built,
                    out=directory / "out",
                    version="0.0.4",
                    tag="shard-cv1-v0.0.4",
                    commit="935ff3db",
                    built_at="2026-08-17T09:00:00Z",
                    ncs="v2.9.0",
                    container="ghcr.io/zephyrproject-rtos/ci@sha256:b0ac63",
                )

        self.assertIn("not JSON", str(refusal.exception))

    def test_an_image_that_disagrees_with_the_release_version_is_refused(self):
        # Both are derived from the same VERSION file, so they cannot disagree
        # unless the build used a different tree than the one being released.
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(Refused) as refusal:
                assemble(
                    Path(raw),
                    version="0.0.5",
                    images=(
                        ("omi.signed.bin", signed_image(version=(0, 0, 4, 0))),
                        ("ipc_radio.bin", RADIO_BLOB),
                    ),
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
                assemble(directory, entries=[dict(APP_CORE, board="somebody_else")])

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
                ("ipc_radio.bin", RADIO_BLOB),
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


class NarrowingTheBuildPackage(unittest.TestCase):
    """The first real candidate run, kept as a test.

    sysbuild builds both cores into one DFU package and always has. The release
    line publishes the application core alone — 0.0.3 is that shape. Between the
    two there is a narrowing, and until the first real run nothing performed it
    and no test modelled the input that needed it.
    """

    def released(self, directory):
        """Assemble from the real two-image build package and open the asset."""
        asset = assemble(directory)[0]
        return zipfile.ZipFile(asset)

    def test_the_real_two_image_build_package_is_accepted(self):
        # What the first candidate run was handed, and refused.
        with tempfile.TemporaryDirectory() as raw:
            with self.released(Path(raw)) as release:
                self.assertIn("omi.signed.bin", release.namelist())

    def test_the_radio_core_is_not_published(self):
        with tempfile.TemporaryDirectory() as raw:
            with self.released(Path(raw)) as release:
                self.assertNotIn("ipc_radio.bin", release.namelist())

    def test_the_asset_holds_exactly_the_image_and_its_manifest(self):
        with tempfile.TemporaryDirectory() as raw:
            with self.released(Path(raw)) as release:
                self.assertEqual(
                    sorted(release.namelist()), ["manifest.json", "omi.signed.bin"]
                )

    def test_the_manifest_declares_the_application_core_alone(self):
        with tempfile.TemporaryDirectory() as raw:
            with self.released(Path(raw)) as release:
                manifest = json.loads(release.read("manifest.json"))

            self.assertEqual(len(manifest["files"]), 1)
            entry = manifest["files"][0]
            self.assertEqual(entry["file"], "omi.signed.bin")
            self.assertEqual(entry["image_index"], "0")
            self.assertEqual(entry["board"], "omi")

    def test_the_surviving_entry_is_copied_rather_than_rebuilt(self):
        # What a device reads about an image it is about to write is the build's
        # own description of it, field for field.
        with tempfile.TemporaryDirectory() as raw:
            with self.released(Path(raw)) as release:
                entry = json.loads(release.read("manifest.json"))["files"][0]

            self.assertEqual(entry, APP_CORE)

    def test_the_rest_of_the_manifest_survives(self):
        with tempfile.TemporaryDirectory() as raw:
            with self.released(Path(raw)) as release:
                manifest = json.loads(release.read("manifest.json"))

            self.assertEqual(manifest["name"], "omi")
            self.assertEqual(manifest["format-version"], 1)

    def test_the_image_bytes_are_the_ones_that_were_built(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            asset = assemble(directory)[0]

            with zipfile.ZipFile(directory / "dfu_application.zip") as built:
                original = built.read("omi.signed.bin")
            with zipfile.ZipFile(asset) as release:
                self.assertEqual(release.read("omi.signed.bin"), original)

    def test_the_same_build_package_always_yields_the_same_asset(self):
        # A release is identified by its hashes. Two runs over one build package
        # must not produce two different files.
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            built = package(directory / "dfu_application.zip")

            digests = []
            for run in ("one", "two"):
                asset = write_release(
                    package=built,
                    out=directory / run,
                    version="0.0.4",
                    tag="shard-cv1-v0.0.4",
                    commit="935ff3db",
                    built_at="2026-08-17T09:00:00Z",
                    ncs="v2.9.0",
                    container="ghcr.io/zephyrproject-rtos/ci@sha256:b0ac63",
                )[0]
                digests.append(sha256_file(asset))

            self.assertEqual(digests[0], digests[1])

    def test_the_sums_describe_the_narrowed_asset(self):
        # The hashes must be of the file that is uploaded, not of the build
        # package it was derived from.
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            asset, manifest, sums = assemble(directory)

            recorded = dict(
                reversed(line.split("  ", 1))
                for line in sums.read_text(encoding="utf-8").splitlines()
            )
            self.assertEqual(recorded[asset.name], sha256_file(asset))
            self.assertNotEqual(
                sha256_file(asset), sha256_file(directory / "dfu_application.zip")
            )
            self.assertIn(sha256_file(asset), manifest.read_text(encoding="utf-8"))

    def test_it_has_the_shape_the_published_release_has(self):
        # 0.0.3 as the compatibility reference: one application-core image, one
        # manifest entry, no radio core. Read from this repository's own record
        # of it rather than from an artefact nobody here can open.
        with tempfile.TemporaryDirectory() as raw:
            with self.released(Path(raw)) as release:
                names = sorted(release.namelist())
                manifest = json.loads(release.read("manifest.json"))

        self.assertEqual(names, ["manifest.json", "omi.signed.bin"])
        self.assertEqual([f["type"] for f in manifest["files"]], ["application"])
        self.assertEqual(sorted(manifest), ["files", "format-version", "name", "time"])


if __name__ == "__main__":
    unittest.main()
