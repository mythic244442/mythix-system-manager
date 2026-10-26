#!/usr/bin/env python3
"""
Mythix System Manager — GTK3 system manager for Linux Mint and Debian.
v1.3: Overview dashboard + command palette + Services manager + thermal/GPU telemetry.
  HOME:     Overview (stat cards, security score, live CPU/RAM sparkline + temps)
  MAINTAIN: Updates (apt + flatpak) | Packages (incl. apt-mark hold) | Cleanup | History
  SYSTEM:   Kernels | Services | Repos | Startup | Upgrade
  PROTECT:  Security | Antivirus
  OBSERVE:  Logs | System
Ctrl+K opens the command palette. Settings: check interval, Timeshift snapshot,
flatpak toggle, accent color (live), notifications, history retention.
"""

import subprocess, threading, os, sys, re, json, glob, platform, time, shutil, tempfile, pwd
from datetime import datetime
from pathlib import Path

try:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("GLib", "2.0")
    try:
        gi.require_version("AppIndicator3", "0.1")
        from gi.repository import AppIndicator3
        HAS_APPINDICATOR = True
    except (ValueError, ImportError):
        HAS_APPINDICATOR = False
    from gi.repository import Gtk, GLib, Gdk, Pango
except ImportError:
    # Allow importing core helpers in headless unit tests without GTK installed
    Gtk = GLib = Gdk = Pango = AppIndicator3 = None
    HAS_APPINDICATOR = False

try:
    import apt
except ImportError:
    apt = None

APP_NAME    = "Mythix System Manager"
APP_VERSION = "1.3.0"
APP_ID      = "com.mythix.system-manager"


def resolve_invoking_user():
    """Return (uid, gid, username, home_path) of the real desktop user even when
    elevated to root via pkexec or sudo."""
    for env_uid in ("PKEXEC_UID", "SUDO_UID"):
        val = os.environ.get(env_uid, "").strip()
        if val.isdigit() and int(val) > 0:
            try:
                pw = pwd.getpwuid(int(val))
                return pw.pw_uid, pw.pw_gid, pw.pw_name, Path(pw.pw_dir)
            except KeyError:
                pass

    for env_user in ("SUDO_USER", "LOGNAME", "USER"):
        name = os.environ.get(env_user, "").strip()
        if name and name != "root":
            try:
                pw = pwd.getpwnam(name)
                if pw.pw_uid > 0:
                    return pw.pw_uid, pw.pw_gid, pw.pw_name, Path(pw.pw_dir)
            except KeyError:
                pass

    # If XDG_RUNTIME_DIR is /run/user/<uid>, extract <uid>
    xdg_rt = os.environ.get("XDG_RUNTIME_DIR", "")
    m = re.match(r"^/run/user/(\d+)$", xdg_rt.strip())
    if m and int(m.group(1)) > 0:
        try:
            pw = pwd.getpwuid(int(m.group(1)))
            return pw.pw_uid, pw.pw_gid, pw.pw_name, Path(pw.pw_dir)
        except KeyError:
            pass

    # Fallback when running as root without env vars: check /run/user/* for active session
    if os.geteuid() == 0:
        try:
            for p in sorted(Path("/run/user").iterdir()):
                if p.name.isdigit() and int(p.name) >= 1000:
                    pw = pwd.getpwuid(int(p.name))
                    return pw.pw_uid, pw.pw_gid, pw.pw_name, Path(pw.pw_dir)
        except Exception:
            pass

    try:
        pw = pwd.getpwuid(os.getuid())
        return pw.pw_uid, pw.pw_gid, pw.pw_name, Path(pw.pw_dir)
    except Exception:
        return os.getuid(), os.getgid(), "root", Path.home()


USER_UID, USER_GID, USER_NAME, USER_HOME = resolve_invoking_user()

DATA_DIR      = USER_HOME / ".local" / "share" / "mythix-system-manager"
HISTORY_FILE  = DATA_DIR / "history.json"
SETTINGS_FILE = DATA_DIR / "settings.json"

