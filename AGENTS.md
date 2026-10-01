# AI development instructions

This repository uses a shared KiCad VPS workstation for hardware development.

## Source of truth

- Repository: `nikolajevs/ai`
- Default branch: `main`
- `main` is the source of truth.
- Do not make development commits directly to `main`.
- Start every task from the latest `origin/main`.
- Use a dedicated task branch for each task.
- Push the task branch and merge it only after review and validation.

## KiCad project

Primary KiCad project:

`pcb/PCB_V1/PCB_V1.kicad_pro`

VPS KiCad version:

`10.0.6`

## VPS layout

The VPS is a persistent remote KiCad workstation.

- Main checkout: `~/kicad/main`
- Task worktrees: `~/kicad/worktrees/`
- Full VPS setup, access, operations and troubleshooting: `vps-docs/README.md`

When working on the VPS, read `vps-docs/README.md` before changing workstation configuration.

## Git / worktree workflow

Before starting work:

1. Fetch the latest repository state.
2. Start from `origin/main`.
3. Create or use a dedicated task branch.
4. If working on the VPS, use a separate Git worktree under `~/kicad/worktrees/`.
5. Do not modify another agent's worktree.
6. Make focused commits.
7. Push the branch to GitHub.
8. Merge only after checks and review.

ChatGPT and Claude may work in parallel, but they should use different branches/worktrees.

## Validation

For PCB-related changes, run from the repository's `pcb` directory:

```bash
KICAD_CLI=/usr/bin/kicad-cli \
KICAD_PYTHON=/usr/bin/python3 \
python3 check_all.py
```

The project validation includes ERC, netlist checks, board verification, calculations/BOM checks and DRC.

Do not use `check_all.py --write` unless the task intentionally requires updating committed review artifacts.

## Documentation and generated artifacts

Keep only current information in the working tree; git history keeps the rest.

- Living documents in `pcb/PCB_V1/`: `DESIGN.md` (current design, calculations, open items), `CHANGELOG.md` (one row per revision and the archive of removed files), `PLACEMENT.md`, `ROUTING_PREP.md`, `RTC_COMPATIBILITY.md`, `BOM_v0.1.*` and the README files. Update them instead of adding new documents.
- Write a task report in the PR description, not as a new file. Move durable results into `DESIGN.md` (decisions, calculations, open items) and add a `CHANGELOG.md` row.
- `pcb/review/` and `pcb/PCB_V1/*_snapshot_*.json` hold only the revision selected by `REV` / `PRICE_REV` in `check_all.py`. When either changes, delete the previous files in the same commit. Link old files by GitHub permalink, as in the `CHANGELOG.md` archive.
- Do not read large generated reports such as DRC `.rpt` in full; search them for the lines you need.

## KiCad merge safety

Treat these files carefully:

- `*.kicad_sch`
- `*.kicad_pcb`

Do not automatically resolve complex merge conflicts in KiCad schematic or PCB files.

If two branches changed the same schematic/PCB area, preserve both branches and require review or visual inspection in KiCad before merging.

## VPS safety

Do not change these unless the user explicitly asks for infrastructure work:

- Tailscale configuration
- TigerVNC/noVNC configuration
- systemd services
- SSH keys
- firewall/network configuration
- unrelated PM2/web services

Never commit passwords, private SSH keys, access tokens, Tailscale credentials or other secrets.
