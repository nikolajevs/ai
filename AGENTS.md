# AI development instructions

The former KiCad VPS workstation was decommissioned on 2026-10-22.
Develop and validate hardware in a separate environment with KiCad installed.

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

`hardware/PCB_V1/PCB_V1.kicad_pro`

## VPS status

KiCad, its libraries, service unit files and `~/kicad/` checkouts/worktrees
were removed from the VPS on 2026-10-22. Do not assume `kicad-cli` or the old
`ai-codex` / `ai-claude` launchers work there. See `vps-docs/README.md` for the
cleanup evidence, access limitations and remaining service documentation.

Do not recreate the workstation unless explicitly requested.

## Git / worktree workflow

Before starting work:

1. Fetch the latest repository state.
2. Start from `origin/main`.
3. Create or use a dedicated task branch.
4. In an isolated cloud task, use the existing checkout; do not create a worktree unless requested.
5. Do not modify another agent's worktree.
6. Make focused commits.
7. Push the branch to GitHub.
8. Merge only after checks and review.

ChatGPT and Claude may work in parallel, but they should use separate branches
and isolated checkouts, or separate worktrees when explicitly requested.

## Validation

For PCB-related changes, use an environment with KiCad, its Python bindings
and standard libraries configured. The former VPS no longer provides them.
Run from the repository's `hardware` directory:

```bash
KICAD_CLI=/usr/bin/kicad-cli \
KICAD_PYTHON=/usr/bin/python3 \
python3 check_all.py
```

The project validation includes ERC, netlist checks, board verification, calculations/BOM checks and DRC.

Do not use `check_all.py --write` unless the task intentionally requires updating committed review artifacts.

## Documentation and generated artifacts

Keep only current information in the working tree; git history keeps the rest.

- Living documents in `hardware/PCB_V1/`: `DESIGN.md` (current design, calculations, open items), `CHANGELOG.md` (one row per revision and the archive of removed files), `PLACEMENT.md`, `ROUTING_PREP.md`, `RTC_COMPATIBILITY.md`, `BOM_v0.1.*` and the README files. Update them instead of adding new documents.
- Write a task report in the PR description, not as a new file. Move durable results into `DESIGN.md` (decisions, calculations, open items) and add a `CHANGELOG.md` row.
- `hardware/review/` and `hardware/PCB_V1/*_snapshot_*.json` hold only the revision selected by `REV` / `PRICE_REV` in `check_all.py`. When either changes, delete the previous files in the same commit. Link old files by GitHub permalink, as in the `CHANGELOG.md` archive.
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
