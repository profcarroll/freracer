# Packaging freracer for Maemo 5

How the `.deb` and the application catalogue are built, and why they are built
this way rather than the modern way. Every constraint below was checked against
the actual device (Nokia N900, Maemo 5 PR1.3, `dpkg 1.14.25`, `OpenSSL 0.9.8n`),
not inferred from documentation.

## Build

```
sh packaging/build-deb.sh          # -> dist/freracer_0.1.0-1_all.deb
sh packaging/build-repo.sh http://10.0.0.66:8000/    # -> dist/repo/
sh packaging/serve-repo.sh         # both of the above, then serve on the LAN
```

`VERSION` is the single source of the version number; the release workflow
refuses to publish if the tag and `VERSION` disagree. The Debian revision comes
from `DEB_REVISION` (default `1`), for the case where the packaging changes but
the game does not.

Only `dpkg-deb` and coreutils are needed. No `dpkg-dev`, no `fakeroot`, no Maemo
SDK, no scratchbox: freracer is pure Python 2.5, so the package is
`Architecture: all` and there is nothing to cross-compile. `build-repo.sh`
writes the `Packages` and `Release` indexes by hand for the same reason — a
`Packages` entry is just each `.deb`'s control file plus `Filename`, `Size` and
checksums, and `Release` is a list of the index files with theirs.

## The five things that bite

**1. The device's `dpkg` predates xz.** `dpkg-deb` on a 2026 machine writes
`control.tar.xz`/`data.tar.zst`; the N900's `dpkg 1.14.25` refuses it with
*"contains ununderstood data member control.tar.xz, giving up"*. Hence
`-Zgzip`, which is the load-bearing flag in `build-deb.sh`. Check a built
package with `ar t foo.deb` — both members must end in `.gz`.

**2. `Section:` decides whether the GUI will touch it.** The Application manager
only installs packages whose section starts with `user/`; anything else is
rejected with *"Incompatible application package"*. freracer is
`Section: user/games`. System packages have to go through `apt-get install` in a
root terminal, which has no such filter.

**3. The icon lives in the control file.** For the Application manager to show
an icon for a package it has not installed yet, the icon has to be *in the
index* — so a 48×48 PNG is base64'd into an `XB-Maemo-Icon-26:` continuation
block in `control`. `build-repo.sh` copies control into `Packages` with
`dpkg-deb -I <deb> control`, verbatim, precisely so that multi-line block
survives; anything that reformats fields would drop it.

**4. `/opt`, not `/usr`.** The N900's rootfs is 256 MB and habitually near full;
`/opt` is on the 2 GB `/home` partition. Maemo calls installing there
"optification" and every non-trivial application does it. freracer's payload is
small enough not to need it, but it follows the convention.

**5. The game must not write to its install directory.** `game.py` resolves
`tracks/` and `buzz_helper.py` from its own `__file__`, but it writes this run's
telemetry CSV under the *working* directory. `/opt/freracer` is root-owned and
Hildon launches applications as `user`, so `/usr/bin/freracer` runs the game
from `~/.freracer` instead — which is also where the log goes, and which
`apt-get remove` deliberately leaves behind.

## The one that has no clean fix: the device cannot reach GitHub

The obvious design is a catalogue hosted on GitHub Pages, updating itself from
releases. It cannot work. The N900's OpenSSL is 0.9.8n (March 2010), which
offers TLS 1.0 at best; GitHub has required TLS 1.2 since 2018. On the device:

```
$ echo | openssl s_client -connect github.com:443
CONNECTED(00000003)
error:1407742E:SSL routines:SSL23_GET_SERVER_HELLO:tlsv1 alert protocol version
```

`raw.githubusercontent.com` fails the same way, and `*.github.io` is HSTS
preloaded, so even `http://` gets redirected into a handshake that cannot
complete. apt *has* an https method (`/usr/lib/apt/methods/https` is present),
but it is the same OpenSSL underneath. There is no `wget` or `curl` in stock
Maemo's BusyBox either, so there is no manual fallback.

So the split is: **GitHub is the source of truth and holds the artifacts; a
plain-HTTP host the device can actually reach serves them.** Three ways to be
that host, in increasing order of effort:

- **A laptop on the same Wi-Fi** — `packaging/serve-repo.sh`. Zero infra, and
  it is the pattern the course already teaches
  ([nokia-n900-software-repos.md](https://github.com/mfadt/sld-fall-2026/blob/main/docs/nokia-n900-software-repos.md),
  Part 2). Updates work; the laptop just has to be running.
- **A plain-HTTP VPS** — e.g. the same free Oracle Ampere node that hosts the
  course designer model. Unpack `freracer-repo-<version>.tar.gz` under a web
  root, point `freracer.install` at it, and the device updates over the internet
  with nothing else running. This is the only arrangement where an N900 owner
  who is not you gets updates unattended.
- **A TLS 1.2-capable stack on the device** — a backported `libssl` for
  fremantle. Out of scope here, and it would have to be maintained.

## One-click install files

`freracer.install` is Maemo's one-click format: an ini file listing a catalogue
and a package. `application/x-install-instructions` is registered to
`hildon-application-manager` on a stock device, so opening it in the browser
adds the catalogue and offers the install. `build-repo.sh` generates it with
whatever base URI it was given, which is why rebasing the repo to a new host is
one command and not a hand edit.

## Verifying without installing

Both of these are read-only on the device and worth running before shipping:

```
dpkg -I freracer_0.1.0-1_all.deb            # the device's own dpkg parses it
dpkg -i --no-act freracer_0.1.0-1_all.deb   # unpack dry run, arch + deps
apt-get update && apt-cache policy freracer # the catalogue is really serving it
apt-get install --dry-run freracer          # dependencies resolve on this device
```

`apt-cache policy` naming the catalogue as the candidate's origin is the signal
that `Packages`, `Release` and the pool paths all line up; a repo with a broken
`Release` fails earlier, during `update`.

The *update* path is worth checking the same way, since it is the reason for
having a catalogue at all. Build a second revision into the same repo
(`DEB_REVISION=2 sh packaging/build-deb.sh && sh packaging/build-repo.sh`),
refresh, and `apt-cache policy` reports the installed revision against the newer
candidate, with `apt-get upgrade --dry-run` planning the swap:

```
  Installed: 0.1.0-1
  Candidate: 0.1.0-2
Inst freracer [0.1.0-1] (0.1.0-2 freracer:fremantle)
```

## What is in the package

The same Python 2.5 files `tools/deploy.sh` copies — the game, the generator,
the tracks, `synth.py` and `music.py`, and the three on-device tools. The
soundtrack plays by default; `freracer --mute` from a shell or `FRERACER_MUTE=1`
turns it off, and it costs frame rate (20.1 fps against ~26 muted, measured
through the packaged launcher). The Python 3 laptop tools —
`generate_track.py`, `render_shot.py`, `fake_pygame.py`, `render_song.py`,
`fake_audioop.py` — are deliberately not packaged; they cannot run on the
device.
