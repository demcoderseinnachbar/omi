# Firmware — Agent Guide

Two products build from this tree: **Omi CV1** (upstream, `Omi_CV1_v…`) and
**Shard CV 1** (ours, `shard-cv1-v…`, consumed by the Orb app). Never mix their
tags, asset names or version lines.

**There is no cable to a Shard.** Updates are over the air only, the bootloader
cannot be replaced, and downgrade prevention is compiled in — so a wrong version
or a moved partition cannot be undone. What follows from that:

- `omi/firmware/omi/VERSION` is the only version. Anything reaching the image
  needs a higher one in the same change; `firmware_version_gate.yml` refuses.
- The persistent partition addresses in `boards/omi/pm_static.yml` are a
  compatibility contract. `scripts/ci/partition_gate.py` reads the **generated**
  table after a build, not the pinning file.
- Read [`SHARD_RELEASES.md`](./SHARD_RELEASES.md) before touching `omi.conf`,
  `VERSION`, `Kconfig` or `omi/src/lib/core/transport.c`.

| For | Read |
|---|---|
| Shard versioning, tagging, releasing | [`SHARD_RELEASES.md`](./SHARD_RELEASES.md) |
| CI, gates, Omi CV1 releases | [`scripts/ci/README.md`](./scripts/ci/README.md) |
| Formatting | [`../../docs/agents/formatting.md`](../../docs/agents/formatting.md) |
| Changing this file | [`../../docs/agents/doc-maintenance.md`](../../docs/agents/doc-maintenance.md) |

This file is an index, not a handbook: it loads in every session under
`omi/firmware/`. Put detail in the document that already owns it and link to it.
