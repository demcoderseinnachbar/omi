# Firmware CI / Release

Two release tracks share this directory, and they answer different questions.
Everything below the "Shard" heading belongs to **our** product; everything
above it is the upstream **Omi** track and is left as it is.

| Track | Builds | Publishes | Documented in |
|---|---|---|---|
| **Omi CV1** | `firmware_release.yml`, manual dispatch | `Omi_CV1_v…`, served to Omi users by the Omi backend | this file |
| **Shard** | `firmware_build_check.yml` on every change, `shard_release_candidate.yml` on a version bump | nothing — it drafts, a person publishes | [`SHARD_RELEASES.md`](../../SHARD_RELEASES.md) |

---

## Omi CV1

Automation for building and releasing **Omi CV1** firmware (nRF5340).

Workflow: [`.github/workflows/firmware_release.yml`](../../../../.github/workflows/firmware_release.yml)

## How it works

A firmware "release" is a **GitHub Release** in a specific shape that the
backend ([`backend/routers/firmware.py`](../../../../backend/routers/firmware.py))
reads and serves to the app as an OTA update. The workflow builds the firmware
and publishes that Release.

The contract the backend requires (do not break these):

| Requirement | Value |
|---|---|
| Tag | `Omi_CV1_v<ver>` — **no** `OTA` in the tag |
| OTA asset name | must contain `ota` **and** end `.zip` (e.g. `Omi_CV1_OTA_v3.0.20.zip`) |
| Release state | published, **non-draft, non-prerelease** |
| Body | must contain a `<!-- KEY_VALUE_START … KEY_VALUE_END -->` block with `release_firmware_version` |

The firmware version is read from `CONFIG_BT_DIS_FW_REV_STR` in
[`omi/firmware/omi/omi.conf`](../../omi/omi.conf) (the build copies `omi.conf`
→ `prj.conf`, so this string is also baked into the binary's BLE DIS).

## Releasing a new CV1 version

1. Bump `CONFIG_BT_DIS_FW_REV_STR` in `omi/firmware/omi/omi.conf` and merge it.
2. Dry run (build only, artifacts attached to the Actions run, **no** release):
   ```bash
   gh workflow run firmware_release.yml
   ```
3. Publish:
   ```bash
   gh workflow run firmware_release.yml \
     -f publish=publish \
     -f changelog="Removed BLE bond-key|Bug fixes" \
     -f minimum_firmware_required=3.0.6 \
     -f minimum_app_version=1.0.74 \
     -f minimum_app_version_code=438 \
     -f ota_update_steps=battery,internet
   ```
   `version` defaults to the `omi.conf` value; pass `-f version=3.0.21` to override.

Publishing is only allowed from the **`main`** branch (the build-only path runs
from any branch). The publish step also refuses to overwrite an existing
`Omi_CV1_v<ver>` tag — bump the version if you need to re-release.

## Scripts

- `build-cv1.sh` — runs inside `ghcr.io/zephyrproject-rtos/ci` (firmware bind-mounted
  at `/omi/firmware`): west init/update of NCS v2.9.0, `cp omi.conf prj.conf`, and
  `west build … --sysbuild` (MCUboot-signed). Mirrors [`omi/firmware/omi/BUILD.md`](../../omi/BUILD.md).
  Outputs `dfu_application.zip`, `merged.hex`, `merged_CPUNET.hex`.
- `make-release-body.sh` — renders the GitHub Release body + `KEY_VALUE` block.

## Notes

- The Release is created by the **Omi Bot GitHub App** (`actions/create-github-app-token`,
  secrets `OMI_BOT_APP_ID` / `OMI_BOT_PRIVATE_KEY`) so it is clearly attributed to
  automation rather than a person — same as the desktop pipeline. The token is only
  minted on a publish run; build-only QA runs don't need the secrets.
- The build is heavy: ~1.5 GB NCS download + ~20-30 min on a cold cache.
- DK2 / OmiGlass are **not** automated here yet. DK2 can be added as a second job
  (NCS 2.7.0 + `adafruit-nrfutil`); OmiGlass uses a separate ESP32/PlatformIO toolchain.
- MCUboot signing uses the committed key `omi/firmware/bootloader/mcuboot/root-rsa-2048.pem`.

---

## Shard

**The release process is in [`SHARD_RELEASES.md`](../../SHARD_RELEASES.md) and is
not repeated here.** This section is only about which piece of automation does
what.

| | Runs on | Does |
|---|---|---|
| [`firmware_build_check.yml`](../../../../.github/workflows/firmware_build_check.yml) | every push to `main` / `feat/**` and every PR touching `omi/firmware/**` | builds, checks the partitions. Publishes nothing, uploads nothing, reads no secret |
| [`firmware_version_gate.yml`](../../../../.github/workflows/firmware_version_gate.yml) | pull requests touching `omi/firmware/**` | refuses a firmware change that forgot to raise `VERSION` |
| [`shard_release_candidate.yml`](../../../../.github/workflows/shard_release_candidate.yml) | pushes to `main` that raise `VERSION` | builds, assembles the release, attaches it to a **draft**. Never publishes and never tags |
| the same workflow | pushes to `main` that change the firmware **without** raising `VERSION` | marks an existing draft `SUPERSEDED` and fails, so it cannot be published as though it were current |

The build itself is described once, in
[`.github/actions/build-shard-firmware`](../../../../.github/actions/build-shard-firmware/action.yml),
and both workflows call it. Change how the firmware is built there.

### Scripts

All four run without dependencies, in CI and by hand alike:

- `version_gate.py <target-ref>` — refuses a change that reaches the image and
  leaves `VERSION` where the target branch has it.
- `partition_gate.py <partitions.yml>` — refuses a build whose `settings_storage`
  or `littlefs_storage` moved. Reads the **generated** table, not `pm_static.yml`.
- `release_gate.py <before-ref>` — decides whether a push to `main` raised the
  version, and whether that release is still unclaimed. Answers `release`,
  `no release` or a refusal; uncertainty is never `release`.
- `make_shard_release.py` — assembles the three files of §3 from one build, reads
  the MCUboot header and TLV trailer, and refuses a package that is not the
  application core alone or whose image disagrees with the version being
  released. Recomputes the payload hash rather than transcribing it.

Their tests are `test_*.py` beside them: `python3 -m unittest` in this directory,
no arguments, no dependencies.

### Doing it by hand

The same candidate, without CI:

```bash
cd omi/firmware
bash scripts/ci/build-cv1.sh                                    # in the container
python3 scripts/ci/partition_gate.py v2.9.0/build/partitions.yml
python3 scripts/ci/make_shard_release.py \
  --package v2.9.0/build/dfu_application.zip \
  --out /tmp/release --version 0.0.4 --tag shard-cv1-v0.0.4 \
  --commit "$(git rev-parse HEAD)" \
  --built-at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --ncs v2.9.0 --container "$CI_IMAGE"
```
