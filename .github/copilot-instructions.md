# freracer — assistant bootstrap

Target device: Nokia N900, Maemo 5, **Python 2.5.4**, pygame 1.9.1, 800x480 screen.
Hard rules for any code you write here:
- Python 2.5 only: no `json` module (use a tiny hand parser), no `with` statement unless
  `from __future__ import with_statement`, no f-strings, no `print()` function, no dict
  comprehensions, no `str.format`, no `except X as e` (use `except X, e`), no `bytes`, no
  `nonlocal`, no ternary-free tricks that need 2.6+.
- Standard library and pygame only. No pip, no third-party packages.
- Tracks are data, not code: a track is a plain-text file the track designer (an LLM on a
  remote server, `qwen3-coder` on `sld-cloud`) can emit, and the game loads it without
  executing anything. See `tracks/FORMAT.md`.
- Keep files short. One concern per file. No frameworks.
- Do not run pip, git, network commands, or anything outside this directory.
- Bytes to atoms: this assistant does not get shell/SSH access to the N900. It writes
  files; a person (or the directing assistant, by hand) copies them to the device and
  runs them there.
