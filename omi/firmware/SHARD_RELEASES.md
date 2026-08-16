# Shard — Release Guide

Versioned firmware builds for **Orb**, produced in this fork and consumed by the
Orb app as a bundled asset.

This is a **second, parallel release track** alongside the Omi one described in
[`AGENTS.md`](./AGENTS.md). It exists because the two answer different
questions: an Omi release tells the Omi backend what to offer Omi users; a
Shard release is the archival record of the exact bytes an Orb build
carries.

**Nothing here is published yet.** See [Status](#status).

---

## 1. Product identity

| Field | Stock Omi | Shard |
|---|---|---|
| `CONFIG_BT_DEVICE_NAME` | `Omi` | `Shard` |
| `CONFIG_BT_DIS_MODEL` | `Omi CV 1` | `Shard CV 1` |
| `CONFIG_BT_DIS_FW_REV_STR` | `3.0.21` | `0.0.2` |

The version restarts at `0.0.x` deliberately. It is not a continuation of the
Omi version line — it is a different product identity with its own history, and
pretending otherwise would make `3.0.21` and `0.0.2` comparable when they are
not.

### The persistent partitions are pinned, and their addresses are a contract

```
settings_storage   0xF8000  0x2000
littlefs_storage   0xFA000  0x6000
```

Both are pinned in `boards/omi/pm_static.yml`. **The values are the ones already
on shipped hardware, not the ones a fresh build would choose.**

Upstream leaves both to the partition manager with the identical constraint —
`before: [tfm_storage, end]` in `pm.yml.settings` and `pm.yml.file_system` — and
**no ordering between them**. Two placements are therefore equally valid, and
which appears depends on the order the fragments happen to be collected in. That
is not theoretical: a Shard already in the field was built with `settings` first,
and a later build of the same source produced `littlefs` first, moving
`settings_storage` from `0xF8000` to `0xFC000`.

A firmware update writes only the application slot. If these addresses move, the
new firmware looks for its settings where nothing ever wrote them — the device
loses its clock, its microphone gain and its dim ratio, and there is no cable to
this hardware to put them back.

`littlefs_storage` is pinned as well even though nothing mounts it: its
placement is what decides where `settings_storage` lands.

**Changing either address needs a planned storage migration and a product
decision, not a rebuild.**

Verified twice over: `pm_static.yml` pins them, and
`scripts/ci/partition_gate.py` reads the **generated** `partitions.yml` and
fails if they are not exactly where they belong. Trusting a file to have had an
effect is not the same as seeing the effect. Run it after any firmware build:

```
python3 scripts/ci/partition_gate.py v2.9.0/build/partitions.yml
```

### `VERSION` is the only source of truth

One file decides every version a Shard reports or carries:

```
omi/firmware/omi/VERSION
    ├─ MCUBOOT_IMGTOOL_SIGN_VERSION  →  image header      0.0.2+0
    ├─ the DFU manifest              →  version_MCUBOOT   0.0.2+0
    └─ CONFIG_BT_DIS_FW_REV_STR      →  BLE DIS revision  0.0.2
```

The DIS string is **derived, not typed**: `omi.conf` sets
`CONFIG_BT_DIS_FW_REV_STR="$(APPVERSION)"`, which Zephyr composes from the
VERSION file in `cmake/modules/version.cmake` and hands to Kconfig in
`cmake/modules/kconfig.cmake`. MCUboot takes the tweak form from the same file.

That closes a drift this fork actually had: the image once said `0.0.1` while
the DIS said `3.0.21`, because the two were maintained by hand and nothing
connected them. A device reported a version describing neither the firmware on
it nor the one that replaced it.

`APPVERSION` rather than the Zephyr default `$(APP_VERSION_TWEAK_STRING)`: the
build number belongs to the bootloader, and what a device says it is running is
the product version.

### The version must go up, every time

The bootloader on shipped devices is built with
`CONFIG_MCUBOOT_DOWNGRADE_PREVENTION=y`, and it **cannot be replaced over the
air**: MCUboot sits at the start of flash with no image index of its own and no
`b0`/`s0`/`s1` arrangement. There is no wired access to this hardware either.

So a release whose MCUboot image version is not higher than the one already on a
device simply cannot be installed there, ever. A release that forgets to raise
`VERSION` is a release that can never reach the devices it was meant for — and
no later fix can rescue it.

**CI refuses instead of reminding.** `.github/workflows/firmware_version_gate.yml`
fails a pull request that changes anything reaching the image and leaves
`VERSION` where the target branch has it.

The contract, in full:

1. `VERSION` is the only source of truth.
2. MCUboot and the BLE DIS derive the same product version from it.
3. A change that reaches the image needs a strictly higher `VERSION`.
4. CI enforces that. It never writes a file, never creates a commit, never picks
   a number.
5. Documentation-only changes need no bump.
6. Orb's app version and the Shard firmware version are independent of each
   other.
7. **A build never modifies `VERSION`.** Nothing mutates the working copy.
8. Whoever changes the firmware raises `VERSION` in the same change,
   deliberately. CI only stops them forgetting.

Two branches may pick the same next number. Once the first merges, the second is
compared with the **merged target branch** — not the merge base — and is asked to
pick again. That is deliberate: otherwise two different images would go into the
world under one version. No number is reserved centrally.

Which paths count as reaching the image is decided in
`scripts/ci/version_gate.py` and tested in `scripts/ci/test_version_gate.py`
(`python3 -m unittest` in that directory, no dependencies).

This is also why Orb's own policy is forward-only, and why an older Orb meeting
a newer Shard asks for an app update rather than trying to roll the device back.

### Identity is a pair, not a model number

`0.0.1` changed the manufacturer and the advertised name and deliberately left
the model and firmware revision alone. A device running it reports `Omi CV 1` /
`3.0.21` — the *stock* strings — and is told apart from a genuine stock pendant
only by `CONFIG_BT_DIS_MANUF`.

Anything that identifies these devices must read model **and** manufacturer.
Changing `CONFIG_BT_DIS_MANUF` would break Orb's ability to recognise devices
already in the field.

### Where the name lives

The device name is in the **scan response** (`bt_sd`), not the advertising
packet (`bt_ad`) — see `src/lib/core/transport.c`.

Legacy advertising allows 31 bytes: flags (3) + a 128-bit service UUID (18)
leaves room for a name of **at most 8 characters** including its 2-byte header.

**`Shard` is five and would fit.** The placement is nevertheless kept, and the
reason is worth writing down because the original one no longer applies: the
move was made for `Shared Omi`, which was ten characters and did not fit. With
a shorter name the constraint is gone and the decision is a judgement — three
spare bytes are not a margin worth spending on a product name, which is exactly
the kind of thing that changes.

What the ceiling costs if it is ever crossed: `bt_le_adv_start()` returns
`-EINVAL`, which this firmware treats as non-fatal and logs as "continuing
without BLE". The device runs, records nothing anybody can fetch, never appears
in a scan, and cannot be recovered over the air — an OTA needs the connection
the missing advertisement prevents. With no serial console that means a J-Link.

Nothing is lost by the placement. The service UUID stays in the advertising
packet, and it is what scanners filter on — Orb's discovery and its
CompanionDeviceManager filter both match on the UUID and never on the name.
Android scans actively for the chooser, so the scan response is read as a
matter of course.

---

## 2. Tag and asset scheme

```
tag:     shard-cv1-v<version>
release: Shard CV1 v<version>
asset:   Shard_CV1_appcore_v<version>.zip
```

For the current build:

```
tag:     shard-cv1-v0.0.2
release: Shard CV1 v0.0.2
asset:   Shard_CV1_appcore_v0.0.2.zip
```

### Why this scheme, verified rather than assumed

The Omi backend must never serve a Shard build to an Omi user. Two
independent mechanisms in `backend/routers/firmware.py` prevent it, and both
were checked against the source rather than assumed:

1. **The tag does not match.** `FIRMWARE_TAG_PATTERN` is
   `^(?:Omi_CV1|Omi_DK2|OmiGlass|OpenGlass|Friend)_v[0-9]+(?:\.[0-9]+){1,2}$`.
   `shard-cv1-v0.0.2` fails it — wrong prefix, wrong separator.
2. **The model does not map.** `_get_device_by_model_number` recognises
   `Omi CV 1`, not `Shard CV 1`, and returns `None` for anything else.

The asset name deliberately **omits the substring `ota`**, which the Omi release
workflow requires and which the app-side lookup keys on. Two reasons to name it
`appcore` instead: it says what the package actually contains, and it cannot be
mistaken for an Omi OTA asset by anything scanning for the conventional name.

---

## 3. What the package contains

**App core only.** No net core.

| | |
|---|---|
| Size | 190,358 bytes |
| SHA-256 (archive) | `c9d04ed80cb785a9454ae087684cccc6967b81beb443e9a454b8f4b96b75bc4d` |
| SHA-256 (image) | `31af0c523672c088ca8c3b9d9e6d9a1d1cec7681866e083c61f9e1aa25fef24e` |
| Image version | `0.0.2+0` |
| Toolchain | NCS 2.9.0, sysbuild, MCUboot `OVERWRITE_ONLY` |

### The binding rule

> **The asset attached to a Shard release and the asset bundled in the Orb
> app must be byte-for-byte identical.**

Orb records both hashes in `app/lib/devices/firmware/shard_firmware.dart`
and verifies the archive hash before a single byte reaches a device. An Orb test
reads the shipped package from disk and hashes it, so the two cannot drift apart
without the Orb suite failing.

Both hashes are kept because they answer different questions. The archive hash
changes when the package is repacked; the image hash does not. One alone would
make "the same firmware" either impossible or meaningless to state.

---

## 4. Release body

The Omi releases carry a `KEY_VALUE` body that `backend/routers/firmware.py`
parses. **A Shard release must not carry one.** It is not served to
anything, and a body in that format would invite a future reader to assume it
is.

Proposed body for `shard-cv1-v0.0.2`:

```markdown
Shard CV 1 — firmware 0.0.2

The first Shard build. App core only, from NCS 2.9.0 with sysbuild and MCUboot.

What it changes against the build this fork carried before:
- BLE device name is `Shard`, carried in the scan response rather than the
  advertising packet.
- DIS model number is `Shard CV 1`.
- DIS firmware revision is `0.0.2`, and it is now the *only* visible version.
  The previous build reported two different numbers: `0.0.1` in the image and
  `3.0.21` over the Device Information Service, the latter inherited from stock
  Omi and never maintained.

`0.0.1` never reported a version of its own, so Orb recognises devices running
it by their manufacturer rather than by a version number. Orb installs this
build over the air onto both a stock `Omi CV 1` / `Based Hardware` pendant and
an `Omi CV 1` / `Unicorn Production` one. From here on, `0.0.2` is a revision a
later release can recognise directly.

This build is consumed by the Orb app as a bundled asset. It is not served by
the Omi firmware endpoint and is not offered to Omi users: the tag does not
match `FIRMWARE_TAG_PATTERN` and the model number does not map to a known
device.

Installing this build changes what the device identifies itself as. A device
running it is no longer recognised by the Omi app as an Omi CV 1.

SHA-256 (archive) c9d04ed80cb785a9454ae087684cccc6967b81beb443e9a454b8f4b96b75bc4d
SHA-256 (image)   31af0c523672c088ca8c3b9d9e6d9a1d1cec7681866e083c61f9e1aa25fef24e
```

---

## 5. Publishing

Not via `firmware_release.yml`. That workflow names the asset `Omi_CV1_OTA_v…`
and publishes an `Omi_CV1_v…` release with a `KEY_VALUE` body — all three of
which are exactly what a Shard release must not do.

The steps, when a release is authorised:

1. Confirm the working tree matches the build: `omi.conf`, `VERSION` and
   `src/lib/core/transport.c`.
2. Confirm the archive's SHA-256 matches the value above **and** the value in
   Orb's firmware registry.
3. Create the annotated tag `shard-cv1-v0.0.2`.
4. Create the GitHub release from that tag with the body in section 4.
5. Attach `Shard_CV1_appcore_v0.0.2.zip`.

---

## Status

Prepared, **not published**.

- No tag has been created.
- No GitHub release exists.
- No asset has been uploaded.
- The firmware changes are in the working tree and are **not committed**.

Changed in this fork for 0.0.2:

```
M  omi/firmware/omi/omi.conf                    device name, model, version
M  omi/firmware/omi/VERSION                     image version
M  omi/firmware/omi/src/lib/core/transport.c    name in the scan response
M  omi/firmware/AGENTS.md                       pointer to this file
?  omi/firmware/SHARD_RELEASES.md               this file
```

The build writes `omi/firmware/omi/prj.conf` as a copy of `omi.conf`. It is a
build artefact and is not part of the change.

No device has yet received this build over the air.