DEFAULT_SETTINGS = {
    "check_interval_min": 60,         # background update-check interval
    "snapshot_before_install": False, # Timeshift snapshot before installing updates
    "include_flatpak_updates": True,  # show flatpak updates in the Updates page
    "accent": "Mythix Cyan",          # UI accent color (see SystemManager.ACCENTS)
    "notify_updates": True,           # desktop notification when updates appear
    "notify_security_only": False,    # …but only when security updates are among them
    "history_keep": 200,              # install events kept in history.json
}


def _fix_user_ownership(path):
    """Ensure files created inside USER_HOME while running as root remain owned by USER_UID."""
    if os.geteuid() == 0 and USER_UID > 0:
        try:
            os.chown(path, USER_UID, USER_GID)
        except Exception:
            pass


def load_settings():
    s = dict(DEFAULT_SETTINGS)
    try:
        if SETTINGS_FILE.exists():
            s.update({k: v for k, v in json.loads(SETTINGS_FILE.read_text()).items()
                      if k in DEFAULT_SETTINGS})
    except Exception:
        pass
    return s


def save_settings(s):
    try:
        atomic_write_text(SETTINGS_FILE, json.dumps(s, indent=2))
        _fix_user_ownership(SETTINGS_FILE)
    except Exception:
        pass


BACKUP_ROOT = Path("/var/backups/mythix-system-manager")
# Migrate old data dir if it exists
_OLD_DATA_DIR = USER_HOME / ".local" / "share" / "looni-system-manager"
try:
    if _OLD_DATA_DIR.exists() and not DATA_DIR.exists():
        _OLD_DATA_DIR.rename(DATA_DIR)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _fix_user_ownership(DATA_DIR)
except Exception:
    pass

# ── Column constants ───────────────────────────────────────
# Updates
COL_SELECTED=0; COL_PACKAGE=1; COL_OLD_VER=2; COL_NEW_VER=3
COL_SIZE=4; COL_ORIGIN=5; COL_DESC=6; COL_RAW_SIZE=7; COL_IS_SECURITY=8
# Kernels
COL_K_RUNNING=0; COL_K_PACKAGE=1; COL_K_VERSION=2; COL_K_STATUS=3; COL_K_SIZE=4; COL_K_RAW_SIZE=5
# Services
COL_SV_ACTIVE=0; COL_SV_ENABLED=1; COL_SV_UNIT=2; COL_SV_STATE=3; COL_SV_SUB=4; COL_SV_DESC=5; COL_SV_SCOPE=6
# Repos
COL_R_ENABLED=0; COL_R_TYPE=1; COL_R_URL=2; COL_R_SUITE=3; COL_R_COMPS=4; COL_R_FILE=5; COL_R_LINE_NUM=6
# Packages
COL_P_MARK=0; COL_P_NAME=1; COL_P_INST=2; COL_P_AVAIL=3; COL_P_DESC=4; COL_P_SIZE=5; COL_P_RAW=6; COL_P_STATUS=7
# Antivirus
COL_AV_FILE=0; COL_AV_THREAT=1
# Startup
COL_ST_ENABLED=0; COL_ST_NAME=1; COL_ST_TYPE=2; COL_ST_DESC=3; COL_ST_FILE=4


def human_size(n):
    for u in ("B","KB","MB","GB"):
        if abs(n) < 1024: return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


def atomic_write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
        if str(path).startswith(str(USER_HOME)):
            _fix_user_ownership(path)
    finally:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except Exception:
            pass


def safe_expand_path(path):
    """Expand ~ and ~/ against the real desktop user's home directory (USER_HOME)
    rather than /root when running under pkexec/sudo."""
    s = str(path)
    if s == "~":
        return USER_HOME
    if s.startswith("~/"):
        return USER_HOME / s[2:]
    return Path(s).expanduser()


