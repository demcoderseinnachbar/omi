# Shard — Release Guide

Versioned firmware builds for **Orb**, produced in this fork and consumed by the
Orb app as a bundled asset.

This is a **second, parallel release track** alongside the Omi one described in
[`AGENTS.md`](./AGENTS.md). It exists because the two answer different
questions: an Omi release tells the Omi backend what to offer Omi users; a
Shard release is the archival record of the exact bytes an Orb build
carries.

**This file is the source of truth for the Shard release process.** Other
documents point here rather than restating it, so that there is one place to
change when the process changes.

---

## 0. The short version

> **A GitHub release in this fork is the only official archive of a published
> Shard firmware. There is no second one.**

No separate archive, no mirrored copy on a drive or a file share, and no
archiving step after the release is published. A release that is published and
verified is finished. Anything kept elsewhere is a working copy, and a working
copy is not a record — it is something that can quietly disagree with the
record.

The ten questions this file exists to answer:

| | Question | Answer | Detail |
|---|---|---|---|
| 1 | When must the version go up? | When a change reaches the image. Documentation-only changes do not. CI refuses, it does not remind. | [§1](#the-version-must-go-up-every-time) |
| 2 | When may a tag be created? | Only after the concrete artefact has been **accepted on hardware**. A candidate gets no tag. | [§2](#what-a-tag-means) |
| 3 | What must the tag point at? | Exactly the commit the accepted artefact was built from — never the branch head. Tags are never moved. | [§2](#what-a-tag-means) |
| 4 | When may the GitHub release be published? | From the existing tag, after it is pushed and its dereferenced target verified. | [§5](#5-publishing) |
| 5 | Which files make a complete release? | Exactly three: the package, `RELEASE_MANIFEST.md`, `SHA256SUMS`. | [§3](#the-release-is-three-files) |
| 6 | What is Orb's bundled asset? | The delivery copy its automatic update path needs — **not** an archive. | [§3](#what-orbs-asset-is-and-what-it-is-not) |
| 7 | Which hash answers which question? | Archive hash: is this the same file. Image hash: the same signed image. Payload hash: the same firmware. | [§3](#three-hashes-three-questions) |
| 8 | How is a release verified after upload? | Download it back read-only, `sha256sum -c SHA256SUMS`, compare Orb's copy byte for byte. | [§5](#verifying-a-release-after-upload) |
| 9 | What is the single source of truth? | The GitHub release. | this section |
| 10 | How is an RC or a rebuild kept out? | Never trust a filename. Full path, hash before upload, hash the download after. | [§5](#never-publish-an-rc-or-a-rebuild) |

**The current release is `0.0.7`.** See [Status](#status).

---

## 1. Product identity

| Field | Stock Omi | Shard |
|---|---|---|
| `CONFIG_BT_DEVICE_NAME` | `Omi` | `Shard` |
| `CONFIG_BT_DIS_MODEL` | `Omi CV 1` | `Shard CV 1` |
| `CONFIG_BT_DIS_FW_REV_STR` | `3.0.21` | derived from `VERSION` (below) |

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

`.github/workflows/firmware_build_check.yml` runs it on every firmware change,
so a moved partition fails the commit that moved it rather than the release that
would have carried it to a device.

### `VERSION` is the only source of truth

One file decides every version a Shard reports or carries:

```
omi/firmware/omi/VERSION            (0.0.6, VERSION_TWEAK 0)
    ├─ MCUBOOT_IMGTOOL_SIGN_VERSION  →  image header      0.0.6+0
    ├─ the DFU manifest              →  version_MCUBOOT   0.0.6+0
    └─ CONFIG_BT_DIS_FW_REV_STR      →  BLE DIS revision  0.0.6
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
manifest both read `0.0.4+0` while the DIS reads `0.0.4`.

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
tag:     shard-cv1-v0.0.6
release: Shard CV1 0.0.6
asset:   Shard_CV1_appcore_v0.0.6.zip
```

Every release title so far reads `Shard CV1 <version>` and not `Shard CV1 v<version>`, which is
what the pattern above asks for. It is written down as it is rather than
corrected: those releases are published, and renaming a published release to match a
document would change the record to fit the description. **The tag and the asset
name — the two a machine reads — follow the pattern exactly.**

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

## 3. What a release contains

### The build package is not the release package

sysbuild builds **both cores** into one DFU package: the application core at
image index 0 and the radio core at index 1, both declared `application` in its
manifest. `SB_CONFIG_NETCORE_APP_UPDATE=y` has always been set and is not
changed for the sake of a release.

**Shard CV 1 0.0.x publishes the application core alone.** 0.0.3 is that shape —
one image, one manifest entry, no radio core — and Orb's uploader has only ever
been proven for the one-image case.

So there is a narrowing between the build and the release, and
`scripts/ci/make_shard_release.py` owns it. It selects the application core by
what the build's own manifest says — index 0, board `omi` — never by counting
files or taking the first `.bin`, and it copies the surviving manifest entry
rather than rebuilding it.

**The radio core is a permitted build input and never a release component.** An
image the release line does not know — a third core, a different board at index
0, two entries at index 0 — **stops the release**. Dropping an unrecognised
image quietly would be a decision about what a Shard release contains, made by
omission; adding one is a decision that belongs here, in writing, before it
reaches a device that has no cable.

### The release is three files

A published release carries exactly these, and together they *are* the release:

| File | Answers |
|---|---|
| `Shard_CV1_appcore_v<version>.zip` | the firmware itself |
| `RELEASE_MANIFEST.md` | what it is, where it came from, what was proven and what was not |
| `SHA256SUMS` | whether a download arrived intact |

`SHA256SUMS` lists at minimum the package and the manifest, in the format
`sha256sum` writes and reads, so that anybody who downloads a release can check
it with a standard tool and no instructions:

```
sha256sum -c SHA256SUMS
```

or, on Windows without a POSIX shell:

```powershell
Get-FileHash Shard_CV1_appcore_v<version>.zip, RELEASE_MANIFEST.md -Algorithm SHA256 |
  Format-List Path, Hash
```

It does not list itself, and nothing else lists it either: a file cannot contain
its own hash, and the manifest cannot carry it because `SHA256SUMS` already
carries the manifest's. The chain ends at the release page, which is the trusted
point — that is what "single source of truth" buys.

### What Orb's asset is, and what it is not

Orb bundles the same package under `app/assets/firmware/`. **That copy is not a
second archive.** It is the delivery copy Orb's automatic update path needs at
runtime, because Orb speaks to no server about firmware and the bytes have to be
in the app.

| | |
|---|---|
| **GitHub release** | the official archive and the source of truth |
| **Orb's bundled asset** | the delivery copy for the automatic OTA path |

For a published version the two must be **byte-for-byte identical**, and the
archive SHA-256 recorded in `app/lib/devices/firmware/shard_firmware.dart` must
equal the one attached to the release. **A difference is a release error, not a
variant** — one of the two is then not the firmware anybody signed off, and
there is no way to tell which from the outside.

**A registry entry may only name an asset whose real bytes are checked by an
automated test.** `app/test/devices/firmware_asset_test.dart` reads the package
from disk, hashes it, and compares with the `archiveSha256` of the entry that
names it — the registry stays the single source of truth for the value, and the
test never restates it. Nothing else in Orb can tell the registry from the
artefact: every other check compares a constant with a literal, both written by
the same hand at the same moment, and passes just as happily when the package
beside it is a rebuild, a candidate, or the previous version under a new name.

**And the other way round: every firmware package under `app/assets/firmware/`
must belong to a registry entry.** A package stays in the bundle when a version
moves on unless somebody deletes it — `0.0.3` did, for as long as `0.0.4` was
already the entry. Nothing loads it, so nothing notices: it simply ships inside
the app, indistinguishable in a file list from the one that is real. That is
the confusion §5 warns about, arriving from the other side.

This is written down because it was once only assumed. Until firmware 0.0.4 the
sentence here claimed such a test existed; the test that was pointed at
compared registry constants with each other and read no file at all. The claim
was true of the intent and false of the code for as long as nobody looked.

### What the package contains

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

The archive hash identifies **this** artefact. It is what the release is
recorded under and what Orb verifies before a single byte reaches a device.

Orb carries the archive and image hashes, not the payload hash: it checks the
file it is about to send, and afterwards takes the device's own word for what it
runs. The payload hash is for whoever asks whether two builds are the same
firmware, which is a question about sources rather than about a download.

**Do not use the archive or image hash to claim two builds contain the same
firmware.** They cannot answer that, and stating it that way would be wrong in
the one direction that matters: two honest rebuilds look different, so an
inequality would be read as tampering when it is only a new salt.

### Open: the network core image does not rebuild identically

Four clean builds of the same tree in the pinned container produced **four
different payload hashes for `ipc_radio.bin`**, the network core image. The
application core was identical across all four:

```
omi.signed.bin  payload_sha256=e725f8f1523b413781a72dedd84a23da876a468150edb9804ba88b54892b0316
```

This is not the salt effect described above. That one leaves the payload hash
alone, and the payload hash is exactly what moved.

**Not a release blocker, for a narrow reason:** `dfu_application.zip` carries
both images, but a Shard release is the application core alone —
`write_app_core_package` extracts it, and `read_package` refuses a package
holding a second image. Nothing `ipc_radio.bin` contains reaches a device on
this release line.

Written down because it stops being harmless if the network core is ever
shipped, and because anyone reproducing a build and comparing the whole package
would otherwise read it as a broken build rather than as this. Observed
2026-08-20 while measuring build times; no cause established, nothing attempted.

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

### What CI does, and what it never does

`.github/workflows/shard_release_candidate.yml` does the mechanical half. When
`VERSION` rises on `main` it builds in the pinned container, runs the partition
gate against the generated table, and assembles the three files of §3 into a
**draft release** — every hash read back out of the file that was uploaded, from
that build and no other.

**It stops there, and the reason is §2.** A tag means released, not built, and a
draft carries no tag until somebody publishes it. That is precisely the state
this section requires of a candidate: no tag, identity by hashes. What CI cannot
do is the half that earns the tag — put the bytes on a device and watch what
happens.

So it never publishes, never tags, never writes a version, never touches `main`,
and never decides that a build is a release. The steps below are unchanged; what
changed is that steps 3 and 4 are now performed by a machine that cannot forget
one.

**A draft the branch moves past is marked, never replaced.** If the firmware
changes again while `VERSION` stays where it is, the draft under that number
holds bytes `main` no longer has — and the release page would say nothing about
it at the moment somebody presses publish. So CI retitles it `SUPERSEDED — …`,
puts a warning at the top of its body naming both the commit it was built from
and the one that overtook it, and fails the run.

It does not delete the draft and does not rebuild it. A candidate may be on a
device at that moment, and discarding the artefact somebody is testing is the
worse mistake. The state is resolved by a decision, not by CI: raise `VERSION`,
and a new draft is built for the new number — or delete the old draft if its
build was never wanted.

### The process, end to end

Fifteen steps, written for `<version>` and the same shape every time. Nothing
follows step 15 — **there is no archiving step after the release**, because the
release *is* the archive.

**Build and prove**

1. Develop the firmware change.
2. Raise `VERSION` in the same change, once, deliberately. §1 says when this is
   required; a documentation-only change is not.
3. Push it to `main`. CI builds and runs the gates: `build-cv1.sh`, then
   `partition_gate.py` against the **generated** `partitions.yml`.
   (`version_gate.py` has already refused the pull request if step 2 was
   forgotten.) By hand the same three commands do the same thing.
4. CI assembles the candidate — the three files of §3 — and attaches them to a
   **draft release**. **It gets no tag**: its identity is its hashes, and they
   are in the `RELEASE_MANIFEST.md` attached beside it. Locally, that step is
   `make_shard_release.py`.

   **A candidate run that fails before it drafts anything does not spend the
   version.** The push gate looks for a rise against the commit before it, and
   once `main` has moved on carrying the same `VERSION` that rise is gone — no
   later push can produce that candidate. The version is still owed: nothing
   published it, no tag claims it, and the firmware it names has not changed.

   So the same unpublished `VERSION` is built again, from the fixed pipeline,
   through the **Shard release candidate** workflow's manual run. It takes no
   inputs; the version comes from `omi/firmware/omi/VERSION` as it does for a
   push, and it builds a candidate only when that version is newer than the
   newest published one and unclaimed. A published release or an existing draft
   for it still refuses, exactly as on the automatic path.

   **The version is never raised to get another attempt**, and a candidate is
   never assembled by hand. Both would put a number on firmware nobody built
   that way.
5. Point Orb at exactly this artefact: the package into `app/assets/firmware/`,
   the version, image version and archive hash into the firmware registry.
6. Run Orb's gates — analyzer, tests, and the test that hashes the shipped
   package.
7. Run the controlled hardware acceptance on a named device. Record what it
   proved **and what it did not**.

**Release**

8. Fix the release commit: the commit the accepted artefact was built from. It
   is not a matter of memory — `RELEASE_MANIFEST.md` in the draft names it, and
   that manifest was written by the run that produced the package.
9. Create the annotated tag `shard-cv1-v<version>` **on that commit explicitly**,
   never on `HEAD` — main has usually moved on by now — then verify it:
   `git rev-parse shard-cv1-v<version>^{commit}` must equal the commit the
   manifest names. Push branch and tag — no force, no other tags.
10. Publish the draft: replace the placeholder body with the body from §4 and
    release it. It already carries the right name and the right tag, and
    publishing against a tag that is already pushed uses that tag rather than
    creating a second one.
11. **Attach nothing and replace nothing.** The three files of §3 are already
    there, and they are the ones that were built and accepted. Never swap the
    package for a local copy or a rebuild: a rebuild carries a different
    signature and therefore a different archive hash, and the hash recorded in
    the manifest would stop identifying what is attached.

**Verify what was published**

12. Download the assets back from GitHub, read-only. Not the local copies — the
    published bytes.
13. Run `sha256sum -c SHA256SUMS` against what was downloaded. Both lines must
    read `OK`.
14. Compare Orb's bundled package with the downloaded one **byte for byte**
    (`cmp`), not by name and not by size.
15. Only then: **`RELEASE COMPLETE`**.

Until every step is done the release is not finished, and the status says so.
Rounding up here is how somebody a year from now comes to believe a file exists
that never did.

### Verifying a release after upload

Step 12 to 14 in full, for `0.0.3`:

```bash
gh release download shard-cv1-v0.0.3 --repo demcoderseinnachbar/omi -D verify/
# or, with no gh:
curl -sL -O https://github.com/demcoderseinnachbar/omi/releases/download/shard-cv1-v0.0.3/Shard_CV1_appcore_v0.0.3.zip
cd verify && sha256sum -c SHA256SUMS
cmp Shard_CV1_appcore_v0.0.3.zip ../../Orb/app/assets/firmware/Shard_CV1_appcore_v0.0.3.zip
```

Verifying the local copy proves nothing about the release. What was uploaded is
the only thing anybody else will ever get.

### Never publish an RC or a rebuild

**Release candidates and rebuilds carry the same filename as the release.** This
is not hypothetical — during `0.0.3` a candidate named
`Shard_CV1_appcore_v0.0.3.zip` sat on disk alongside the release with a
different hash and a six-byte size difference. Nothing about the name tells them
apart, and a file picker shows the name.

So, every time:

- Address the file by its **full path**, never by name from a search result.
- **Hash it before uploading** and compare with the manifest.
- **Hash the download afterwards.** That closes the loop the first two cannot:
  it checks what arrived at GitHub, not what was meant to.

A wrong artefact under a right version number cannot be corrected by replacing
it, because the version has already been published for other bytes. It costs a
new version.

---

## Status

### 0.0.7 — **`RELEASE COMPLETE`**

Every step of §5 is done and verified against what was actually published, not
against the local copies. Nothing follows.

| Step | State |
|---|---|
| 1 Firmware change | **done** — `281aecb574`, PR #17 |
| 2 `VERSION` raised to `0.0.7` | **done** — same commit |
| 3 Built by CI from `main` | **done** — merge `cdc718092cf4a85555bcf8dc8d4a590fc649c57a`, run `40672966219` (*Shard release candidate*), success; *Firmware build check* on the same commit, success — `settings_stealth` 6 / 6, `haptic` 19 / 19, partition gate |
| 4 Candidate assembled (draft) | **done** — draft *Shard CV1 0.0.7*, 2026-10-28T10:38:49Z, three files |
| 5 Orb points at exactly this artefact | **done** — Orb `9213c02` on `feat/1.3.6-incognito-focus`, bundled package byte-identical to the published download (`cmp`) |
| 6 Orb's gates | **done** — Orb CI green on that branch, last on `cb9e65a` (run `40692772584`) |
| 7 Accepted on hardware | **done, with limits** — see *The hardware acceptance* |
| 8 Release commit fixed | **done** — `cdc718092cf4a85555bcf8dc8d4a590fc649c57a`, named by the manifest the build itself wrote |
| 9 Annotated tag `shard-cv1-v0.0.7` | **done**, dereferencing to `cdc718092c…` — checked as `^{commit}`, not by the tag object's own id |
| Tag pushed | **done** — verified remotely, `refs/tags/shard-cv1-v0.0.7^{}` = `cdc718092c…` |
| 10 GitHub release `Shard CV1 0.0.7` | **done** — published `2026-10-28T13:50:58Z`, not a draft, not a pre-release, with the approved body verbatim |
| 11 Nothing attached, nothing replaced | **done** — the three assets keep the build's timestamps (2026-10-28T10:38:50Z) |
| `Shard_CV1_appcore_v0.0.7.zip` attached | **done** — verified `4740aed4…` |
| `RELEASE_MANIFEST.md` attached | **done** — verified `663c9315…` |
| `SHA256SUMS` attached | **done** — verified `4f4c50ba…` |
| 12–13 `sha256sum -c SHA256SUMS` on the download | **done** — both `OK`; image `afc72c26…`, `imgtool verify` *Image was correctly validated*, `0.0.7+0` |
| 14 Orb delivery copy identical to the published package | **done** — byte-for-byte, 0 differing bytes |
| 15 | **`RELEASE COMPLETE`** |

Release: https://github.com/demcoderseinnachbar/omi/releases/tag/shard-cv1-v0.0.7

The published files were downloaded back into a fresh directory and hashed
there; the byte comparison against Orb's bundled copy was made on that download.
The tag is on the merge commit the manifest names and not on a branch head.
**The tag is never moved.**

#### The artefact this refers to

| | |
|---|---|
| Product | Shard CV 1 |
| Version | `0.0.7`, image `0.0.7+0` |
| Firmware commit | `cdc718092cf4a85555bcf8dc8d4a590fc649c57a` |
| Tag | `shard-cv1-v0.0.7` |
| Archive | `Shard_CV1_appcore_v0.0.7.zip`, 250,559 bytes |
| Archive SHA-256 | `4740aed48c667f89f10300e868caaf7fe909a72f2dcc227e9fcde4332f3df100` |
| Signed image | `omi.signed.bin`, 249,836 bytes |
| Signed image SHA-256 | `afc72c2614194ec82f1a277827f1316b6a7a8148c23e8548b31d15137c3d1f06` |
| Payload SHA-256 (image TLV) | `21aa37d8ee2c10cd8fe7b39cc5dc4d7f530895a0ef29a936b5d86ee48ed4fb6a` — the same as the local check build below, as expected for the same source |
| Toolchain | nRF Connect SDK `v2.9.0`, sysbuild, MCUboot, RSA-2048 PSS |
| Package contents | `manifest.json` + one image at index 0, board `omi` — **no radio core** |

Checked twice against the bytes downloaded back from the draft, the second
time on 2026-10-28 after the acceptance: `sha256sum -c SHA256SUMS` both `OK`,
image unpacked and hashed, `imgtool verify` against
`bootloader/mcuboot/root-rsa-2048.pem` *Image was correctly validated*,
`0.0.7+0`. The draft's asset timestamps are those of the build
(2026-10-28T10:38:50Z), so nothing has been replaced since.

#### The hardware acceptance

    Manual validation device:
    Samsung Galaxy A25 (SM-A256B)

Serial `RZCXC034X1R`, pendant `D5:D2:EE:26:53:D3` (*Shard · 53D3*),
2026-10-28. Installed **over Orb's own automatic update path** from the bundled
candidate (Orb dev build `63bc3a1`), 0.0.6 → 0.0.7; the device reported `0.0.7`
afterwards, read fresh. Full record: `docs/testing/1.3.6-incognito-a25-abnahme.md`
in the Orb repository.

| | Point | Result |
|---|---|---|
| H0 | Firmware revision reads `0.0.7` | **PASS** |
| H8 | Update 0.0.6 → 0.0.7 over Orb | **PASS** — light normal afterwards; stealth was **not** on before the update, so the retired `omi/stealth` record was not exercised on hardware (covered by `settings_stealth`) |
| H1 / H2 | Stealth on / off | **PASS** |
| H3 | Lost Bluetooth link and reconnect | **PASS** — stealth stays on. A first run that showed it off was traced to three taps on the switch after the reconnect (B1), not to the device |
| H4 | App restart | **PASS** |
| H5 | Device restart ends stealth, normal light, nothing written back | **PASS** |
| H11 | Recording, button, haptics, link-lost alarm, charging | **PASS** |
| H6 | Empty battery | **NOT DONE** — same mechanism as H5 |
| H7 | Second Shard | **NOT EXECUTABLE** — none exists |
| H9 | New app with 0.0.6 | **NOT DONE** — skipped by decision |
| H10 | Old app with 0.0.7 | **NOT DONE** — by decision |

**One finding about Orb, not about this firmware (B3).** The update ran at about
17 % charge: Orb read `0x2A19`, and the Battery Service answers Zephyr's initial
`100` until the firmware's first measurement tick on a link. Fixed in Orb
(`cb9e65a`) — it now decides only on a notification of the open link. The
firmware is unchanged; the 60 % hold is covered by Orb's tests and **not
confirmed on hardware**.

#### What this version changes

One change against `0.0.6`, and nothing else:

- **Stealth lasts for one session of the device.** It is held in RAM only. Every
  boot starts with it off — after switching off, an empty battery, a firmware
  update or any other reset — and a BLE write changes this session and is never
  written to flash. A lost link does not end it; the device does not restart
  for that. The record `0.0.6` left under `omi/stealth` is recognised at load
  and dropped unread: not read, because that would bring back a silence nobody
  chose in this session; not erased, because nothing can read it any more and
  erasing it would be one more flash write at boot on hardware without a cable.
  **The key `omi/stealth` is retired and never to be used again.** Product
  decision of 28 October 2026, ADR-0051 in the Orb repository.

`19B10014` keeps its UUID, its length, its values and its read/write
properties; only its meaning changes, from *stored* to *this session*.
`19B10015`, `OMI_FEATURE_STEALTH`, the status display's own logic, haptics, the
button, the microphone, `dim_ratio` and `mic_gain` are unchanged.

| File | Change |
|---|---|
| `omi/src/settings.c` | `app_settings_set_stealth()` replaces `app_settings_save_stealth()` and writes RAM only; the `stealth` branch of the load handler recognises and ignores the retired key |
| `omi/src/lib/core/settings.h` | the declaration and its documentation |
| `omi/src/lib/core/transport.c` | the write handler calls the new function; the save-failure branch is gone because nothing is saved |
| `omi/VERSION` | `0.0.7` |
| `tests/settings_stealth/` | new `native_sim` ztest, the same pattern as `tests/haptic` |
| `.github/workflows/firmware_build_check.yml` | runs it beside `tests/haptic` |

#### Checked locally, on 28 October 2026

In the pinned container `ghcr.io/zephyrproject-rtos/ci:v0.26.13@sha256:b0ac6334…`,
NCS `v2.9.0`, with the SDK workspace mounted read-only:

| Check | Result |
|---|---|
| `tests/settings_stealth` | **6 / 6 pass** — boot starts off; on and off; nothing reaches storage and a restart ends it; the `0.0.6` record is ignored and not erased; the retired key is accepted where an unknown one is refused with `-ENOENT`; `dim_ratio` and `mic_gain` load, save and survive a restart |
| the same test against two deliberate regressions | **fails both** — a set that saves to flash (2 failures), a load that reads the old record (3 failures) |
| `tests/haptic` | 19 / 19 pass, unchanged |
| CI script self-tests (`scripts/ci`, `unittest`) | 106 pass |
| `version_gate.check()` on the changed paths | passes with `0.0.6+0 -> 0.0.7+0`; refuses the same change without the bump |
| `clang-format --dry-run --Werror` (18.1.5) on the changed C files | clean |
| application-core build (`omi/nrf5340/cpuapp`, sysbuild) | **success**; DIS `CONFIG_BT_DIS_FW_REV_STR="0.0.7"`, `CONFIG_MCUBOOT_IMGTOOL_SIGN_VERSION="0.0.7+0"` |
| `partition_gate.py` on the generated table | `settings_storage 0xf8000/0x2000`, `littlefs_storage 0xfa000/0x6000` — where shipped hardware has them |
| `make_shard_release.py` into a scratch directory | package `Shard_CV1_appcore_v0.0.7.zip`, 250,559 bytes, one application image, `sha256sum -c` OK |

**The local package is not the candidate.** Its archive and image hashes are of
no use to anybody and are deliberately not written down here. Its **payload**
hash, `21aa37d8ee2c10cd8fe7b39cc5dc4d7f530895a0ef29a936b5d86ee48ed4fb6a`, is
recorded for one purpose: the CI candidate built from the same source should
carry the same one, and a different value would be a question to answer before
step 5. Everything in this table is repeated by CI in step 3, and only that run
counts.

#### Rollback

**There is none on the device, and there was none before.** The bootloader
refuses any image lower than the one installed (§1) and cannot be replaced over
the air, so a Shard on `0.0.7` cannot be brought back to `0.0.6`. A fault in
`0.0.7` is corrected forward, by `0.0.8`. An Orb app that bundles `0.0.6` does
not try: `0.0.7` is not in its release line, so it reports unknown firmware and
writes nothing — but it still writes its own stored stealth wish back after
every restart of the device, which is why the Orb app that stops doing so has to
ship with this firmware, never after it.

#### Release body — approved and published

Written for step 10 from the recorded acceptance and the draft's manifest.
**Approved by the product owner on 2026-10-28 and published verbatim** as the
release body; nothing was added on the way out.

```markdown
Shard CV 1 — firmware 0.0.7

App core only, from NCS 2.9.0 with sysbuild and MCUboot. Accepted on hardware: a
Shard running 0.0.6 was updated to this build over the air by Orb, without
anybody asking it to, and reported 0.0.7 afterwards. Stealth on and off, a lost
Bluetooth link, an app restart, a device restart, recording, the button, the
haptics and charging were checked on that device.

What it changes against 0.0.6:

- Stealth Mode now lasts for one session of the device. Silencing the status
  light still takes effect at once and survives a lost Bluetooth link or a
  restart of the app, but it is no longer stored: after the device is switched
  off, runs flat, is updated or restarts for any other reason, its light
  behaves normally again. A device that was silenced when it receives this
  update comes back with its light on.
- Nothing else changes: the stealth characteristic keeps its UUID and format,
  and the one-off blue signal, haptics, the button, recording, the microphone
  gain and the dim ratio are as they were.

There is no way back: the bootloader accepts no image older than the one
installed, so a device on 0.0.7 cannot return to 0.0.6.

This build is consumed by the Orb app as a bundled asset. It is not served by
the Omi firmware endpoint and is not offered to Omi users.

SHA-256 (archive) 4740aed48c667f89f10300e868caaf7fe909a72f2dcc227e9fcde4332f3df100
SHA-256 (image)   afc72c2614194ec82f1a277827f1316b6a7a8148c23e8548b31d15137c3d1f06
SHA-256 (payload) 21aa37d8ee2c10cd8fe7b39cc5dc4d7f530895a0ef29a936b5d86ee48ed4fb6a

Only the payload hash survives a rebuild — MCUboot signs with RSA-PSS and its
salt is random.
```

**What the text deliberately does not say.** The empty-battery case, a second
device and the old/new app combinations were not run on hardware, and are not
claimed. The update test ran with stealth off, so the handling of a stored
`0.0.6` silence is shown by the firmware's own test, not by a device.

### 0.0.6 — **`RELEASE COMPLETE`**

Every step of §5 is done and verified against what was actually published, not
against the local copies. Nothing follows.

| Step | State |
|---|---|
| Built by CI from `main` | **done** — run `35497369218`, `push`, success, 2026-09-20T07:44:35Z |
| Candidate assembled | **done** — the three files of §3, draft created 2026-09-20T07:44:36Z |
| Accepted on hardware | **done** — see below |
| Orb points at exactly this artefact | **done** — `app/assets/firmware/Shard_CV1_appcore_v0.0.6.zip`, byte-identical to the published download, `cmp` clean |
| Orb's gates | **done** — analyzer clean, 2288 tests, the asset guard hashing the shipped bytes |
| Release commit fixed | **done** — `e1d36d9b673181464817d96c6daaf7a8f53e0f75`, named by the manifest the build itself wrote |
| Annotated tag `shard-cv1-v0.0.6` | **done**, dereferencing to `e1d36d9b67…` — checked as `^{commit}`, not by the tag object's own id |
| Tag pushed | **done** — verified remotely, `refs/tags/shard-cv1-v0.0.6^{}` = `e1d36d9b67…` |
| GitHub release `Shard CV1 0.0.6` | **done** — published `2026-09-20T08:37:31Z`, not a draft, not a pre-release |
| `Shard_CV1_appcore_v0.0.6.zip` attached | **done** — verified `6c9c75c1…` |
| `RELEASE_MANIFEST.md` attached | **done** — verified `4e4dfbd5…` |
| `SHA256SUMS` attached | **done** — verified `19095ed9…` |
| `sha256sum -c SHA256SUMS` on the download | **done** — both `OK` |
| Orb delivery copy identical to the published package | **done** — byte-for-byte, 0 differing bytes |

Release: https://github.com/demcoderseinnachbar/omi/releases/tag/shard-cv1-v0.0.6

The published files were downloaded back into a fresh directory and hashed
there; the byte comparison against the accepted candidate and against Orb's
bundled copy was made on those downloads, not on the files they were uploaded
from.

The tag is on the merge commit the manifest names and not on the branch head.
**The tag is never moved.**

#### The artefact this refers to

| | |
|---|---|
| Product | Shard CV 1 |
| Version | `0.0.6`, image `0.0.6+0` |
| Firmware commit | `e1d36d9b673181464817d96c6daaf7a8f53e0f75` |
| Tag | `shard-cv1-v0.0.6` |
| Archive | `Shard_CV1_appcore_v0.0.6.zip`, 250,579 bytes |
| Archive SHA-256 | `6c9c75c14a37d605eaae06ba26f689f426a455b60afeed34f6ae54cfe39a9da6` |
| Signed image | `omi.signed.bin`, 249,856 bytes |
| Signed image SHA-256 | `1aa6e26349c3562c8fca6de46f478b543968d8d5456b3620d36dc06af6627103` |
| Payload SHA-256 (image TLV) | `88496667cd6c6ea7f28bf103c2a92f5311aa1e0cf2447bf52cb4ea46e644affb` |
| Toolchain | nRF Connect SDK `v2.9.0`, sysbuild, MCUboot, RSA-2048 PSS |
| Container | `ghcr.io/zephyrproject-rtos/ci:v0.26.13@sha256:b0ac6334d1926cd0971a0a444f7adc6dd020e88ee3ce865aa070b6475a3ac4eb` |
| Package contents | `manifest.json` + one image at index 0, board `omi` — **no radio core** |

#### What this version contains

Two changes against `0.0.5`, and nothing else — no other commit touches firmware
sources in the range:

- **Stealth Mode.** A persistent `omi/stealth` setting of its own, kept in the
  device's flash beside `dim_ratio` and `mic_gain`, guarding the once-a-second
  status display. While it is on, the device stops saying whether it is
  connected, disconnected or charging. The short signals are untouched — the
  boot pulse and the ready fade run before that loop exists, and the existing
  error blinks are raised during initialisation.
- **A one-off blue signal, deliberately separate.** `19B10014` holds the stored
  state; `19B10015` is a write-only instruction to show one second of blue,
  once, on its own timer. Two characteristics because they are two kinds of
  thing: a momentary instruction must never be able to change what the device
  does for the rest of the week. The signal is never a side effect of
  connecting — the firmware cannot tell a deliberate open from an automatic
  reconnect, so the app asks for it.

Haptics, the button, the microphone and what the device records are unchanged.
`dim_ratio` is unchanged: silence and brightness are separate settings, and the
hardware acceptance confirmed the light returns at its previous brightness.

#### The hardware acceptance

    Manual validation device:
    Samsung Galaxy A25 (SM-A256B)

Serial `RZCXC034X1R`, pendant `D2:5A:68:29:1B:95`, 2026-09-20. The artefact was
installed **over Orb's own automatic update path** from the bundled candidate —
not over nRF Connect, and not from a local build. The device reported `0.0.6`
afterwards, read fresh from the device.

| | Point | Result |
|---|---|---|
| 0 | Firmware revision reads `0.0.6` | **PASS** |
| A | Stealth on: device state confirmed, pendant goes dark while charging | **PASS** |
| B | Link lost: no standing red, no repeated blink; Orb's own mark still turns red | **PASS** |
| C | Automatic reconnect: no blue signal | **PASS** |
| D | Deliberate app open: exactly one second of blue, once — on return and on restart | **PASS** |
| E | Device restart: boot and ready signals kept, stealth survives, no standing blue afterwards | **PASS** |
| F | Charging: no standing glow, no repeated blink, charging itself unaffected | **PASS** |
| G | Recording, button and haptics unchanged, including the alarm on a link lost mid-recording and its acknowledgement by one press | **PASS** |
| H | App restart: the wish survives and is reconciled with the device | **PASS** |
| I | Stealth off: ordinary LED behaviour returns immediately, at the previous brightness | **PASS** |
| J | Swapping to a second Shard | **NOT EXECUTABLE** — no second device exists. Not claimed as passed |

**One observation left open.** During C, shortly after the first reconnect, a
single one-byte write went to the device. Android's GATT log names no
characteristic, so it could not be attributed. Nothing visible followed from it,
and E disproved the worrying reading — a device that had lost the setting would
have come back showing a standing blue, and it did not. It is recorded here
because it was seen, not because it is explained.

### 0.0.5 — **`RELEASE COMPLETE`**

Published 2026-09-20, tag `shard-cv1-v0.0.5` on
`d07784fc04a226b708958a0bd7e6d066aa50d07e`, from the draft CI built on
2026-08-22. It carries the alarm on a connection lost during a recording, and
that alarm is part of `0.0.6` as well.

Release: https://github.com/demcoderseinnachbar/omi/releases/tag/shard-cv1-v0.0.5

**It sat as an unpublished draft for a month, and this document is the reason it
went unnoticed.** The hardware acceptance had passed on 2026-08-22 — six
contract points on a Samsung Galaxy A25 against pendant `E7:2D:36:5A:B1:D3`,
including a controlled fifteen-minute run — and §5 steps 8 to 15 were simply
never carried out. No blocker was recorded anywhere, because there was no entry
here to record it in: the Status section ended at `0.0.4` and the header still
said `0.0.4` was current. The only note that anything was outstanding lived in
the Orb repository, which is not where somebody looks up the state of a firmware
release.

**A version therefore gets its Status entry when its release completes, and the
header above moves with it.** That is what makes an unfinished release visible
in the one place that is read.

### 0.0.4 — **`RELEASE COMPLETE`**

Every step of §5 is done and verified against what was actually published, not
against the local copies. Nothing follows.

| Step | State |
|---|---|
| Built by CI from `main` | **done** — run `32174812652`, `workflow_dispatch`, success, 2026-08-18T19:07:03Z |
| Candidate assembled | **done** — the three files of §3 |
| Accepted on hardware | **done** — see below |
| Orb points at exactly this artefact | **done** — `app/assets/firmware/Shard_CV1_appcore_v0.0.4.zip`, byte-identical, `cmp` clean |
| Orb's gates | **done** — analyzer, 1062 tests, the asset guard hashing the shipped bytes |
| Release commit fixed | **done** — `9d491a57eb5e8337162e4c33958b642243243880` |
| Annotated tag `shard-cv1-v0.0.4` | **done**, dereferencing to `9d491a57eb…` — checked as `^{commit}`, not by the tag object's own id |
| Tag pushed | **done** — verified remotely, `refs/tags/shard-cv1-v0.0.4^{}` = `9d491a57eb…` |
| GitHub release `Shard CV1 0.0.4` | **done** — id `372606091`, published `2026-08-20T19:43:16Z`, not a draft, not a pre-release |
| `Shard_CV1_appcore_v0.0.4.zip` attached | **done** — verified `9e644a75…` |
| `RELEASE_MANIFEST.md` attached | **done** — verified `e03ac95e…` |
| `SHA256SUMS` attached | **done** — verified `c2a9a825…` |
| `sha256sum -c SHA256SUMS` on the download | **done** — both `OK` |
| Orb delivery copy identical to the published package | **done** — byte-for-byte, 0 differing bytes |

Release: https://github.com/demcoderseinnachbar/omi/releases/tag/shard-cv1-v0.0.4

All three hashes were taken from files **downloaded back from GitHub** into a
fresh directory, not from the copies they were uploaded from — the archive with
`Get-FileHash`, the signed image over the unpacked bytes, and the payload read
out of the image's own TLV trailer rather than transcribed from the manifest.

The tag is on the build commit and not on the branch head. Later commits — this
document among them — sit after it and are not part of the release. **The tag is
never moved to include them.**

The firmware for `0.0.4` is frozen. Anything further changes a version number
first.

#### The artefact this refers to

Every hash below was taken from the files themselves, not copied from the
manifest.

| | |
|---|---|
| Product | Shard CV 1 |
| Version | `0.0.4`, image `0.0.4+0` |
| Firmware commit | `9d491a57eb5e8337162e4c33958b642243243880` |
| Intended tag | `shard-cv1-v0.0.4` |
| Archive | `Shard_CV1_appcore_v0.0.4.zip`, 249,871 bytes |
| Archive SHA-256 | `9e644a756208ffe780deee3204837de6e52b28af3683b8cf4cd2a15108eec14b` |
| Signed image | `omi.signed.bin`, 249,148 bytes |
| Signed image SHA-256 | `cdf6f1e68f10e1111c28031886687d0ecd51de2953d7c4715ff6ab00d886c452` |
| Payload SHA-256 (image TLV) | `e725f8f1523b413781a72dedd84a23da876a468150edb9804ba88b54892b0316` |
| Toolchain | nRF Connect SDK `v2.9.0`, sysbuild, MCUboot, RSA-2048 PSS |
| Container | `ghcr.io/zephyrproject-rtos/ci:v0.26.13@sha256:b0ac6334d1926cd0971a0a444f7adc6dd020e88ee3ce865aa070b6475a3ac4eb` |
| Package contents | `manifest.json` + one image at index 0, board `omi` — **no radio core** |

**These exact bytes are the ones that went onto a device.** The archive Orb
carries and the archive that was downloaded from the draft are byte-identical,
and the payload hash was read out of the image's own TLV trailer rather than
transcribed.

#### Why no rebuild may replace these bytes

The three files were drafted by the candidate run, sat on the draft until the
hardware acceptance was done, and were published unchanged — never re-uploaded,
never rebuilt. The download-back verification confirms it from the other side:
what GitHub serves is byte-for-byte what Orb carries.

**A rebuild is not a substitute and must never be used as one.** MCUboot signs
with RSA-PSS, whose salt is random, and the DFU manifest records the build time
— a rebuild of this same commit produces a different archive and a different
image hash while the payload stays the same. It would therefore not be the
artefact that was accepted on hardware, and §5 step 11 forbids swapping the
package for one.

#### Hardware acceptance

`0.0.3` → `0.0.4` over Orb's automatic OTA path on **2026-08-19**, on a
**Samsung Galaxy A25 (SM-A256B)** with the pendant `E7:2D:36:5A:B1:D3`.

Orb read the device, decided `shouldUpdate` on its own and installed without
being asked. The upload, one reboot and the reconnect took about thirty seconds;
afterwards a fresh device-information read reported model `Shard CV 1`,
manufacturer `Unicorn Production` and firmware revision **`0.0.4`**, and the
updater reached `completed` — a state only reachable when that read matches what
the registry expects.

Established in the same session, on the updated device:

- **Boot and BLE.** The pendant came back after the reboot, services were
  rediscovered, and the link stayed up with battery notifications arriving
  every five seconds.
- **Button.** Six presses produced six button events with no duplicates.
- **Microphone and audio transport.** Three recordings of 5.9 s, 7.5 s and
  8.3 s delivered 299, 380 and 418 frames with **no frame loss** — every frame
  that arrived reached the app.
- **The whole pipeline.** All three recordings became Sparks with real
  transcripts through the ordinary upload and processing path.

What was **not** measured, and is therefore not claimed:

- **The battery gate is still unverified on hardware.** The run happened at
  100 %. An OTA below and above the 60 % threshold, and a device that will not
  report its charge, remain untested — as they were for `0.0.3`.
- **`mic_gain` and `dim_ratio` were not read.** No path exposes them.
- **The LED was not observed.**
- **Only one pendant exists.** Nothing here distinguishes a trait of this
  specimen from a trait of the hardware.

#### The haptics on this firmware

**Everything Orb does is verified, and the physical result is not.**

After a genuine app defect was found and fixed — `DeviceCaptureRecorder` and
`CaptureController` both confirmed the same capture edge, so one press asked the
motor twice — a controlled retest was run against these bytes. Six capture edges
produced **exactly six** haptic requests, six started GATT writes and six
callbacks with `status=0`, with **no refusals, no `busy` and no duplicates**, and
the levels alternated correctly between short for a start and long for an end.
The command path is therefore verified up to and including the pendant's ATT
acknowledgement.

**During that retest none of the six pulses was perceptible.** Later, on the
same firmware, the haptics worked again after the pendant was tapped mechanically
against a table.

**No cause is claimed** — not the motor, not a solder joint, not a contact, not
the driver, not the GPIO, and not `haptic.c`. The mechanical sensitivity is a
strong indication of an intermittent hardware or contact fault **on this
specimen**, and an indication is not a finding. This continues the same picture
recorded under `0.0.3` and does not resolve it: **the investigation stays closed
until a second pendant exists.**

What this does settle is where the boundary lies. `status=0` says the device
acknowledged the write; it says nothing about whether the motor turned, and no
link can report that. Everything on Orb's side of that boundary is now
observable — `OrbBleProof` carries `request → write started → callback` per
numbered request, and the developer page keeps a bounded history in which a
later success never erases an earlier failure.

**Firmware `0.0.4` is accepted in software.** Whether it is published while the
haptics of the one available pendant behave this way is a product decision, not
a technical one.

---

### 0.0.3 — **`RELEASE COMPLETE`**

Every step of §5 is done and verified against what was actually published, not
against the local copies. Nothing follows.

| Step | State |
|---|---|
| Accepted on hardware | **done** |
| Committed | **done** — `935ff3dbaff98d95c0922d572aa5f32d0e4ca46e` |
| Annotated tag `shard-cv1-v0.0.3` | **done**, pointing exactly at `935ff3db…` |
| Tag pushed | **done** — verified remotely, `refs/tags/shard-cv1-v0.0.3^{}` = `935ff3db…` |
| GitHub release `Shard CV1 v0.0.3` | **done** — id `371269673`, published `2026-08-16T08:14:43Z`, not a draft, not a pre-release |
| `Shard_CV1_appcore_v0.0.3.zip` attached | **done** — verified `7d8c5a46…` |
| `RELEASE_MANIFEST.md` attached | **done** — verified `132bd363…` |
| `SHA256SUMS` attached | **done** — verified `29da7427…` |
| `sha256sum -c SHA256SUMS` on the download | **done** — both `OK` |
| Orb delivery copy identical to the published package | **done** — `cmp`, byte-identical |

Release: https://github.com/demcoderseinnachbar/omi/releases/tag/shard-cv1-v0.0.3

All three hashes were taken from files **downloaded back from GitHub**, not from
the copies they were uploaded from. That is the whole point of steps 12 to 14:
the local file only ever proves what was meant to be published.

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

Separately open and unaffected by this release: **SMP over BLE is
unauthenticated** (`CONFIG_MCUMGR_TRANSPORT_BT_PERM_RW=y`) — the image signature
is the trust boundary, not the transport.

#### The haptic feedback, corrected

The manifest attached to this release says the pendant's haptic feedback is not
perceptible. **That was the observation at the time and the manifest is not
changed** — a published release artefact records what was seen when it was
published. Later observation on the same firmware says something different, and
this is where that belongs.

**The haptics work.** On 2026-08-16 both confirmations were felt through the
real product path — a button press started a recording with a short pulse, a
second press ended it with a longer one, the two were told apart by a person,
and the recording transcribed. Nothing was flashed or changed to get there.

**The same pendant is also inconsistent.** Within the same hour it produced no
perceptible pulse at all, then both pulses correctly, then nothing again —
including the **boot buzz**, which runs before any Bluetooth and involves no app.
The firmware bytes were identical throughout.

**No cause is claimed.** Not the motor, not a contact, not the firmware, not the
app, not a power cycle, not the case. None of them is supported by evidence, and
naming one would turn a guess into a record. What *is* established is that every
layer above the GPIO register was verified in the same session: 28 writes
answered with `GATT_SUCCESS`, the correct service and value, `motor_pin` present
in the generated devicetree, no pin conflict, and `haptic_init()` succeeding.

**There is exactly one pendant.** A single unit cannot distinguish a fault of
this specimen from a general hardware trait or from some other state-dependent
effect. **The next diagnostic step is a second pendant**, compared under
comparable conditions. Until one exists the investigation stays closed — further
measurement on one device would produce more observations and no more certainty.

### 0.0.2

Superseded by `0.0.3`. It was never tagged and never published: the tag
convention was settled after it shipped to hardware, and by then `0.0.3` was the
next release rather than a retrospective one. Devices provisioned with it are
recognised by the release line in Orb's firmware registry.

### A note on `prj.conf`

The build writes `omi/firmware/omi/prj.conf` as a copy of `omi.conf`. It is a
build artefact, is git-ignored, and is never part of a change.
