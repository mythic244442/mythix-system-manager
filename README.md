# mythix-system-manager

A GTK3 desktop system manager for **Linux Mint** and **Debian** — updates,
packages, kernels, systemd services, security, cleanup, and logs in one window. **v1.3**.

## Requirements

- Python 3 with GTK bindings: `python3-gi`, `gir1.2-gtk-3.0`, `python3-apt`
- Optional: `gir1.2-ayatanaappindicator3-0.1` (tray indicator), `flatpak`,
  `timeshift` (snapshot-before-update), `notify-send`, `nvidia-smi` (GPU/VRAM telemetry)

## Usage

```sh
python3 mythix-system-manager.py
```

Or install system-wide (with desktop launcher and Polkit policy):

```sh
sudo make install
mythix-system-manager
```

`Ctrl+K` opens the command palette (supports `↑`/`↓` arrow navigation and `Enter`) — every page and quick maintenance action is reachable from there.

## Pages

| Group | Pages |
|-------|-------|
| **HOME** | Overview — stat cards, security score, live CPU/RAM sparkline + CPU/GPU thermals |
| **MAINTAIN** | Updates (apt + flatpak), Packages (incl. `apt-mark hold`), Cleanup (apt, orphans, old kernels, journald vacuum, GPU/Mesa shader cache, thumbnails, trash), History |
| **SYSTEM** | Kernels, Services (systemd system & user units + log jump), Repos (`.list` & `deb822` `.sources`), Startup, Upgrade |
| **PROTECT** | Security (UFW, unattended-upgrades, Fail2ban, SSH hardening, USB guard, core dumps, SysRq), Antivirus (ClamAV) |
| **OBSERVE** | Logs (journald viewer + export), System (CPU, GPU, Thermals, VRAM, RAM, Swap, Disks) |

## Behavior & Data

- Automatically resolves the real desktop user (`PKEXEC_UID` / `SUDO_UID`) when elevated via `pkexec` or `sudo`, so user paths (`~/.local/share/mythix-system-manager/`, `~/.cache/thumbnails/`, `~/.local/share/Trash/`, `~/.config/autostart/`, and `systemctl --user`) always target your user session rather than `/root`.
- Background update checks every `check_interval_min` minutes (default 60), with desktop notifications (optionally security-only).
- Optional Timeshift snapshot before installing updates.
- Settings: `~/.local/share/mythix-system-manager/settings.json`
- History: `~/.local/share/mythix-system-manager/history.json`
- Config backups before writes land in `/var/backups/mythix-system-manager/`.

All config writes are atomic and backed up first (`write_text_with_backup`), so a bad edit never leaves a half-written system file.

## Layout

```
mythix-system-manager/
  mythix-system-manager.py   thin launcher (re-execs via pkexec if not root)
  Makefile                   install / uninstall / test / check targets
  data/
    com.mythix.system-manager.desktop
    com.mythix.system-manager.policy
  system_manager/
    core.py                  constants, user resolution, thermal/GPU telemetry,
                             atomic-write helpers, distro detection
    app.py                   AppBase (window skeleton, CSS, tray, palette
                             wiring) + SystemManager composing all mixins
    pages/
      palette.py             Ctrl+K command palette with arrow-key navigation
      overview.py            HOME dashboard (stat cards, sparkline, thermals)
      updates.py             apt + flatpak updates
      packages.py            installed package browser, apt-mark hold
      cleanup.py             disk, kernel, journald & shader cache cleanup
      history.py             install history
      kernels.py             kernel manager & GRUB default selector
      services.py            systemd system & user services manager
      repos.py               APT repository manager (.list + deb822 .sources)
      startup.py             startup entry manager (user systemd + XDG autostart)
      upgrade.py             distro upgrade (mintupgrade / Debian codename swap)
      security.py            security toggles + score + sshd validation rollback
      antivirus.py           ClamAV scanning
      logs.py                journald viewer
      sysinfo.py             system info + thermals & VRAM with live refresh
  tests/
    test_core_and_repos.py   unit tests for core helpers & repo parsers
```