def run_as_user(cmd, timeout=15, check=False):
    """Run a user-session command (e.g. systemctl --user, notify-send) as the
    real desktop user when the app is running as root under pkexec/sudo."""
    env = dict(os.environ)
    if USER_UID > 0:
        rt_dir = f"/run/user/{USER_UID}"
        env.setdefault("XDG_RUNTIME_DIR", rt_dir)
        bus_path = f"{rt_dir}/bus"
        if Path(bus_path).exists():
            env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={bus_path}")
        env["HOME"] = str(USER_HOME)
        env["USER"] = USER_NAME
        env["LOGNAME"] = USER_NAME

    if os.geteuid() == 0 and USER_UID > 0 and shutil.which("runuser"):
        full_cmd = ["runuser", "-u", USER_NAME, "--"] + list(cmd)
        return subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout, check=check, env=env)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=check, env=env)


def read_thermal_and_gpu_telemetry():
    """Return a dict with cpu_temp_c, gpu_temp_c, gpu_util_pct, vram_used_mb, vram_total_mb."""
    out = {
        "cpu_temp_c": None,
        "gpu_temp_c": None,
        "gpu_util_pct": None,
        "vram_used_mb": None,
        "vram_total_mb": None,
    }
    # 1. CPU / APU temp via /sys/class/hwmon
    preferred_Chips = ("k10temp", "zenpower", "coretemp", "cpu_thermal", "acpitz")
    best_temp = None
    best_prio = 999
    try:
        for hw in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
            name_file = hw / "name"
            chip = name_file.read_text().strip().lower() if name_file.exists() else ""
            prio = next((i for i, c in enumerate(preferred_Chips) if c in chip), 50)
            for tf in sorted(hw.glob("temp*_input")):
                try:
                    milli = int(tf.read_text().strip())
                    deg = milli / 1000.0
                    if 5.0 < deg < 125.0 and prio < best_prio:
                        best_temp = deg
                        best_prio = prio
                        break
                except Exception:
                    pass
    except Exception:
        pass

    if best_temp is None:
        try:
            for tz in sorted(Path("/sys/class/thermal").glob("thermal_zone*/temp")):
                milli = int(tz.read_text().strip())
                deg = milli / 1000.0
                if 5.0 < deg < 125.0:
                    best_temp = deg
                    break
        except Exception:
            pass
    out["cpu_temp_c"] = best_temp

    # 2. NVIDIA GPU telemetry via nvidia-smi (if present, e.g. GTX 1660 Ti on bean2442)
    if shutil.which("nvidia-smi"):
        try:
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3
            )
            if r.returncode == 0 and r.stdout.strip():
                first = r.stdout.splitlines()[0]
                parts = [p.strip() for p in first.split(",")]
                if len(parts) >= 4:
                    out["gpu_temp_c"] = float(parts[0])
                    out["gpu_util_pct"] = float(parts[1])
                    out["vram_used_mb"] = float(parts[2])
                    out["vram_total_mb"] = float(parts[3])
        except Exception:
            pass

    # 3. AMD / DRM sysfs fallback for GPU temp & VRAM (e.g. AMD 610M / Raven Ridge APU)
    if out["gpu_temp_c"] is None:
        try:
            for hw in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
                chip = (hw / "name").read_text().strip().lower() if (hw / "name").exists() else ""
                if chip in ("amdgpu", "radeon", "nouveau", "i915", "xe"):
                    tf = hw / "temp1_input"
                    if tf.exists():
                        deg = int(tf.read_text().strip()) / 1000.0
                        if 5.0 < deg < 125.0:
                            out["gpu_temp_c"] = deg
                            break
        except Exception:
            pass

    if out["vram_total_mb"] is None:
        try:
            for card in sorted(Path("/sys/class/drm").glob("card[0-9]*")):
                tot_f = card / "device" / "mem_info_vram_total"
                used_f = card / "device" / "mem_info_vram_used"
                if tot_f.exists() and used_f.exists():
                    out["vram_total_mb"] = int(tot_f.read_text().strip()) / (1024 * 1024)
                    out["vram_used_mb"] = int(used_f.read_text().strip()) / (1024 * 1024)
                    break
        except Exception:
            pass

    return out


def make_backup(path, label="config"):
    src = Path(path)
    if not src.exists():
        return None
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest_dir = BACKUP_ROOT / stamp
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{src.name}.{label}"
    shutil.copy2(src, dest)
    return dest


