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
- When a check could not run in your environment (a cloud task usually has no KiCad), the PR description lists which checks were run and which were not. Committed reports that are older than the change are marked as such, never presented as current.

## Projects

| Project | KiCad project | Firmware | Status |
| --- | --- | --- | --- |
| PCB_EU (EU-0.1) | `hardware/PCB_EU/PCB_EU.kicad_pro` | `softwareEU/` | current board |
| PCB_V1 | `hardware/PCB_V1/PCB_V1.kicad_pro` | `software/` | previous board, separate project |

- A task that does not name a project is about PCB_EU.
- `hardware/PCB_V1/`, `hardware/cheap-version/`, `hardware/enclosure/` and `software/` are separate from PCB_EU. Do not change them in a PCB_EU task.
- Firmware of one board does not run on the other.

## PCB_EU

Owner decisions (Igors). Change them only on his explicit word.

- Language: README, `DESIGN.md`, PR titles and descriptions, and replies to Igors are in Russian. Commit subjects are in English.
- Shops: buy only from Salvats, Electrobase, Semikom and Lemona (list confirmed by Igors on 2026-10-23). Farnell, Elektrika, Ormix and any other shop are not allowed. Prices are in EUR with VAT and carry a date.
- Budget: target about 80 EUR, hard ceiling 100 EUR for parts with VAT and delivery. PCB, PSU, loads, tools and the external thermal cutoff are not included. The current estimate is in `hardware/PCB_EU/README.md`, section "Закупка"; `tools/verify.py` checks the ceiling.
- Do not change the board design or the BOM unless the task asks for it.

Sources and generated files:

- `tools/generate.py` writes the schematics (`*.kicad_sch`), `PCB_EU.kicad_pro`, `libraries/EU.kicad_sym`, `design.json`, `BOM_allocated.csv`, `BOM_allocated.json` and `review/BOM_summary.json`. Change the generator and run it again; do not edit these outputs by hand.
- `PCB_EU.kicad_pcb` is built by the scripts listed in the README, section "Проверки" (`build_board.py`, `route_power.py`, `route_board.py`, `silkscreen.py`). Edit the board text by hand only when the change cannot be rebuilt in your environment, and say so in the PR.
- Firmware build and tests: `softwareEU/README.md`.

Checks, run from the repository root:

- Without KiCad: `python3 hardware/PCB_EU/tools/generate.py` (it must not change committed files unless the generator changed) and `python3 hardware/PCB_EU/tools/verify.py hardware/PCB_EU/review/netlist.xml` (connections, purchase quantities, budget ceiling).
- With KiCad 10.0.7 (`kicad-cli` and `pcbnew` Python) and Shapely 2: `python3 hardware/PCB_EU/tools/run_checks.py` (ERC, footprints, placement, DRC, power copper, JLCPCB checks). KiCad 10.0.7 is the version of the committed reports. Another version needs `--allow-other-version` and is recorded in `review/validation.json`.
- `hardware/check_all.py` checks only PCB_V1. Do not use it for PCB_EU.
- `hardware/PCB_EU/review/` holds the result of the last full KiCad run. The README, section "Проверки", says which files are older than the design. Refresh them only with a full `run_checks.py` run.

Documents: PCB_EU has no `CHANGELOG.md`. `README.md` and `DESIGN.md` record each owner decision once, with its date, and superseded text is removed when a decision changes (git history keeps it). `procurement_2026-10-20.json` is a dated price snapshot, not a current offer; the current prices are in `BOM_allocated.csv` (column `Price_date`).

## Parts catalog

`parts-catalog/` is a local search over the prices and stock of the four allowed shops, with a BOM check and an analog finder (Python, FastAPI, SQLite; README in Russian). It is a tool, not a board: it only reads `hardware/PCB_EU/BOM_allocated.csv`, `BOM_allocated.json`, `design.json` and `review/BOM_summary.json`, and it never changes the board or the BOM.

- Tests (offline, on saved shop pages): `cd parts-catalog && python -m pip install -r requirements-dev.txt && python -m pytest`.
- Do not crawl the shops from a cloud task. Igors runs the live collection on his own computer (2026-10-23); Semikom bans an address that loads pages faster than about one in four seconds (HTTP 423). Keep the shop pauses and the `robots.txt` handling in `partscat/http.py` and `partscat/shops/` as they are.
- The Windows archive is built by `python parts-catalog/tools/pack_windows.py` from the current BOM files; it has an empty database.

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

## Validation of PCB_V1

For PCB-related changes, use an environment with KiCad, its Python bindings
and standard libraries configured. The former VPS no longer provides them.
Run from the repository's `hardware` directory:

```bash
KICAD_CLI=/usr/bin/kicad-cli \
KICAD_PYTHON=/usr/bin/python3 \
python3 check_all.py
```

The validation includes ERC, netlist checks, board verification, calculations/BOM checks and DRC.

Do not use `check_all.py --write` unless the task intentionally requires updating committed review artifacts.

PCB_EU has its own checks; see the PCB_EU section above.

## Documentation and generated artifacts

Keep only current information in the working tree; git history keeps the rest.

- Living documents in `hardware/PCB_V1/`: `DESIGN.md` (current design, calculations, open items), `CHANGELOG.md` (one row per revision and the archive of removed files), `PLACEMENT.md`, `ROUTING_PREP.md`, `RTC_COMPATIBILITY.md`, `BOM_v0.1.*` and the README files. Update them instead of adding new documents.
- Write a task report in the PR description, not as a new file. Move durable results into `DESIGN.md` (decisions, calculations, open items); for PCB_V1 also add a `CHANGELOG.md` row.
- `hardware/review/` and `hardware/PCB_V1/*_snapshot_*.json` hold only the revision selected by `REV` / `PRICE_REV` in `check_all.py`. When either changes, delete the previous files in the same commit. Link old files by GitHub permalink, as in the `CHANGELOG.md` archive.
- Do not read large generated reports such as DRC `.rpt` in full; search them for the lines you need.

## KiCad merge safety

Treat these files carefully:

- `*.kicad_sch`
- `*.kicad_pcb`

Do not automatically resolve complex merge conflicts in KiCad schematic or PCB files.

If two branches changed the same schematic/PCB area, preserve both branches and require review or visual inspection in KiCad before merging.

In PCB_EU the schematics are generated: when the conflict comes from the generator inputs, merge the sources (`tools/*.py`, `placement.json`, `routing.json`) and run `tools/generate.py` again instead of editing the generated files.

## VPS safety

Do not change these unless the user explicitly asks for infrastructure work:

- Tailscale configuration
- TigerVNC/noVNC configuration
- systemd services
- SSH keys
- firewall/network configuration
- unrelated PM2/web services

Never commit passwords, private SSH keys, access tokens, Tailscale credentials or other secrets.
