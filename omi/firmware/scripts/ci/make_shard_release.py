#!/usr/bin/env python3
"""Turns a freshly built DFU package into the three files a Shard release is.

SHARD_RELEASES.md §3: a published release carries exactly the package,
``RELEASE_MANIFEST.md`` and ``SHA256SUMS``, and together they *are* the release.
This assembles those three from one build, and refuses if the package is not
something a release may contain.

Every hash it records is read from the **final file under its final name**, in
this run's output directory. Nothing is carried over from an earlier build and
nothing is copied out of a previous manifest: MCUboot signs with RSA-PSS, whose
salt is random, so two builds of byte-identical firmware differ in their
signature and therefore in their image and archive hashes. A hash inherited from
an earlier build would silently stop identifying the file it is attached to.

It creates no tag, publishes nothing and contacts nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

# MCUboot's image format, from `boot/bootutil/include/bootutil/image.h`.
IMAGE_MAGIC = 0x96F3B83D
HEADER = struct.Struct("<IIHHIIBBHII")  # 32 bytes; fields unpacked in parse_image.
TLV_INFO = struct.Struct("<HH")
TLV_ENTRY = struct.Struct("<HH")
TLV_INFO_MAGIC = 0x6907
TLV_PROT_INFO_MAGIC = 0x6908

TLV_SHA256 = 0x10

# Signature TLVs by what they mean, so the manifest can say what signed the
# image instead of printing a bare hex type.
SIGNATURE_TLVS = {
    0x20: "RSA-2048, PSS",
    0x21: "ECDSA-224",
    0x22: "ECDSA",
    0x23: "RSA-3072, PSS",
    0x24: "Ed25519",
}

ASSET_TEMPLATE = "Shard_CV1_appcore_v{version}.zip"
MANIFEST_NAME = "RELEASE_MANIFEST.md"
SUMS_NAME = "SHA256SUMS"


class Refused(Exception):
    """A package that must not become a release."""


@dataclass(frozen=True)
class ImageInfo:
    """What the signed image says about itself, and what it hashes to."""

    version: str  # X.Y.Z — the product version, what a device reports
    image_version: str  # X.Y.Z+B — what MCUboot compares
    size: int
    signature: str
    image_sha256: str  # this signed image; does not survive a rebuild
    payload_sha256: str  # this firmware; the only hash that does


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tlvs(blob: bytes, start: int, magic: int) -> dict[int, bytes]:
    """Read one TLV area, checking it is the area it claims to be."""
    if start + TLV_INFO.size > len(blob):
        raise Refused("The image ends before its TLV trailer begins.")

    found_magic, total = TLV_INFO.unpack_from(blob, start)
    if found_magic != magic:
        raise Refused(
            f"Expected a TLV area with magic {magic:#06x} at offset {start}, "
            f"found {found_magic:#06x}. This is not an MCUboot image this "
            "script understands, and guessing at its layout would produce a "
            "hash that identifies nothing."
        )

    entries: dict[int, bytes] = {}
    offset = start + TLV_INFO.size
    end = min(start + total, len(blob))
    while offset + TLV_ENTRY.size <= end:
        kind, length = TLV_ENTRY.unpack_from(blob, offset)
        offset += TLV_ENTRY.size
        entries[kind] = blob[offset : offset + length]
        offset += length
    return entries


def parse_image(blob: bytes) -> ImageInfo:
    """Read a signed MCUboot image.

    Deliberately a small reader rather than a call into ``imgtool``: these
    values end up in an archival record, and parsing another tool's printed
    output is a way to record something subtly different from what is in the
    file. Checked against the published ``0.0.3`` artefact, whose three hashes
    are written down in SHARD_RELEASES.md §3 — this reader reproduces all
    three.
    """
    if len(blob) < HEADER.size:
        raise Refused("The image is too short to hold an MCUboot header.")

    (
        magic,
        _load_address,
        header_size,
        protected_tlv_size,
        payload_size,
        _flags,
        major,
        minor,
        revision,
        build,
        _padding,
    ) = HEADER.unpack_from(blob, 0)

    if magic != IMAGE_MAGIC:
        raise Refused(
            f"The image does not start with the MCUboot magic ({magic:#010x}, "
            f"expected {IMAGE_MAGIC:#010x}). Whatever this is, it is not "
            "something a device would accept."
        )

    offset = header_size + payload_size
    if protected_tlv_size:
        # Covered by the signature. Checked, then skipped: the hash and the
        # signature live in the unprotected trailer after it.
        read_tlvs(blob, offset, TLV_PROT_INFO_MAGIC)
        offset += protected_tlv_size

    tlvs = read_tlvs(blob, offset, TLV_INFO_MAGIC)

    payload_digest = tlvs.get(TLV_SHA256)
    if not payload_digest:
        raise Refused(
            "The image carries no SHA-256 TLV. That hash is the only one of the "
            "three that survives a rebuild, and a release cannot record what a "
            "build did not produce."
        )

    # Recompute it rather than copy it out. The TLV is what MCUboot will check
    # on the device before it accepts the image, and it covers the header, the
    # payload and any protected TLVs. A manifest that transcribed the recorded
    # value would say "the image claims this" where it reads as "this is the
    # firmware" — and would keep saying it for an image whose payload no longer
    # matched its own trailer.
    computed = hashlib.sha256(blob[:offset]).digest()
    if computed != payload_digest:
        raise Refused(
            f"The image's recorded SHA-256 ({payload_digest.hex()}) is not the "
            f"hash of the bytes it covers ({computed.hex()}). The bootloader "
            "checks this before accepting an image, so this one could not be "
            "installed — and the value would have gone into the archive as the "
            "one hash that is supposed to identify the firmware itself."
        )

    signatures = [SIGNATURE_TLVS[kind] for kind in tlvs if kind in SIGNATURE_TLVS]
    if not signatures:
        raise Refused(
            "The image carries no signature TLV. An unsigned image cannot be "
            "installed by a bootloader that verifies signatures, so publishing "
            "one would spend a version number on firmware no device can take."
        )

    return ImageInfo(
        version=f"{major}.{minor}.{revision}",
        image_version=f"{major}.{minor}.{revision}+{build}",
        size=len(blob),
        signature=", ".join(signatures),
        image_sha256=hashlib.sha256(blob).hexdigest(),
        payload_sha256=payload_digest.hex(),
    )


# What sysbuild puts in a build package for this board, named rather than
# counted. `SB_CONFIG_NETCORE_APP_UPDATE=y` has always been set, so the build
# package carries both cores; the release line carries the first alone.
#
# Both entries say `type: application`, so the type does not tell them apart.
# The index and the board do, and they are what the build actually writes:
#
#   index 0  board "omi"                    omi.signed.bin   the application core
#   index 1  board "omi/nrf5340/cpunet"     ipc_radio.bin    the radio core
#
# The file names are not pinned. They follow the Zephyr application name and
# would change for a reason that has nothing to do with what is being released;
# the index, board and core they describe are the identity.
APP_CORE_INDEX = "0"
APP_CORE_BOARD = "omi"
RADIO_CORE_INDEX = "1"
RADIO_CORE_BOARD = "omi/nrf5340/cpunet"


def select_app_core(manifest: dict) -> dict:
    """The one manifest entry a Shard release publishes.

    **Refuses rather than picks.** Every other composition — no application
    core, two of them, a third image, a radio core that is not the one this
    build has always produced — ends here. A release that quietly dropped an
    image it did not recognise would be claiming to have looked.
    """
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise Refused("The build package's manifest lists no files.")

    app = [f for f in files if f.get("image_index") == APP_CORE_INDEX]
    if len(app) != 1:
        raise Refused(
            f"The build package declares {len(app)} images at index "
            f"{APP_CORE_INDEX}, expected exactly one — the application core is "
            "what a Shard release is."
        )

    core = app[0]
    if core.get("type") != "application" or core.get("board") != APP_CORE_BOARD:
        raise Refused(
            f"The image at index {APP_CORE_INDEX} is "
            f"{core.get('type')!r} for board {core.get('board')!r}, not the "
            f"Shard application core ('application' for {APP_CORE_BOARD!r})."
        )

    for other in files:
        if other is core:
            continue
        if (
            other.get("image_index") != RADIO_CORE_INDEX
            or other.get("board") != RADIO_CORE_BOARD
        ):
            raise Refused(
                f"The build package carries an image this release line does not "
                f"know: index {other.get('image_index')!r}, board "
                f"{other.get('board')!r}, file {other.get('file')!r}. Only the "
                f"radio core at index {RADIO_CORE_INDEX} is a known build "
                "input, and it is not published. A new image is a decision "
                "about what a Shard release contains, not something to drop."
            )

    return core


def write_app_core_package(build_package: Path, asset: Path) -> None:
    """Narrow the build package to the one image a Shard release publishes.

    sysbuild produces both cores in one DFU package; §3 publishes the
    application core alone, and 0.0.3 is that shape. The narrowing happens here
    rather than in the build, so nothing about how the firmware is produced
    depends on what this release line chooses to ship.

    The surviving manifest entry is **copied**, never rebuilt: what a device
    reads about an image it is about to write is the build's own description of
    it, minus the entries for images that are not in the package.
    """
    with zipfile.ZipFile(build_package) as source:
        names = source.namelist()
        if "manifest.json" not in names:
            raise Refused(
                "The build package has no manifest.json, so which image is the "
                "application core cannot be established. It is not guessed."
            )
        try:
            manifest = json.loads(source.read("manifest.json"))
        except json.JSONDecodeError as broken:
            raise Refused(f"The build package's manifest is not JSON: {broken}")

        core = select_app_core(manifest)
        name = core.get("file")
        if not isinstance(name, str) or name not in names:
            raise Refused(
                f"The manifest names {name!r} as the application core, but the "
                "build package does not contain it."
            )

        kept = source.getinfo(name)
        blob = source.read(name)
        stamp = source.getinfo("manifest.json").date_time

    trimmed = dict(manifest)
    trimmed["files"] = [core]

    # Deterministic: the same build package always yields the same asset. The
    # image keeps its own entry metadata; the manifest is written with a fixed
    # shape and the timestamp it had in the build package.
    with zipfile.ZipFile(asset, "w", zipfile.ZIP_DEFLATED) as release:
        release.writestr(
            zipfile.ZipInfo("manifest.json", date_time=stamp),
            json.dumps(trimmed, indent=4) + "\n",
        )
        release.writestr(kept, blob)


def read_package(package: Path, expected_version: str) -> tuple[ImageInfo, str]:
    """Check a DFU package and read the image inside it.

    Returns the image and the name it carries inside the archive.
    """
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
        images = [name for name in names if name.endswith(".bin")]

        if len(images) != 1:
            found = ", ".join(images) or "none"
            raise Refused(
                f"The package holds {len(images)} images ({found}). A Shard "
                "release is the application core alone — a package carrying a "
                "second image would update something this release line has "
                "never claimed to update."
            )

        if "manifest.json" in names:
            manifest = json.loads(archive.read("manifest.json"))
            kinds = sorted({entry.get("type") for entry in manifest.get("files", [])})
            if kinds != ["application"]:
                raise Refused(
                    f"The package manifest declares {kinds}, expected the "
                    "application core alone."
                )

        image = parse_image(archive.read(images[0]))

    if image.version != expected_version:
        raise Refused(
            f"The built image reports {image.image_version}, but this release "
            f"is {expected_version}. Both are derived from the same VERSION "
            "file, so they cannot disagree unless the build used a different "
            "tree than the one being released. This fork has already had a "
            "build whose image said one version while the device reported "
            "another; the release stops here rather than repeating it."
        )

    return image, images[0]


def render_manifest(
    *,
    version: str,
    tag: str,
    commit: str,
    built_at: str,
    ncs: str,
    container: str,
    image: ImageInfo,
    image_name: str,
    files: list[tuple[str, str]],
) -> str:
    """The archival record that ships beside the package.

    §3 asks a manifest to say what the artefact is, where it came from, and
    **what was proven and what was not**. That last part is why this is written
    by the build rather than afterwards from memory: a CI run establishes that
    the firmware builds and that its partitions did not move, and establishes
    nothing whatever about hardware. Saying so plainly is the difference between
    a record and an advertisement.
    """
    listed = "\n".join(f"| `{name}` | `{digest}` |" for name, digest in files)
    archive_sha = files[0][1]

    return f"""# Shard CV 1 — firmware {version}

