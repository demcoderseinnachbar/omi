# Firmware (Omi CV1) — Agent Guide

Component guide for `omi/firmware/`. General engineering rules: root `AGENTS.md`.

## Release Workflow

Firmware releases are manual via `.github/workflows/firmware_release.yml`:

1. Bump `CONFIG_BT_DIS_FW_REV_STR` in `omi/firmware/omi/omi.conf` first.
2. `gh workflow run firmware_release.yml -f publish=publish -f changelog="..." -f minimum_app_version_code=...` (omit `publish` for a build-only QA run).
3. The workflow builds via Docker (NCS 2.9.0 sysbuild + MCUboot), names the OTA asset `Omi_CV1_OTA_v<ver>.zip` (the "ota" substring is required), and publishes a `Omi_CV1_v<ver>` GitHub Release with the `KEY_VALUE` body that `backend/routers/firmware.py` serves.

Build logic lives in `omi/firmware/scripts/ci/`.

## Shard (Orb)

This fork also builds a **second product identity**, `Shard CV 1`, consumed
by the Orb app. It has its own version line starting at `0.0.x`, its own tag and
asset scheme, and is deliberately invisible to the Omi firmware endpoint.

Read [`SHARD_RELEASES.md`](./SHARD_RELEASES.md) before touching
`omi.conf`, `VERSION` or `src/lib/core/transport.c`.

**It is also the source of truth for the Shard release process** — versioning,
tagging, publishing and verification. **A GitHub release in this fork is the
only official archive of a published Shard firmware**; there is no second one
and no archiving step after it. Do not restate the process here or elsewhere;
change it there.

**Shard devices are updated over the air and only over the air.** There is no
wired access to this hardware, and no product path may assume one. What follows
from that is not optional:

- **The bootloader is fixed.** MCUboot sits at the start of flash with no image
  index of its own and no `b0`/`s0`/`s1` arrangement
  (`SB_CONFIG_SECURE_BOOT_APPCORE` is unset), so no DFU package can replace it.
  `CONFIG_BOOT_UPGRADE_ONLY=y` and `CONFIG_MCUBOOT_DOWNGRADE_PREVENTION=y` in
  `bootloader/mcuboot/mcuboot.conf` are therefore **permanent** on devices
  already in the field.
- **The persistent partition addresses are a compatibility contract.**
  `settings_storage` at `0xF8000/0x2000` and `littlefs_storage` at
  `0xFA000/0x6000`, pinned in `boards/omi/pm_static.yml`. Upstream leaves both to
  the partition manager with the same constraint and no ordering between them,
  so an unpinned build can swap them — which already happened. An update writes
  only the application slot, so a moved `settings_storage` silently costs a
  device its stored settings, with no cable to put them back. Never change these
  without a planned migration. `scripts/ci/partition_gate.py` checks the
  generated `partitions.yml` after a build, not just the pinning file.
- **`omi/firmware/omi/VERSION` is the only version there is.** MCUboot, the DFU
  manifest and the BLE DIS revision are all derived from it, never typed. The
  DIS string comes from a `default "$(APPVERSION)"` on `BT_DIS_FW_REV_STR` in
  **`omi/firmware/omi/Kconfig`**, before `source "Kconfig.zephyr"`; MCUboot takes
  the tweak form from the same file through an untouched Zephyr default. **It
  cannot go in `omi.conf`** — Kconfig expands `$(...)` only while parsing Kconfig
  files, so a `.conf` fragment assigns the literal text and a device advertises
  `$(APPVERSION)` as its firmware version. That was tried and caught before it
  shipped. Do not reintroduce a second place to maintain, and do not move it
  back.
- **Shard image versions only ever go up, and CI enforces it.** A release whose
  image version is not higher than its predecessor's cannot be installed on a
  device running that predecessor — the bootloader refuses it and nothing can
  undo that. Any change reaching the image needs a higher `VERSION` in the same
  commit; `firmware_version_gate.yml` fails the PR otherwise. It only refuses —
  no hook writes files, no build touches `VERSION`.

Two more rules that are easy to break by accident:

- **The device name lives in the scan response, not the advertising packet.**
  Legacy advertising leaves room for eight name characters after flags and a
  128-bit UUID. `Shard` is five and would fit; the placement is kept anyway,
  because three spare bytes are no margin for something as changeable as a
  product name. Cross the ceiling and `bt_le_adv_start()` returns `-EINVAL`,
  which this firmware logs and continues past — leaving a device that never
  advertises, cannot be found, and cannot be recovered over the air.
- **A Shard release must not use the `Omi_CV1_v…` tag or an asset name
  containing `ota`.** Both are what makes the Omi backend serve a build to Omi
  users.

## Formatting

C/C++ files: `clang-format -i <files>` (the repo pre-commit hook covers this).
