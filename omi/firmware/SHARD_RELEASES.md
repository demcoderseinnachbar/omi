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

**The current release is `0.0.3`.** See [Status](#status).

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

`.github/workflows/firmware_build_check.yml` runs it on every firmware change,
so a moved partition fails the commit that moved it rather than the release that
would have carried it to a device.

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
there is no way to tell which from the outside. An Orb test reads the shipped
package from disk and hashes it, so the two cannot drift apart silently.

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