Application core only, built from this fork by
`.github/workflows/shard_release_candidate.yml`. This file was generated by the
same run that produced the package beside it, and every hash below was read from
the files attached to this release.

## What this is

| | |
|---|---|
| Version | `{version}` |
| Image version | `{image.image_version}` |
| Tag | `{tag}` |
| Commit | `{commit}` |
| Built (UTC) | `{built_at}` |
| Toolchain | nRF Connect SDK `{ncs}`, sysbuild, MCUboot |
| Container | `{container}` |
| Signature | {image.signature} |
| Signed image | `{image_name}`, {image.size:,} bytes |

## The files in this release

| File | SHA-256 |
|---|---|
{listed}

`SHA256SUMS` lists these same files and is not listed itself: a file cannot
carry its own hash. Check a download with `sha256sum -c SHA256SUMS`.

## Three hashes, three questions

| Hash | SHA-256 | Answers |
|---|---|---|
| Archive | `{archive_sha}` | is this the same file |
| Signed image | `{image.image_sha256}` | is this the same signed image |
| Payload (image TLV) | `{image.payload_sha256}` | is this the same firmware |

**Only the payload hash survives a rebuild.** MCUboot signs with RSA-PSS, whose
salt is random, and the DFU manifest inside the package records the time it was
built. Two builds of byte-identical firmware therefore differ in their image and
archive hashes while the payload hash stays the same.

