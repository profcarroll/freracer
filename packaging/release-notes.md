A Maemo 5 (fremantle) package for the Nokia N900. Tap the icon and drive:
the launcher starts a **journey** — an endless, seeded, procedurally
generated road through changing regions, with a soundtrack composed one beat
at a time from the road ahead. The two finite courses ship too.

The music costs frame rate — about 20 fps with it against 26 without, and
PulseAudio rather than the synth is where that goes. `freracer --mute` from a
shell, or `FRERACER_MUTE=1`, turns it off.

**Requires** a Maemo 5 N900 with `python2.5` and `python-pygame` installed
(both are in the archival Extras catalogue).

### Read this first: the N900 cannot download from GitHub

The device's OpenSSL is 0.9.8n (2010) and tops out at TLS 1.0. GitHub
requires TLS 1.2, so `github.com`, `raw.githubusercontent.com` and any
`*.github.io` page fail the handshake outright — verified on device:

```
$ echo | openssl s_client -connect github.com:443
error:1407742E:SSL routines:SSL23_GET_SERVER_HELLO:tlsv1 alert protocol version
```

There is also no `wget` or `curl` in stock Maemo's BusyBox. So the files
below are downloaded **on a laptop**, and reach the device over the LAN or
over `scp`. Everything below is built around that fact.

### The easy way: install and update from a catalogue

On a laptop on the same Wi-Fi as the N900, with this repo cloned:

```
sh packaging/serve-repo.sh
```

It builds the package, wraps it in an apt repository, prints your LAN
address, and serves it. Then on the device: **Application manager → menu
title → Application catalogues → New**

| Field | Value |
|---|---|
| Catalogue name | `freracer` |
| Web address | `http://<your-laptop-ip>:8000/` |
| Distribution | `fremantle` |
| Components | `free` |

Save; freracer appears under **Download**. Later releases appear under
**Update** — that is the whole point of doing it this way rather than
copying a file.

If you would rather not clone, `freracer-repo-<version>.tar.gz` below is the
same tree, prebuilt: unpack it and run `python3 -m http.server 8000` inside
it, then edit `freracer.install`'s `uri` to match your laptop.

`freracer.install` is a Maemo one-click file: served from that same address
and opened in the device's browser, it adds the catalogue and installs the
package without typing anything.

### The plain way: one file

Copy `freracer_<version>_all.deb` to the device and install it:

```
scp freracer_<version>_all.deb root@<device-ip>:/tmp/
ssh root@<device-ip> 'dpkg -i /tmp/freracer_<version>_all.deb'
```

(Both need the legacy SSH options the N900's 2009 OpenSSH requires — see the
README.) Tapping the `.deb` in the file manager works too.

### What it installs

`/opt/freracer` (the game and the soundtrack, on the 2 GB partition — the
rootfs is 256 MB), `/usr/bin/freracer` (the launcher), plus the app-grid entry
and icon. Logs and telemetry go to `~/.freracer`, which `apt-get remove`
leaves alone.

### Notes

- The catalogue is **unsigned**. Maemo will call it "not authenticated" and
  ask *install without verification?* — answer `y`. Nobody issues new
  signatures for a platform Nokia retired.
- `fremantle` has one **e**. `freemantle` 404s every refresh.
- Physics constants are still starting points; see the README's open
  questions.
