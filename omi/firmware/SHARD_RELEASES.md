# Shard — Release Guide

Versioned firmware builds for **Orb**, produced in this fork and consumed by the
Orb app as a bundled asset.

This is a **second, parallel release track** alongside the Omi one described in
[`AGENTS.md`](./AGENTS.md). It exists because the two answer different
questions: an Omi release tells the Omi backend what to offer Omi users; a
Shard release is the archival record of the exact bytes an Orb build
carries.

**The current release is `0.0.3`.** It is accepted on hardware and tagged; the
GitHub release and the archival copy are still outstanding. See
[Status](#status).

---

## 1. Product identity

| Field | Stock Omi | Shard |
|---|---|---|
| `CONFIG_BT_DEVICE_NAME` | `Omi` | `Shard` |
| `CONFIG_BT_DIS_MODEL` | `Omi CV 1` | `Shard CV 1` |
| `CONFIG_BT_DIS_FW_REV_STR` | `3.0.21` | `0.0.3` |

The version restarts at `0.0.x` deliberately. It is not a continuation of the
Omi version line — it is a different product identity with its own history, and
pretending otherwise would make `3.0.21` and `0.0.3` comparable when they are
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
omi/firmware/omi/VERSION            (0.0.3, VERSION_TWEAK 0)
    ├─ MCUBOOT_IMGTOOL_SIGN_VERSION  →  image header      0.0.3+0
    ├─ the DFU manifest              →  version_MCUBOOT   0.0.3+0
    └─ CONFIG_BT_DIS_FW_REV_STR      →  BLE DIS revision  0.0.3
```

Both derivations are **defaults**, and neither value is typed anywhere.

**The DIS string comes from `omi/firmware/omi/Kconfig`**, which sets
`config BT_DIS_FW_REV_STR` to `default "$(APPVERSION)"` immediately before
`source "Kconfig.zephyr"`. `APPVERSION` is Zephyr's expansion of the VERSION
file, composed in `cmake/modules/version.cmake` and handed to Kconfig in
`cmake/modules/kconfig.cmake`. The position matters: the first default parsed
for a symbol wins, so the application's default has to be read before
`Kconfig.zephyr` brings its own.

> **It cannot live in `omi.conf`, and putting it there was a real defect.**
> Kconfig expands `$(...)` while parsing **Kconfig files**; a `.conf` fragment
> assigns a literal string. An earlier attempt wrote
> `CONFIG_BT_DIS_FW_REV_STR="$(APPVERSION)"` into `omi.conf`, and the generated
> `.config` carried those thirteen characters verbatim — a device would have
> advertised `$(APPVERSION)` as its firmware version. It was caught by reading
> the generated `.config` before the build finished, never reached hardware, and
> `omi.conf` now carries only a comment saying where the value really comes
> from.

**The image version comes from an untouched Zephyr default.** Nothing in this
fork sets `CONFIG_MCUBOOT_IMGTOOL_SIGN_VERSION`;
`zephyr/modules/Kconfig.mcuboot` defaults it to `$(APP_VERSION_TWEAK_STRING)`
whenever `VERSION_MAJOR` is non-empty, which is the same VERSION file in its
tweak form. That is where the `+0` comes from, and why the image and the DFU
manifest both read `0.0.3+0` while the DIS reads `0.0.3`.

The two forms differ on purpose: the build number belongs to the bootloader, and
what a device says it is running is the product version.

That closes a drift this fork actually had: the image once said `0.0.1` while
the DIS said `3.0.21`, because the two were maintained by hand and nothing
connected them. A device reported a version describing neither the firmware on
it nor the one that replaced it.

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

For the current release:

```
tag:     shard-cv1-v0.0.3
release: Shard CV1 v0.0.3
asset:   Shard_CV1_appcore_v0.0.3.zip
```

### What a tag means

**A firmware tag means released, not frozen.** It is created only after the
concrete release artefact has been accepted on hardware — not when the source
looks finished, and not when the build is green.

The reason is the project's own history. Twice an artefact looked complete
and the hardware said otherwise: a busy device-information read silently
stopped the firmware check from ever running, and the partition manager moved
the settings region between two builds of the same source. Neither showed up in
a build log. A tag that meant "source frozen" would be read as "released" a
year later by somebody who was not here.

So, in full:

- A **release candidate gets no tag.** Its identity is its artefact hashes.
- The tag points at **exactly the commit the accepted artefact was built from**.
- A tag is **never moved** to another commit afterwards.
- A version number that has been tagged is **never reused for different firmware
  bytes**. If the bytes change, the version changes.
- Development commits are not tagged at all.

### Why this scheme, verified rather than assumed

The Omi backend must never serve a Shard build to an Omi user. Two
independent mechanisms in `backend/routers/firmware.py` prevent it, and both
were checked against the source rather than assumed:

1. **The tag does not match.** `FIRMWARE_TAG_PATTERN` is
   `^(?:Omi_CV1|Omi_DK2|OmiGlass|OpenGlass|Friend)_v[0-9]+(?:\.[0-9]+){1,2}$`.
   `shard-cv1-v0.0.3` fails it — wrong prefix, wrong separator.
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
| Asset | `Shard_CV1_appcore_v0.0.3.zip` |
| Size | 190,352 bytes |
| Image version | `0.0.3+0` |
| Signed image size | 249,020 bytes |
| Toolchain | NCS 2.9.0, sysbuild, MCUboot `OVERWRITE_ONLY` |
| Signature | RSA-2048, `bootloader/mcuboot/root-rsa-2048.pem`, unchanged from upstream |

### Three hashes, three questions

| Hash | SHA-256 | Answers |
|---|---|---|
| Archive | `7d8c5a46188f1f46e5c683aeacd119a2eeb7bc998e471286e280e489b4bb2d95` | is this the same file |
| Signed image | `5f0e13b3f426acf1a4d2a0804d7959ce15f31120fd020300c413021f71ca46c8` | is this the same signed image |
| **Payload (image TLV)** | `71165e2e507372da9cd148e762b7a2e2d3e9d9f5afa658081c5eed195b1f6a42` | **is this the same firmware** |

**Only the payload hash survives a rebuild.** MCUboot signs with RSA-PSS, whose
salt is random, so two builds of byte-identical firmware carry different
signatures and therefore different image *and* archive hashes. Three builds of
the `0.0.3` source demonstrated exactly that: identical payload to the byte,
three different image hashes. Anyone reproducing a Shard build compares the
payload hash — the SHA-256 MCUboot records in the image's own TLV trailer, taken
over the payload alone — and nothing else.

The archive hash identifies **this** artefact, and it is the one to archive
against and the one Orb checks.

### The binding rule

> **The asset attached to a Shard release and the asset bundled in the Orb
> app must be byte-for-byte identical.**

Orb records the archive and image hashes in
`app/lib/devices/firmware/shard_firmware.dart` and verifies the archive hash
before a single byte reaches a device. An Orb test reads the shipped package
from disk and hashes it, so the two cannot drift apart without the Orb suite
failing. Orb does not carry the payload hash: it verifies the file it is about
to send and then takes the device's own word for what it runs afterwards.

---

## 4. Release body

The Omi releases carry a `KEY_VALUE` body that `backend/routers/firmware.py`
parses. **A Shard release must not carry one.** It is not served to
anything, and a body in that format would invite a future reader to assume it
is.

Body for `shard-cv1-v0.0.3`:

```markdown
Shard CV 1 — firmware 0.0.3

App core only, from NCS 2.9.0 with sysbuild and MCUboot. Accepted on hardware:
a Shard running 0.0.2 was updated to this build over the air by Orb, without
anybody asking it to, and reported `0.0.3` afterwards.

What it changes against 0.0.2:

- The version a device reports is derived, not typed. `omi/Kconfig` sets
  `BT_DIS_FW_REV_STR` to `$(APPVERSION)`, composed by Zephyr from the VERSION
  file. In 0.0.2 the DIS string was maintained by hand beside the image version
  and the two could drift.
- The persistent partitions are pinned. `settings_storage` at `0xF8000` and
  `littlefs_storage` at `0xFA000` are written down in
  `boards/omi/pm_static.yml` instead of being chosen by the partition manager.
  Upstream constrains both identically and orders neither, so two placements
  were equally valid and one build of the same source moved `settings_storage`
  to `0xFC000`. A firmware update writes only the application slot; a device
  whose settings region moves loses its clock, its microphone gain and its dim
  ratio, and there is no cable to this hardware to put them back.
- CI refuses instead of reminding: a change reaching the image without a higher
  VERSION fails, and the generated partition table is checked against the
  pinned addresses rather than trusted to have been read.

No functional change to recording, BLE transport or audio.

This build is consumed by the Orb app as a bundled asset. It is not served by
the Omi firmware endpoint and is not offered to Omi users: the tag does not
match `FIRMWARE_TAG_PATTERN` and the model number does not map to a known
device.

SHA-256 (archive) 7d8c5a46188f1f46e5c683aeacd119a2eeb7bc998e471286e280e489b4bb2d95
SHA-256 (image)   5f0e13b3f426acf1a4d2a0804d7959ce15f31120fd020300c413021f71ca46c8
SHA-256 (payload) 71165e2e507372da9cd148e762b7a2e2d3e9d9f5afa658081c5eed195b1f6a42

Only the payload hash survives a rebuild — MCUboot signs with RSA-PSS and its
salt is random.
```

The note about identity that `0.0.2` carried — that installing it changes what
the device calls itself, and that the Omi app no longer recognises it — belongs
to that release and is not repeated here. `0.0.3` replaces a Shard with a
Shard.

---

## 5. Publishing

Not via `firmware_release.yml`. That workflow names the asset `Omi_CV1_OTA_v…`
and publishes an `Omi_CV1_v…` release with a `KEY_VALUE` body — all three of
which are exactly what a Shard release must not do.

The steps, when a release is authorised — written for `0.0.3`, and the same
shape for every version after it:

1. Confirm the artefact has been **accepted on hardware**. A tag means released;
   a release candidate gets none.
2. Confirm the working tree is clean at the commit the artefact was built from.
3. Confirm the archive's SHA-256 matches the value in section 3 **and** the
   value in Orb's firmware registry.
4. Create the annotated tag `shard-cv1-v0.0.3` **on that commit explicitly**,
   not on `HEAD`. Later commits on the branch are not part of the release.
5. Verify the dereferenced tag: `git rev-parse shard-cv1-v0.0.3^{commit}` must
   equal the build commit.
6. Push the branch and the tag. No force, no other tags.
7. Create the GitHub release from that tag with the body in section 4, named
   `Shard CV1 v0.0.3`.
8. Attach `Shard_CV1_appcore_v0.0.3.zip` — the accepted artefact itself. Never
   a rebuild: a rebuild produces a different signature and therefore a different
   archive hash, and the hash recorded here would no longer identify what was
   attached.
9. Archive the artefact, its manifest and its `SHA256SUMS`.

---

## Status

### 0.0.3 — **released, archive pending**

Not "complete". The process in section 5 has nine steps and two of them are
outstanding, so the release is not finished, and saying otherwise would leave a
later reader believing an artefact is archived that is not.

| Step | State |
|---|---|
| Accepted on hardware | **done** |
| Committed | **done** — `935ff3dbaff98d95c0922d572aa5f32d0e4ca46e` |
| Annotated tag `shard-cv1-v0.0.3` | **done**, pointing exactly at `935ff3db…` |
| Tag pushed | **done** — verified remotely, `refs/tags/shard-cv1-v0.0.3^{}` = `935ff3db…` |
| GitHub release `Shard CV1 v0.0.3` | **outstanding** |
| Asset uploaded | **outstanding** |
| Archived | **outstanding** |

The tag is on the build commit and not on the branch head. Later commits — this
document among them — sit after it on `feat/shard-recording-hold` and are not
part of the release. **The tag is never moved to include them.**

The firmware for `0.0.3` is frozen. Anything further changes a version number
first.

#### Hardware acceptance

`0.0.2` → `0.0.3` over Orb's automatic OTA path, on a Samsung Galaxy A25
(SM-A256B), started by opening the app. Orb read the device, decided
`shouldUpdate` on its own, uploaded once, waited out one reboot, reconnected and
verified against a **fresh** device-information read — model, manufacturer and
firmware revision all had to match before it reported success. The device
reported `0.0.3` afterwards, and the clock sync that follows succeeded, which
means `settings_storage` is where it was pinned and is writable.

What was **not** measured, and is therefore not claimed:

- **`mic_gain` and `dim_ratio` were not read.** No product or diagnostic path
  exposes them and none was built for the test. That they survived is a
  reasonable expectation from the partition addresses holding, not an
  observation.
- **The battery gate is unverified on hardware.** The run happened with the
  pendant on external power. Still open: an OTA below and above the 60 %
  threshold without external power, and a device that will not report its charge
  at all. Testable again with the next release, not on this device — it now runs
  the expected revision and has nothing to receive.
- **The LED was not observed.**

Separately open and unaffected by this release: the pendant's **haptic feedback
is not perceptible**, and **SMP over BLE is unauthenticated**
(`CONFIG_MCUMGR_TRANSPORT_BT_PERM_RW=y`) — the image signature is the trust
boundary, not the transport.

### 0.0.2

Superseded by `0.0.3`. It was never tagged and never published: the tag
convention was settled after it shipped to hardware, and by then `0.0.3` was the
next release rather than a retrospective one. Devices provisioned with it are
recognised by the release line in Orb's firmware registry.

### A note on `prj.conf`

The build writes `omi/firmware/omi/prj.conf` as a copy of `omi.conf`. It is a
build artefact, is git-ignored, and is never part of a change.