Do not use the archive or image hash to claim two builds contain the same
firmware. They cannot answer that, and the answer would be wrong in the
direction that matters: two honest rebuilds look different, so the inequality
would read as tampering when it is only a new salt.

## What was proven, and what was not

Established by the run that produced this file:

- The firmware builds from commit `{commit}` with the toolchain named above.
- The persistent partitions are where shipped hardware has them —
  `settings_storage` at `0xF8000`, `littlefs_storage` at `0xFA000` — read from
  the **generated** partition table rather than from `pm_static.yml`.
- The image reports `{image.image_version}`, which matches the VERSION file this
  release is named after.

**Not established, and therefore not claimed:**

- **The run that built this artefact did not put it on a device.** No update was
  attempted and nothing here says a Shard can take it. SHARD_RELEASES.md §2 is
  explicit that a tag means released rather than built, and that acceptance on
  hardware is what earns it.
- Nothing about recording, BLE transport, audio, battery behaviour or haptics
  was exercised. A green build is a statement about compilation and layout.

Whoever publishes this release is stating that the hardware acceptance in §5 was
carried out, on a named device, against **these** bytes.
"""


def write_release(
    *,
    package: Path,
    out: Path,
    version: str,
    tag: str,
    commit: str,
    built_at: str,
    ncs: str,
    container: str,
) -> list[Path]:
    """Assemble the three files, reading every hash back out of them."""
    out.mkdir(parents=True, exist_ok=True)
    asset = out / ASSET_TEMPLATE.format(version=version)

    try:
        # Not a copy. The build package holds both cores; this is where it
        # becomes the one-image package §3 describes.
        write_app_core_package(package, asset)
    except Refused:
        asset.unlink(missing_ok=True)
        raise

    try:
        # Read from the copy that will be uploaded, not from the build output it
        # came from. Same bytes either way — but "the hash of the file we
        # published" is a claim worth being able to make literally.
        image, image_name = read_package(asset, version)
    except Refused:
        # A refused package must not be left sitting in a directory whose whole
        # purpose is "the files to upload", under the exact name a real release
        # asset has. That confusion is what §5 means by never publishing an RC.
        asset.unlink(missing_ok=True)
        raise

    archive_sha = sha256_file(asset)

    manifest = out / MANIFEST_NAME
    manifest.write_text(
        render_manifest(
            version=version,
            tag=tag,
            commit=commit,
            built_at=built_at,
            ncs=ncs,
            container=container,
            image=image,
            image_name=image_name,
            files=[(asset.name, archive_sha)],
        ),
        encoding="utf-8",
    )

    # Written last, over the finished files, in the format `sha256sum` reads.
    sums = out / SUMS_NAME
    sums.write_text(
        "".join(f"{sha256_file(path)}  {path.name}\n" for path in (asset, manifest)),
        encoding="utf-8",
    )

    return [asset, manifest, sums]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Assemble a Shard release.")
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--built-at", required=True)
    parser.add_argument("--ncs", required=True)
    parser.add_argument("--container", required=True)
    args = parser.parse_args(argv[1:])

    try:
        written = write_release(
            package=args.package,
            out=args.out,
            version=args.version,
            tag=args.tag,
            commit=args.commit,
            built_at=args.built_at,
            ncs=args.ncs,
            container=args.container,
        )
    except Refused as refusal:
        print(f"Refusing to assemble a release: {refusal}")
        return 1

    print("The release is these three files:")
    for path in written:
        print(f"  {path}  ({path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