def write_text_with_backup(path, text, label="config"):
    backup = make_backup(path, label=label)
    atomic_write_text(path, text)
    return backup


def remove_file_with_backup(path, label="config"):
    backup = make_backup(path, label=label)
    Path(path).unlink(missing_ok=True)
    return backup


# Debian stable release progression. Used to map current codename → next
# stable codename for the distro-upgrade tab on Debian systems.
DEBIAN_NEXT_CODENAME = {
    "buster":   "bullseye",
    "bullseye": "bookworm",
    "bookworm": "trixie",
    "trixie":   "forky",
}

# Linux Mint release progression (version → codename), in release order.
MINT_RELEASES = [
    ("21",    "vanessa"),
    ("21.1",  "vera"),
    ("21.2",  "victoria"),
    ("21.3",  "virginia"),
    ("22",    "wilma"),
    ("22.1",  "xia"),
    ("22.2",  "zara"),
    ("22.3",  "zena"),
]
MINT_LATEST = MINT_RELEASES[-1]


def mint_release_index(version):
    """Index of version in MINT_RELEASES, or None if unknown."""
    for i, (v, _cn) in enumerate(MINT_RELEASES):
        if v == version:
            return i
    return None


def detect_distro():
    """Identify the running distribution.

    Returns a dict with keys: id, version, codename, pretty.
    id is normalised to one of: 'linuxmint', 'debian', 'ubuntu', or the raw
    ID= value from /etc/os-release (lower-case) if it's something else.
    """
    info = {"id": "unknown", "version": "", "codename": "", "pretty": ""}
    try:
        mint_info = Path("/etc/linuxmint/info")
        if mint_info.exists():
            info["id"] = "linuxmint"
            for line in mint_info.read_text().splitlines():
                if line.startswith("RELEASE="):
                    info["version"] = line.split("=", 1)[1].strip()
                elif line.startswith("CODENAME="):
                    info["codename"] = line.split("=", 1)[1].strip()
            cn = f' "{info["codename"].capitalize()}"' if info["codename"] else ""
            info["pretty"] = f"Linux Mint {info['version']}{cn}".strip()
            return info

        for line in Path("/etc/os-release").read_text().splitlines():
            if "=" not in line: continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"')
            if   k == "ID":               info["id"] = v.lower()
            elif k == "VERSION_ID":       info["version"] = v
            elif k == "VERSION_CODENAME": info["codename"] = v
            elif k == "PRETTY_NAME":      info["pretty"] = v
        if not info["pretty"]:
            info["pretty"] = f"{info['id'].capitalize()} {info['version']}".strip()
    except Exception:
        pass
    return info


SECURITY_FEATURES = [
    {"key":"ufw",                 "title":"Firewall (UFW)",               "desc":"Block unauthorized incoming connections",                           "icon":"security-high-symbolic"},
    {"key":"auto_security_updates","title":"Automatic Security Updates",   "desc":"Install critical patches via unattended-upgrades",                 "icon":"system-software-update-symbolic"},
    {"key":"fail2ban",            "title":"Fail2ban",                      "desc":"Ban IPs showing brute-force / repeated auth failures",              "icon":"changes-prevent-symbolic"},
    {"key":"ssh_root",            "title":"Block Root SSH Login",          "desc":"Prevent direct root login over SSH",                               "icon":"dialog-password-symbolic"},
    {"key":"ssh_password",        "title":"SSH Key-Only Auth",             "desc":"Disable SSH password login — require keys",                        "icon":"dialog-password-symbolic"},
    {"key":"usb_storage",         "title":"Block USB Storage",             "desc":"Prevent USB drive auto-mount — stops exfiltration",                "icon":"drive-removable-media-symbolic"},
    {"key":"core_dumps",          "title":"Disable Core Dumps",            "desc":"Prevent memory dumps on crash",                                    "icon":"document-properties-symbolic"},
    {"key":"sysrq",               "title":"Restrict Magic SysRq",          "desc":"Limit kernel debug key combos",                                    "icon":"preferences-system-symbolic"},
]
