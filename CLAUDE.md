# Agent instructions: H2LaserControl

Read `README.md` §8 first, then `memory-bank/progress.md` (status, open questions, next step).

## Rules from the user (standing)
1. **Hardware motion needs permission.** Before *every* command that moves a HIT-MV feedthrough
   (`H:`, `A:`, `M:`, `J:`; and `B:`/`D:` only as part of an approved move), ask the user and
   wait. The user watches the device. The feedthroughs are in vacuum on a live laser/muon
   beamline: an unexpected insertion blocks the beam or can damage the photodiode. Remember that
   `H:` (origin return) **inserts**. Read-only queries are fine.
   - ELL14: motion tests are allowed without asking, but note the starting position and
     settings (jog step, home offset) and **restore them** afterwards.
   - MFF101 flip mounts: tests were allowed only while the unit was *off the optical bench*.
     Once a unit is on the bench, ask before every flip. Restore to "insert" (position 2) after
     tests.
   - Never send: MFF EEPROM save (0x04B9), ELL14 `clean_and_optimize` (rewrites motor tuning)
     unless asked, DG645 `*RST`.
2. **Record before code.** While investigating a device (manuals, probes, captures), only
   write findings to `docs/protocols.md` and `memory-bank/progress.md`, each marked as from the
   manual, a capture, or a hardware test. Driver code and `config/devices.toml` change later, in
   their own step.
3. **Keep the memory bank up to date.** After each step, add a dated entry to `progress.md`
   (log, open questions, next step). Update `architecture.md` when a structural decision is
   made. Requirements from the user go into `design-document.md`.
4. Users are non-experts: the GUI must be simple, with plain-language messages, and every
   action must go through `Driver.execute` so it is logged.
5. Ask before guessing hardware facts (axis roles, which position is "insert", channel numbers).

## Environment
- Conda env **`H2LaserControl`** (Python 3.12): `conda run -n H2LaserControl python …`, or
  activate it first.
- Tests: `$env:QT_QPA_PLATFORM="offscreen"; conda run -n H2LaserControl python -m pytest -q`
  (PowerShell 5.1: set the env var first, then run). Lint: `ruff check .`
- Git may not be on PATH for the agent shell; on the original PC it is at
  `C:\Program Files\Git\cmd\git.exe`. Commit as the repo-local author (already in `.git/config`,
  do not change it). One commit per finished step, with a short summary line. To pass a
  multi-line message, write it to a file and use `git commit -F <file>`.
- **Never edit text files with PowerShell 5.1 `Get-Content`/`Set-Content`**: this PC's ANSI
  codepage is 932 (Shift-JIS), so the docs' UTF-8 symbols (✅ 📖 → ≈) get corrupted and a BOM is
  added. Use the editor tools. Likewise, a `git show … > file` inside PowerShell re-encodes the
  output; use `cmd /c` for byte-exact output.
- Close vendor software (SGSample, ELLO, Kinesis) before touching hardware. Vendor tools
  installed on the original PC: `C:\Program Files\Thorlabs\Elliptec` (ELLO, including its driver
  source code) and `C:\Program Files\Thorlabs\Kinesis`.
