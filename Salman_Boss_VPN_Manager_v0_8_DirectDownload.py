# Salman Boss VPN Manager v0.8 — Master Admin, Exact Timer & Portable Edition
# Windows 10/11 | macOS 3D GUI + Exact Timer + City Button + Remote Admin Control
from __future__ import annotations
import argparse, ctypes, json, logging, os, random, shutil, subprocess, sys, urllib.request, urllib.parse
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

try:
    import winsound
except ImportError:
    winsound = None

APP = "Salman Boss VPN Manager"
APP_VERSION = "0.8.0"

# টেলিগ্রাম এবং হোয়াটসঅ্যাপ লিংক (নাম্বার বাটনে শো করবে না, লিংকে কাজ করবে)
TELEGRAM_URL = "https://t.me/Salman3579"
WHATSAPP_URL = "https://wa.me/8801955858703"

# ডিফল্ট অ্যাডমিন পিন কোড (অ্যাডমিন প্যানেল আনলক করার জন্য)
DEFAULT_ADMIN_PIN = "3579"

BASE = Path(os.environ.get("APPDATA", str(Path.home()))) / "SalmanBossVPN"
BASE.mkdir(parents=True, exist_ok=True)
CONFIG = BASE / "settings.json"
REMOTE_CONTROL_FILE = BASE / "remote_control_state.json"
LOGFILE = BASE / "manager.log"

logging.basicConfig(
    filename=LOGFILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


# ---------------------------------------------------------------------------
# BACKGROUND SYSTEM SETUP, PATH INJECTION & CONSOLE HIDING
# ---------------------------------------------------------------------------
def hide_console_window():
    """Hides the Windows CMD console window so only the GUI stays visible."""
    if os.name == "nt":
        try:
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)
        except Exception:
            pass


def is_admin() -> bool:
    if os.name != "nt":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def ensure_background_environment():
    """Automatically adds common VPN CLI paths and verifies required packages."""
    extra_paths = [
        r"C:\Program Files\Private Internet Access",
        r"C:\Program Files\PIA",
        r"C:\Program Files\ExpressVPN\services",
        r"C:\Program Files (x86)\ExpressVPN\services",
        r"C:\Program Files\NordVPN",
        r"C:\Program Files (x86)\NordVPN",
        r"C:\Program Files\Proton\VPN",
    ]
    current_path = os.environ.get("PATH", "")
    for p in extra_paths:
        if os.path.isdir(p) and p.lower() not in current_path.lower():
            os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")

    try:
        import PySide6  # noqa: F401
    except ImportError:
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "PySide6>=6.7,<7", "--quiet"],
                creationflags=CREATE_NO_WINDOW,
                check=False,
            )
        except Exception as e:
            logging.error("Silent dependency install failed: %s", e)


def play_sound_alert(kind: str, enabled: bool = True):
    if not enabled or winsound is None or os.name != "nt":
        return
    try:
        flags = winsound.SND_ALIAS | winsound.SND_ASYNC
        if kind == "success":
            winsound.PlaySound("SystemAsterisk", flags)
        elif kind == "failed":
            winsound.PlaySound("SystemHand", flags)
        else:
            winsound.PlaySound("SystemExclamation", flags)
    except Exception:
        pass


def run_hidden(exe: str, args: list[str], timeout: int = 25):
    try:
        p = subprocess.run(
            [exe, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
            encoding="utf-8",
            errors="replace",
        )
        out = ((p.stdout or "") + (p.stderr or "")).strip()
        logging.info("%s %s -> %s", exe, args, p.returncode)
        return p.returncode, out
    except Exception as e:
        logging.exception("Command failed")
        return 1, str(e)


def locate(names, extra=()):
    for n in names:
        found = shutil.which(n)
        if found:
            return found
    for p in extra:
        if Path(p).is_file():
            return str(p)
    return None


@dataclass
class Result:
    ok: bool
    message: str


# ---------------------------------------------------------------------------
# SETTINGS & REMOTE ADMIN CONTROL ENGINE
# ---------------------------------------------------------------------------
def load_settings() -> dict:
    try:
        if CONFIG.exists():
            return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        logging.exception("Could not read settings.json")
    return {}


def save_settings(updates: dict):
    try:
        data = load_settings()
        data.update(updates)
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        logging.exception("Could not write settings.json")


def get_default_remote_state() -> dict:
    return {
        "app_enabled": True,
        "latest_version": APP_VERSION,
        "update_message": "নতুন আপডেট এসেছে! সর্বশেষ ফিচার পেতে আপডেট করুন।",
        "update_script_url": "",
        "lock_message": "⛔ অ্যাডমিন (Salman Boss) এই সফটওয়্যারের অ্যাক্সেস সাময়িকভাবে বন্ধ রেখেছেন। যোগাযোগ করুন: WhatsApp / Telegram।",
    }


def load_control_state() -> dict:
    """Loads remote control JSON from configured URL or local shared control file."""
    cfg = load_settings()
    remote_url = cfg.get("remote_control_url", "https://gist.githubusercontent.com/amirlaptopxmd-rgb/72b0bced8b707dc3a86a1dfdd6c67eca/raw/175100b80c5d9f4f06963c2ae670b1cfc6c16d80/salman_admin_control.json").strip()
    state = get_default_remote_state()

    # Check local broadcast file first
    local_shared = Path(__file__).resolve().parent / "salman_admin_control.json"
    for candidate in (local_shared, REMOTE_CONTROL_FILE):
        if candidate.exists():
            try:
                loaded = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    state.update(loaded)
            except Exception:
                pass

    # If a remote raw URL (e.g., GitHub Gist / Pastebin / Server JSON) is set, fetch it
    if remote_url.startswith(("http://", "https://")):
        try:
            req = urllib.request.Request(
                remote_url,
                headers={"User-Agent": f"SalmanBossVPN/{APP_VERSION}", "Cache-Control": "no-cache"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                remote_data = json.loads(resp.read().decode("utf-8"))
                if isinstance(remote_data, dict):
                    state.update(remote_data)
        except Exception as e:
            logging.warning("Remote control URL fetch skipped: %s", e)

    return state


def save_control_state(new_state: dict):
    """Saves admin control state both to AppData and portable folder so clients/servers sync."""
    state = get_default_remote_state()
    state.update(new_state)
    payload = json.dumps(state, indent=2, ensure_ascii=False)
    try:
        REMOTE_CONTROL_FILE.write_text(payload, encoding="utf-8")
    except Exception:
        pass
    try:
        local_shared = Path(__file__).resolve().parent / "salman_admin_control.json"
        local_shared.write_text(payload, encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# COUNTRY & CITY CATALOG + SMART REGION PARSER
# ---------------------------------------------------------------------------
COUNTRY_PREFIX_MAP = {
    "us": "United States",
    "uk": "United Kingdom",
    "gb": "United Kingdom",
    "ca": "Canada",
    "au": "Australia",
    "de": "Germany",
    "nl": "Netherlands",
    "fr": "France",
    "ch": "Switzerland",
    "se": "Sweden",
    "no": "Norway",
    "fi": "Finland",
    "dk": "Denmark",
    "it": "Italy",
    "es": "Spain",
    "jp": "Japan",
    "sg": "Singapore",
    "id": "Indonesia",
    "in": "India",
    "br": "Brazil",
    "mx": "Mexico",
    "za": "South Africa",
    "ae": "United Arab Emirates",
    "hk": "Hong Kong",
    "kr": "South Korea",
    "my": "Malaysia",
    "ph": "Philippines",
    "vn": "Vietnam",
    "th": "Thailand",
    "tr": "Turkey",
    "pl": "Poland",
    "ro": "Romania",
    "at": "Austria",
    "be": "Belgium",
    "ie": "Ireland",
    "nz": "New Zealand",
}

COUNTRY_FLAGS = {
    "Singapore": "🇸🇬",
    "Indonesia": "🇮🇩",
    "United States": "🇺🇸",
    "United Kingdom": "🇬🇧",
    "Canada": "🇨🇦",
    "Germany": "🇩🇪",
    "Australia": "🇦🇺",
    "Japan": "🇯🇵",
    "India": "🇮🇳",
    "Netherlands": "🇳🇱",
    "France": "🇫🇷",
    "Switzerland": "🇨🇭",
    "Malaysia": "🇲🇾",
    "United Arab Emirates": "🇦🇪",
    "Turkey": "🇹🇷",
    "Sweden": "🇸🇪",
    "Brazil": "🇧🇷",
}

DEFAULT_COUNTRY_CITIES: dict[str, list[tuple[str, str]]] = {
    "Singapore": [
        ("Marina Bay", "sg-singapore"),
        ("Jurong East", "singapore"),
        ("Changi Central", "singapore"),
    ],
    "Indonesia": [
        ("Jakarta", "indonesia"),
        ("Surabaya", "indonesia"),
        ("Bali (Denpasar)", "indonesia"),
        ("Bandung", "indonesia"),
    ],
    "United States": [
        ("New York", "us-new-york"),
        ("Chicago", "us-chicago"),
        ("Atlanta", "us-atlanta"),
        ("Los Angeles (California)", "us-california"),
        ("Miami (Florida)", "us-florida"),
        ("Seattle", "us-seattle"),
        ("Dallas (Texas)", "us-texas"),
        ("Washington DC", "us-washington-dc"),
    ],
    "United Kingdom": [
        ("London", "uk-london"),
        ("Manchester", "uk-manchester"),
        ("Southampton", "uk-southampton"),
        ("Glasgow", "uk-glasgow"),
    ],
    "Canada": [
        ("Toronto", "ca-toronto"),
        ("Montreal", "ca-montreal"),
        ("Vancouver", "ca-vancouver"),
        ("Ontario", "ca-ontario"),
    ],
    "Germany": [
        ("Frankfurt", "de-frankfurt"),
        ("Berlin", "de-berlin"),
    ],
    "Australia": [
        ("Sydney", "au-sydney"),
        ("Melbourne", "au-melbourne"),
        ("Perth", "au-perth"),
        ("Brisbane", "au-brisbane"),
    ],
    "Japan": [
        ("Tokyo", "jp-tokyo"),
        ("Yokohama (Streaming)", "jp-streaming-optimized"),
    ],
    "India": [
        ("Mumbai", "in-mumbai"),
        ("New Delhi", "india"),
    ],
    "Netherlands": [
        ("Amsterdam", "nl-amsterdam"),
        ("Rotterdam", "netherlands"),
    ],
    "Malaysia": [
        ("Kuala Lumpur", "malaysia"),
        ("Johor Bahru", "malaysia"),
    ],
}


def build_country_city_tree(raw_locations: list[str]) -> dict[str, list[tuple[str, str]]]:
    tree: dict[str, list[tuple[str, str]]] = {}

    for raw in raw_locations:
        slug = raw.strip()
        if not slug or slug.lower() == "automatic":
            continue
        parts = slug.split("-")
        prefix = parts[0].lower()

        if prefix in COUNTRY_PREFIX_MAP and len(parts) > 1:
            country = COUNTRY_PREFIX_MAP[prefix]
            city_name = " ".join(p.capitalize() for p in parts[1:])
            tree.setdefault(country, []).append((city_name, slug))
        else:
            pretty_country = " ".join(p.capitalize() for p in parts)
            matched_country = None
            for known_c in DEFAULT_COUNTRY_CITIES:
                if known_c.lower() == pretty_country.lower() or known_c.lower() in slug.lower():
                    matched_country = known_c
                    break
            if matched_country:
                for city_label, _ in DEFAULT_COUNTRY_CITIES[matched_country]:
                    tree.setdefault(matched_country, []).append((city_label, slug))
            else:
                tree.setdefault(pretty_country, []).append((f"{pretty_country} Central", slug))

    if not tree:
        return {k: list(v) for k, v in DEFAULT_COUNTRY_CITIES.items()}

    for essential in ("Singapore", "Indonesia"):
        if essential not in tree:
            tree[essential] = list(DEFAULT_COUNTRY_CITIES[essential])
        elif len(tree[essential]) == 1:
            valid_slug = tree[essential][0][1]
            tree[essential] = [(city_lbl, valid_slug) for city_lbl, _ in DEFAULT_COUNTRY_CITIES[essential]]

    cleaned: dict[str, list[tuple[str, str]]] = {}
    for country, cities in sorted(tree.items()):
        seen = set()
        deduped = []
        for c_label, c_slug in cities:
            if c_label.lower() not in seen:
                seen.add(c_label.lower())
                deduped.append((c_label, c_slug))
        cleaned[country] = deduped
    return cleaned


# ---------------------------------------------------------------------------
# VPN PROVIDERS
# ---------------------------------------------------------------------------
class Provider:
    key = "provider"
    label = "Provider"

    def detect(self) -> Optional[str]:
        return None

    def connect(self, location="Automatic") -> Result:
        return Result(False, "Not supported")

    def disconnect(self) -> Result:
        return Result(False, "Not supported")

    def status(self) -> str:
        return "Unknown"

    def locations(self) -> list[str]:
        return []

    def test_connection_ready(self) -> Result:
        exe = self.detect()
        if not exe:
            return Result(False, f"{self.label} ইনস্টল করা নেই বা পাথ পাওয়া যায়নি।")
        st = self.status()
        return Result(True, f"{self.label} রেডি আছে (Status: {st})")


class PIA(Provider):
    key, label = "pia", "Private Internet Access (PIA)"

    def detect(self):
        return locate(
            ["piactl.exe", "piactl"],
            [
                r"C:\Program Files\Private Internet Access\piactl.exe",
                r"C:\Program Files\PIA\piactl.exe",
            ],
        )

    def _resolve_region(self, requested: str) -> str:
        if not requested or requested == "Automatic":
            return "auto"
        avail = self.locations()
        if not avail:
            return requested
        req_low = requested.lower().strip()
        for r in avail:
            if r.lower() == req_low:
                return r
        for r in avail:
            if req_low in r.lower() or r.lower() in req_low:
                return r
        return requested

    def connect(self, location="Automatic"):
        e = self.detect()
        if not e:
            return Result(False, "PIA পাওয়া যায়নি। অফিসিয়াল PIA Windows App ইনস্টল করুন।")
        run_hidden(e, ["background", "enable"], timeout=10)
        if location and location != "Automatic":
            resolved = self._resolve_region(location)
            rc, msg = run_hidden(e, ["set", "region", resolved])
            if rc != 0:
                return Result(False, f"PIA Region সেট করা যায়নি ({resolved}): {msg}")
        rc, msg = run_hidden(e, ["connect"])
        if rc == 0:
            return Result(True, f"PIA কানেক্ট কমান্ড সফল ({location})।")
        return Result(False, msg or "PIA কানেক্ট ব্যর্থ হয়েছে।")

    def disconnect(self):
        e = self.detect()
        if not e:
            return Result(False, "PIA CLI পাওয়া যায়নি।")
        rc, msg = run_hidden(e, ["disconnect"])
        return Result(rc == 0, msg or "PIA ডিসকানেক্ট কমান্ড পাঠানো হয়েছে।")

    def status(self):
        e = self.detect()
        if not e:
            return "Not installed"
        rc, msg = run_hidden(e, ["get", "connectionstate"])
        return msg if rc == 0 and msg else "Status unavailable"

    def locations(self):
        e = self.detect()
        if not e:
            return []
        rc, msg = run_hidden(e, ["get", "regions"])
        return [x.strip() for x in msg.splitlines() if x.strip()] if rc == 0 else []

    def test_connection_ready(self) -> Result:
        e = self.detect()
        if not e:
            return Result(False, "FAILED: PIA (piactl.exe) পিসিতে পাওয়া যায়নি।")
        run_hidden(e, ["background", "enable"], timeout=10)
        rc, state = run_hidden(e, ["get", "connectionstate"], timeout=12)
        if rc == 0 and state:
            rc_ip, vpn_ip = run_hidden(e, ["get", "vpnip"], timeout=10)
            ip_note = f" | VPN IP: {vpn_ip}" if (rc_ip == 0 and vpn_ip and vpn_ip != "Unknown") else ""
            return Result(True, f"SUCCESS: PIA সচল আছে — State: {state}{ip_note}")
        return Result(False, f"FAILED: PIA ব্যাকগ্রাউন্ড সার্ভিস সাড়া দিচ্ছে না ({state})।")


class ExpressVPN(Provider):
    key, label = "expressvpn", "ExpressVPN"

    def detect(self):
        return locate(
            ["expressvpnctl.exe", "expressvpnctl"],
            [
                r"C:\Program Files (x86)\ExpressVPN\services\expressvpnctl.exe",
                r"C:\Program Files\ExpressVPN\expressvpnctl.exe",
            ],
        )

    def connect(self, location="Automatic"):
        e = self.detect()
        if not e:
            return Result(False, "ExpressVPN CLI পাওয়া যায়নি।")
        run_hidden(e, ["background", "enable"], timeout=10)
        args = ["connect"] if not location or location == "Automatic" else ["connect", location]
        rc, msg = run_hidden(e, args)
        return Result(rc == 0, msg or f"ExpressVPN কানেক্ট কমান্ড পাঠানো হয়েছে ({location})।")

    def disconnect(self):
        e = self.detect()
        if not e:
            return Result(False, "ExpressVPN CLI পাওয়া যায়নি।")
        rc, msg = run_hidden(e, ["disconnect"])
        return Result(rc == 0, msg or "ExpressVPN ডিসকানেক্ট করা হয়েছে।")

    def status(self):
        e = self.detect()
        if not e:
            return "Not installed"
        rc, msg = run_hidden(e, ["status"])
        return msg or "Status unavailable"

    def locations(self):
        e = self.detect()
        if not e:
            return []
        rc, msg = run_hidden(e, ["get", "regions"], timeout=40)
        return [x.strip().strip('"') for x in msg.splitlines() if x.strip()] if rc == 0 else []


class ProtonVPN(Provider):
    key, label = "proton", "Proton VPN"

    def detect(self):
        p = Path(r"C:\Program Files\Proton\VPN")
        if p.exists():
            hits = list(p.glob("*/ProtonVPN.exe"))
            if hits:
                return str(hits[-1])
        return locate(["ProtonVPN.exe"])

    def connect(self, location="Automatic"):
        e = self.detect()
        if not e:
            return Result(False, "Proton VPN ইনস্টল করা নেই।")
        try:
            subprocess.Popen([e], creationflags=CREATE_NO_WINDOW)
            return Result(True, "Proton VPN অ্যাপ চালু করা হয়েছে।")
        except Exception as ex:
            return Result(False, str(ex))

    def disconnect(self):
        return Result(False, "Proton VPN এর অফিসিয়াল অ্যাপ থেকে ডিসকানেক্ট করুন।")

    def status(self):
        return "App detected" if self.detect() else "Not installed"


class NordVPN(Provider):
    key, label = "nord", "NordVPN"

    def detect(self):
        return locate(
            ["nordvpn.exe", "NordVPN.exe"],
            [
                r"C:\Program Files\NordVPN\NordVPN.exe",
                r"C:\Program Files (x86)\NordVPN\NordVPN.exe",
            ],
        )

    def connect(self, location="Automatic"):
        e = self.detect()
        if not e:
            return Result(False, "NordVPN ইনস্টল করা নেই।")
        args = ["-c"] if not location or location == "Automatic" else ["-c", "-g", location]
        rc, msg = run_hidden(e, args)
        return Result(rc == 0, msg or f"NordVPN কানেক্ট কমান্ড পাঠানো হয়েছে ({location})।")

    def disconnect(self):
        e = self.detect()
        if not e:
            return Result(False, "NordVPN পাওয়া যায়নি।")
        rc, msg = run_hidden(e, ["-d"])
        return Result(rc == 0, msg or "NordVPN ডিসকানেক্ট কমান্ড পাঠানো হয়েছে।")

    def status(self):
        return "Detected" if self.detect() else "Not installed"


PROVIDERS: dict[str, Provider] = {p.key: p for p in (PIA(), ExpressVPN(), ProtonVPN(), NordVPN())}


class CustomVPN(Provider):
    def __init__(self, key, label, executable):
        self.key, self.label, self.executable = key, label, executable

    def detect(self):
        return self.executable if Path(self.executable).is_file() else None

    def connect(self, location="Automatic"):
        exe = self.detect()
        if not exe:
            return Result(False, "নির্বাচিত VPN .exe ফাইলটি পাওয়া যায়নি।")
        try:
            subprocess.Popen([exe], creationflags=CREATE_NO_WINDOW)
            return Result(True, f"{self.label} ব্যাকগ্রাউন্ডে চালু করা হয়েছে।")
        except Exception as ex:
            return Result(False, str(ex))

    def disconnect(self):
        return Result(False, "কাস্টম ভিপিএন অ্যাপ থেকে ডিসকানেক্ট করুন।")

    def status(self):
        return "Custom App Ready" if self.detect() else "Not found"


def load_custom_vpns():
    data = load_settings()
    for item in data.get("custom_vpns", []):
        key, name, path = item.get("key"), item.get("name"), item.get("path")
        if key and name and path:
            PROVIDERS[key] = CustomVPN(key, name, path)


def save_custom_vpns():
    custom_list = [
        {"key": p.key, "name": p.label, "path": p.executable}
        for p in PROVIDERS.values()
        if isinstance(p, CustomVPN)
    ]
    save_settings({"custom_vpns": custom_list})


load_custom_vpns()


# ---------------------------------------------------------------------------
# CLI INTERFACE
# ---------------------------------------------------------------------------
def cli():
    ap = argparse.ArgumentParser(description=APP)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("providers")
    for action in ("status", "connect", "disconnect", "locations", "test"):
        a = sub.add_parser(action)
        a.add_argument("provider", choices=PROVIDERS.keys())
        if action == "connect":
            a.add_argument("--location", default="Automatic")
    args = ap.parse_args()
    if args.cmd == "providers":
        for k, p in PROVIDERS.items():
            print(f"{k:12} | {p.label:32} | {'DETECTED' if p.detect() else 'not detected'}")
        return 0
    p = PROVIDERS[args.provider]
    if args.cmd == "status":
        print(p.status())
        return 0
    if args.cmd == "test":
        r = p.test_connection_ready()
        print(r.message)
        return 0 if r.ok else 2
    if args.cmd == "locations":
        vals = p.locations()
        print("\n".join(vals) if vals else "No supported location list returned.")
        return 0
    if args.cmd == "connect":
        r = p.connect(args.location)
    else:
        r = p.disconnect()
    print(r.message)
    return 0 if r.ok else 2


# ---------------------------------------------------------------------------
# MACOS 3D GUI + EXACT TIMER + CITY BUTTON + MASTER ADMIN PANEL
# ---------------------------------------------------------------------------
THEMES = {
    "macOS Sonoma Dark (3D)": {
        "bg": "#0b0f19",
        "card": "#131b2e",
        "card_alt": "#18233c",
        "border": "#2b3d63",
        "accent": "#38bdf8",
        "accent_2": "#6366f1",
        "success": "#10b981",
        "danger": "#ef4444",
        "text": "#f1f5f9",
        "muted": "#94a3b8",
    },
    "macOS Finder Light (3D)": {
        "bg": "#eef2f6",
        "card": "#ffffff",
        "card_alt": "#f8fafc",
        "border": "#cbd5e1",
        "accent": "#0284c7",
        "accent_2": "#4f46e5",
        "success": "#059669",
        "danger": "#dc2626",
        "text": "#0f172a",
        "muted": "#475569",
    },
    "Cyber 3D Neon": {
        "bg": "#070510",
        "card": "#120d24",
        "card_alt": "#1b1438",
        "border": "#4c1d95",
        "accent": "#00f5d4",
        "accent_2": "#f72585",
        "success": "#00f59b",
        "danger": "#ff2a6d",
        "text": "#f8f9fa",
        "muted": "#a594f9",
    },
    "Emerald Glass 3D": {
        "bg": "#061512",
        "card": "#0d2621",
        "card_alt": "#13352e",
        "border": "#1f574c",
        "accent": "#34d399",
        "accent_2": "#10b981",
        "success": "#22c55e",
        "danger": "#f87171",
        "text": "#ecfdf5",
        "muted": "#6ee7b7",
    },
}


def launch_gui():
    from PySide6.QtCore import (
        QEasingCurve,
        QEvent,
        QPropertyAnimation,
        QRectF,
        Qt,
        QThread,
        QTimer,
        QUrl,
        Signal,
    )
    from PySide6.QtGui import (
        QAction,
        QColor,
        QConicalGradient,
        QDesktopServices,
        QFont,
        QIcon,
        QLinearGradient,
        QPainter,
        QPen,
        QPixmap,
    )
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QFileDialog,
        QFrame,
        QGraphicsDropShadowEffect,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QInputDialog,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMenu,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QRadioButton,
        QScrollArea,
        QSizeGrip,
        QSizePolicy,
        QSpinBox,
        QSystemTrayIcon,
        QTabWidget,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )

    OFFICIAL_DOWNLOADS = [
        ("PIA", "https://installers.privateinternetaccess.com/download/pia-windows-x64-3.8-08539.exe"),
        ("ExpressVPN", "https://www.expressvpn.com/latest"),
        ("Proton VPN", "https://api.github.com/repos/ProtonVPN/win-app/releases/latest"),
        ("NordVPN", "https://downloads.nordcdn.com/apps/windows/NordVPN/latest/NordInstaller.exe"),
    ]

    def create_3d_tray_icon(primary_hex: str = "#38bdf8", secondary_hex: str = "#6366f1") -> QIcon:
        pix = QPixmap(64, 64)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)

        outer = QRectF(4, 4, 56, 56)
        grad = QLinearGradient(outer.topLeft(), outer.bottomRight())
        grad.setColorAt(0.0, QColor(primary_hex))
        grad.setColorAt(1.0, QColor(secondary_hex))

        p.setBrush(grad)
        p.setPen(QPen(QColor("#ffffff"), 2.5))
        p.drawEllipse(outer)

        inner = QRectF(14, 14, 36, 36)
        core = QLinearGradient(inner.topLeft(), inner.bottomRight())
        core.setColorAt(0.0, QColor(15, 23, 42, 235))
        core.setColorAt(1.0, QColor(30, 41, 59, 235))
        p.setBrush(core)
        p.setPen(QPen(QColor(primary_hex), 2.0))
        p.drawEllipse(inner)

        p.setPen(QColor("#ffffff"))
        f = QFont("Segoe UI", 12, QFont.Black)
        p.setFont(f)
        p.drawText(inner, Qt.AlignCenter, "SB")
        p.end()
        return QIcon(pix)

    def add_3d_shadow(widget: QWidget, blur: int = 24, y_offset: int = 6, color_hex: str = "#000000"):
        shadow = QGraphicsDropShadowEffect(widget)
        shadow.setBlurRadius(blur)
        shadow.setOffset(0, y_offset)
        c = QColor(color_hex)
        c.setAlpha(135)
        shadow.setColor(c)
        widget.setGraphicsEffect(shadow)

    # -----------------------------------------------------------------------
    # CIRCULAR 3D CONNECTION ORB
    # -----------------------------------------------------------------------
    class CircularStatusOrb(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setFixedSize(155, 155)
            self.angle = 0
            self.spinning = False
            self.mode = "idle"
            self.headline = "READY"
            self.subline = "Standby"
            self.timer = QTimer(self)
            self.timer.timeout.connect(self._tick)
            self.timer.start(30)

        def set_state(self, mode: str, headline: str, subline: str = "", spinning: bool = False):
            self.mode = mode
            self.headline = headline
            self.subline = subline
            self.spinning = spinning
            self.update()

        def _tick(self):
            self.angle = (self.angle - (8 if self.spinning else 1)) % 360
            self.update()

        def paintEvent(self, event):
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            rect = QRectF(14, 14, self.width() - 28, self.height() - 28)

            palette = {
                "idle": ("#38bdf8", "#6366f1"),
                "connecting": ("#f59e0b", "#38bdf8"),
                "success": ("#10b981", "#34d399"),
                "failed": ("#ef4444", "#f97316"),
            }
            c1_hex, c2_hex = palette.get(self.mode, palette["idle"])

            track_pen = QPen(QColor(255, 255, 255, 28), 10)
            painter.setPen(track_pen)
            painter.drawEllipse(rect)

            grad = QConicalGradient(rect.center(), float(self.angle))
            grad.setColorAt(0.0, QColor(c1_hex))
            grad.setColorAt(0.5, QColor(c2_hex))
            grad.setColorAt(0.85, QColor(c1_hex).darker(180))
            grad.setColorAt(1.0, QColor(c1_hex))

            ring_pen = QPen(grad, 10)
            ring_pen.setCapStyle(Qt.RoundCap)
            painter.setPen(ring_pen)
            if self.spinning:
                painter.drawArc(rect, int(self.angle * 16), int(250 * 16))
            else:
                painter.drawEllipse(rect)

            inner_rect = rect.adjusted(12, 12, -12, -12)
            core_grad = QLinearGradient(inner_rect.topLeft(), inner_rect.bottomRight())
            core_grad.setColorAt(0.0, QColor(28, 40, 68, 230))
            core_grad.setColorAt(1.0, QColor(12, 18, 34, 240))
            painter.setBrush(core_grad)
            painter.setPen(QPen(QColor(255, 255, 255, 40), 1.5))
            painter.drawEllipse(inner_rect)

            painter.setPen(QColor("#ffffff"))
            painter.setFont(QFont("Segoe UI", 11, QFont.Bold))
            painter.drawText(inner_rect.adjusted(4, -10, -4, -10), Qt.AlignCenter, self.headline)

            painter.setPen(QColor(c1_hex))
            painter.setFont(QFont("Segoe UI", 8, QFont.DemiBold))
            painter.drawText(inner_rect.adjusted(4, 24, -4, 4), Qt.AlignCenter, self.subline)

    # -----------------------------------------------------------------------
    # MACOS 3D COUNTRY & CITY PICKER DIALOGS (COMPACT POPUPS)
    # -----------------------------------------------------------------------
    class MacCountryFinderDialog(QDialog):
        def __init__(self, parent, country_tree: dict[str, list[tuple[str, str]]]):
            super().__init__(parent)
            self.setWindowTitle("Select Country — macOS 3D Finder")
            self.resize(520, 440)
            self.selected_country: Optional[str] = None
            self.country_tree = country_tree

            layout = QVBoxLayout(self)
            layout.setContentsMargins(18, 18, 18, 18)
            layout.setSpacing(12)

            top = QHBoxLayout()
            for dot_color in ("#ff5f57", "#febc2e", "#28c840"):
                dot = QLabel("●")
                dot.setStyleSheet(f"color:{dot_color};font-size:16px;")
                top.addWidget(dot)
            hdr = QLabel("  🌍  Choose VPN Country (3D Finder)")
            hdr.setStyleSheet("font-size:15px;font-weight:800;")
            top.addWidget(hdr)
            top.addStretch()
            layout.addLayout(top)

            self.search = QLineEdit()
            self.search.setPlaceholderText("🔍  Search country (যেমন: Singapore, Indonesia, United States)...")
            self.search.textChanged.connect(self.populate)
            layout.addWidget(self.search)

            self.list_widget = QListWidget()
            self.list_widget.setSpacing(6)
            self.list_widget.itemClicked.connect(self._on_item_clicked)
            layout.addWidget(self.list_widget, 1)

            self.populate("")

            self.setWindowOpacity(0.0)
            self.anim = QPropertyAnimation(self, b"windowOpacity")
            self.anim.setDuration(200)
            self.anim.setStartValue(0.0)
            self.anim.setEndValue(1.0)
            self.anim.setEasingCurve(QEasingCurve.OutCubic)
            self.anim.start()

        def populate(self, query: str):
            self.list_widget.clear()
            q = query.strip().lower()
            for country, cities in self.country_tree.items():
                if q and q not in country.lower():
                    continue
                flag = COUNTRY_FLAGS.get(country, "🌐")
                item = QListWidgetItem(f"{flag}   {country}   •   ({len(cities)} Cities)")
                item.setData(Qt.UserRole, country)
                item.setFont(QFont("Segoe UI", 11, QFont.Bold))
                self.list_widget.addItem(item)

        def _on_item_clicked(self, item: QListWidgetItem):
            self.selected_country = item.data(Qt.UserRole)
            self.accept()

    class MacCityFinderDialog(QDialog):
        """Clean 3D Popup for selecting a City so city names don't clutter the front screen."""

        def __init__(self, parent, country: str, cities: list[tuple[str, str]]):
            super().__init__(parent)
            flag = COUNTRY_FLAGS.get(country, "🌐")
            self.setWindowTitle(f"Select City in {country}")
            self.resize(480, 400)
            self.selected_city: Optional[tuple[str, str]] = None
            self.cities = cities
            self.country = country

            layout = QVBoxLayout(self)
            layout.setContentsMargins(18, 18, 18, 18)
            layout.setSpacing(12)

            top = QHBoxLayout()
            for dot_color in ("#ff5f57", "#febc2e", "#28c840"):
                dot = QLabel("●")
                dot.setStyleSheet(f"color:{dot_color};font-size:16px;")
                top.addWidget(dot)
            hdr = QLabel(f"  {flag}  {country} — কোন সিটি কানেক্ট করতে চান?")
            hdr.setStyleSheet("font-size:15px;font-weight:800;")
            top.addWidget(hdr)
            top.addStretch()
            layout.addLayout(top)

            self.search = QLineEdit()
            self.search.setPlaceholderText(f"🔍  Search city in {country}...")
            self.search.textChanged.connect(self.populate)
            layout.addWidget(self.search)

            self.list_widget = QListWidget()
            self.list_widget.setSpacing(6)
            self.list_widget.itemClicked.connect(self._on_item_clicked)
            layout.addWidget(self.list_widget, 1)

            self.populate("")

            self.setWindowOpacity(0.0)
            self.anim = QPropertyAnimation(self, b"windowOpacity")
            self.anim.setDuration(200)
            self.anim.setStartValue(0.0)
            self.anim.setEndValue(1.0)
            self.anim.setEasingCurve(QEasingCurve.OutCubic)
            self.anim.start()

        def populate(self, query: str):
            self.list_widget.clear()
            q = query.strip().lower()
            for city_label, region_slug in self.cities:
                if q and q not in city_label.lower():
                    continue
                item = QListWidgetItem(f"🏙   {city_label}   ➔   [{region_slug}]")
                item.setData(Qt.UserRole, (city_label, region_slug))
                item.setFont(QFont("Segoe UI", 11, QFont.Bold))
                self.list_widget.addItem(item)

        def _on_item_clicked(self, item: QListWidgetItem):
            self.selected_city = item.data(Qt.UserRole)
            self.accept()

    # -----------------------------------------------------------------------
    # BACKGROUND WORKERS
    # -----------------------------------------------------------------------
    class ActionWorker(QThread):
        finished_result = Signal(bool, str, str)

        def __init__(self, provider: Provider, action: str, location: str = "Automatic"):
            super().__init__()
            self.provider = provider
            self.action = action
            self.location = location

        def run(self):
            if self.action == "connect":
                res = self.provider.connect(self.location)
            elif self.action == "disconnect":
                res = self.provider.disconnect()
            else:
                res = self.provider.test_connection_ready()
            self.finished_result.emit(res.ok, res.message, self.action)

    class DownloadWorker(QThread):
        progress = Signal(int, str)
        completed = Signal(str, str)
        failed = Signal(str, str)

        def __init__(self, name, url, folder):
            super().__init__()
            self.name, self.url, self.folder = name, url, folder
            self.cancel_requested = False

        def cancel(self):
            self.cancel_requested = True

        def run(self):
            try:
                url = self.url
                headers = {"User-Agent": f"SalmanBossVPNManager/{APP_VERSION}"}
                if self.name == "Proton VPN":
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=40) as response:
                        release = json.loads(response.read().decode("utf-8"))
                    assets = release.get("assets", [])
                    candidates = [
                        a
                        for a in assets
                        if a.get("name", "").lower().endswith(".exe")
                        and "arm" not in a.get("name", "").lower()
                    ]
                    if not candidates:
                        raise RuntimeError("Official Proton release did not provide a Windows EXE asset.")
                    candidates.sort(key=lambda a: ("x64" not in a.get("name", "").lower(), a.get("name", "")))
                    url = candidates[0]["browser_download_url"]

                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=60) as response:
                    final_url = response.geturl()
                    host = urllib.parse.urlparse(final_url).hostname or ""
                    trusted = (
                        host == "privateinternetaccess.com"
                        or host.endswith(".privateinternetaccess.com")
                        or host == "expressvpn.com"
                        or host.endswith(".expressvpn.com")
                        or host == "github.com"
                        or host.endswith(".githubusercontent.com")
                        or host == "nordcdn.com"
                        or host.endswith(".nordcdn.com")
                    )
                    if not trusted:
                        raise RuntimeError("Download redirect left the provider's trusted official domain.")
                    filename = response.headers.get_filename()
                    if not filename:
                        filename = Path(urllib.parse.urlparse(final_url).path).name
                    if not filename.lower().endswith(".exe"):
                        filename = {
                            "PIA": "pia-windows-installer.exe",
                            "ExpressVPN": "expressvpn-windows-installer.exe",
                            "Proton VPN": "protonvpn-windows-installer.exe",
                            "NordVPN": "nordvpn-windows-installer.exe",
                        }.get(self.name, "vpn-installer.exe")
                    self.folder.mkdir(parents=True, exist_ok=True)
                    destination = self.folder / filename
                    total = int(response.headers.get("Content-Length", "0") or 0)
                    received = 0
                    with open(destination, "wb") as output:
                        while True:
                            if self.cancel_requested:
                                output.close()
                                destination.unlink(missing_ok=True)
                                self.failed.emit(self.name, "Download cancelled.")
                                return
                            chunk = response.read(256 * 1024)
                            if not chunk:
                                break
                            output.write(chunk)
                            received += len(chunk)
                            percent = int(received * 100 / total) if total else 0
                            size_text = f"{received / 1048576:.1f} MB"
                            if total:
                                size_text += f" / {total / 1048576:.1f} MB"
                            self.progress.emit(percent, f"{self.name}: {percent}%  •  {size_text}")
                    if destination.stat().st_size < 100_000:
                        destination.unlink(missing_ok=True)
                        raise RuntimeError("The server response was too small to be a valid installer.")
                    self.completed.emit(self.name, str(destination))
            except Exception as exc:
                self.failed.emit(self.name, str(exc))

    # -----------------------------------------------------------------------
    # MAIN APPLICATION WINDOW
    # -----------------------------------------------------------------------
    class Window(QMainWindow):
        def __init__(self):
            super().__init__()
            self.saved_cfg = load_settings()
            self.current_theme_name = self.saved_cfg.get("theme", "macOS Sonoma Dark (3D)")
            if self.current_theme_name not in THEMES:
                self.current_theme_name = "macOS Sonoma Dark (3D)"

            self.is_master_admin_unlocked = bool(self.saved_cfg.get("master_admin_pc", False))
            self.admin_pin = str(self.saved_cfg.get("admin_pin", DEFAULT_ADMIN_PIN))
            self.last_notified_version = self.saved_cfg.get("last_notified_version", APP_VERSION)

            self.force_quit = False
            self.setWindowTitle(f"{APP} v{APP_VERSION} — Master 3D Edition")
            self.setWindowIcon(create_3d_tray_icon("#38bdf8", "#6366f1"))
            self.setMinimumSize(720, 560)
            self.resize(1020, 800)

            # Strict Timer State Variables (Fixes the 15-second premature disconnect bug)
            self.country_tree: dict[str, list[tuple[str, str]]] = {}
            self.selected_country: str = ""
            self.selected_city_label: str = ""
            self.selected_region_slug: str = "Automatic"
            self.timer_enabled: bool = False  # False = Unlimited (No auto-disconnect unless chosen)
            self.configured_minutes: int = 0
            self.remaining_seconds: int = 0
            self.is_reconnecting_cycle: bool = False
            self.active_worker: Optional[ActionWorker] = None

            central = QWidget()
            self.setCentralWidget(central)
            root_vbox = QVBoxLayout(central)
            root_vbox.setContentsMargins(14, 12, 14, 10)
            root_vbox.setSpacing(10)

            # macOS Header Bar
            header_frame = QFrame()
            header_frame.setObjectName("card3d")
            add_3d_shadow(header_frame, blur=20, y_offset=4)
            header_layout = QHBoxLayout(header_frame)
            header_layout.setContentsMargins(16, 12, 16, 12)

            dots_box = QHBoxLayout()
            for col in ("#ff5f57", "#febc2e", "#28c840"):
                lbl = QLabel("●")
                lbl.setStyleSheet(f"color:{col};font-size:18px;")
                dots_box.addWidget(lbl)
            header_layout.addLayout(dots_box)
            header_layout.addSpacing(10)

            brand_col = QVBoxLayout()
            self.title_lbl = QLabel("SALMAN BOSS  •  VPN MANAGER 3D")
            self.title_lbl.setObjectName("heroTitle")
            self.sub_lbl = QLabel(
                f"macOS 3D + ADMIN CONTROL  •  v{APP_VERSION}  •  "
                f"{'MASTER ADMIN PC' if self.is_master_admin_unlocked else 'CLIENT MODE'}"
            )
            self.sub_lbl.setObjectName("muted")
            brand_col.addWidget(self.title_lbl)
            brand_col.addWidget(self.sub_lbl)
            header_layout.addLayout(brand_col)
            header_layout.addStretch()

            self.quick_theme = QComboBox()
            self.quick_theme.addItems(list(THEMES.keys()))
            self.quick_theme.setCurrentText(self.current_theme_name)
            self.quick_theme.currentTextChanged.connect(self.apply_theme)
            header_layout.addWidget(self.quick_theme)

            self.tray_hide_btn = QPushButton("📥 Minimize to Tray")
            self.tray_hide_btn.clicked.connect(self.hide_to_system_tray)
            header_layout.addWidget(self.tray_hide_btn)

            self.update_btn = QPushButton("🔄 Update Check")
            self.update_btn.clicked.connect(lambda: self.check_remote_control_and_updates(manual=True))
            header_layout.addWidget(self.update_btn)

            root_vbox.addWidget(header_frame)

            # Remote Lock Banner (Shown on client PCs when Admin disables access)
            self.lock_banner = QFrame()
            self.lock_banner.setObjectName("dangerCard")
            lock_l = QHBoxLayout(self.lock_banner)
            self.lock_lbl = QLabel(
                "⛔ অ্যাডমিন (Salman Boss) এই সফটওয়্যারের অ্যাক্সেস সাময়িকভাবে বন্ধ রেখেছেন।"
            )
            self.lock_lbl.setStyleSheet("color:#ffffff;font-weight:800;font-size:14px;")
            lock_l.addWidget(self.lock_lbl, 1)
            self.lock_banner.setVisible(False)
            root_vbox.addWidget(self.lock_banner)

            # Main Tabs
            self.tabs = QTabWidget()
            root_vbox.addWidget(self.tabs, 1)

            # ==================== TAB 1: VPN DASHBOARD 3D ====================
            vpn_scroll = QScrollArea()
            vpn_scroll.setWidgetResizable(True)
            vpn_scroll.setFrameShape(QFrame.NoFrame)
            vpn_container = QWidget()
            self.vpn_layout = QVBoxLayout(vpn_container)
            self.vpn_layout.setContentsMargins(6, 6, 6, 6)
            self.vpn_layout.setSpacing(14)

            hero_card = QFrame()
            hero_card.setObjectName("card3d")
            add_3d_shadow(hero_card, blur=28, y_offset=6)
            hero_hbox = QHBoxLayout(hero_card)
            hero_hbox.setContentsMargins(20, 18, 20, 18)
            hero_hbox.setSpacing(24)

            orb_col = QVBoxLayout()
            orb_col.setAlignment(Qt.AlignCenter)
            self.orb = CircularStatusOrb()
            orb_col.addWidget(self.orb, 0, Qt.AlignCenter)
            self.timer_badge = QLabel("⏱ Timer: ♾ Unlimited")
            self.timer_badge.setAlignment(Qt.AlignCenter)
            self.timer_badge.setObjectName("badgeLabel")
            orb_col.addWidget(self.timer_badge)
            hero_hbox.addLayout(orb_col)

            ctrl_col = QVBoxLayout()
            ctrl_col.setSpacing(12)

            self.detect_lbl = QLabel("Scanning installed VPN providers…")
            self.detect_lbl.setObjectName("muted")
            ctrl_col.addWidget(self.detect_lbl)

            prov_row = QHBoxLayout()
            prov_lbl = QLabel("🛡 VPN Provider:")
            prov_lbl.setMinimumWidth(140)
            prov_lbl.setStyleSheet("font-weight:700;font-size:14px;")
            self.provider_combo = QComboBox()
            self.refresh_provider_list()
            self.provider_combo.currentIndexChanged.connect(self.on_provider_changed)
            prov_row.addWidget(prov_lbl)
            prov_row.addWidget(self.provider_combo, 1)
            ctrl_col.addLayout(prov_row)

            # COMPACT HALF-WIDTH COUNTRY BUTTON + COMPACT CITY BUTTON (No sprawling city list!)
            loc_row = QHBoxLayout()
            loc_lbl = QLabel("📁 Location & City:")
            loc_lbl.setMinimumWidth(140)
            loc_lbl.setStyleSheet("font-weight:700;font-size:14px;")

            self.country_folder_btn = QPushButton("📂  1. Select Country")
            self.country_folder_btn.setObjectName("macFolderBtn")
            self.country_folder_btn.setCursor(Qt.PointingHandCursor)
            self.country_folder_btn.setMinimumHeight(44)
            self.country_folder_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.country_folder_btn.clicked.connect(self.open_country_finder)

            # City Button (Shows as a clean 3D button right next to Country, not a huge list)
            self.city_folder_btn = QPushButton("🏙  2. City: Automatic")
            self.city_folder_btn.setObjectName("macCityBtn")
            self.city_folder_btn.setCursor(Qt.PointingHandCursor)
            self.city_folder_btn.setMinimumHeight(44)
            self.city_folder_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.city_folder_btn.clicked.connect(self.open_city_finder)

            reload_btn = QPushButton("↻ Reload")
            reload_btn.setFixedWidth(90)
            reload_btn.setMinimumHeight(44)
            reload_btn.clicked.connect(self.load_locations_for_provider)

            loc_row.addWidget(loc_lbl)
            loc_row.addWidget(self.country_folder_btn, 1)
            loc_row.addWidget(self.city_folder_btn, 1)
            loc_row.addWidget(reload_btn)
            ctrl_col.addLayout(loc_row)

            # Action Buttons Row
            act_row = QHBoxLayout()
            self.btn_connect = QPushButton("⚡ CONNECT VPN")
            self.btn_connect.setObjectName("primaryBtn")
            self.btn_connect.setMinimumHeight(42)
            self.btn_connect.clicked.connect(self.start_connect_flow)

            self.btn_disconnect = QPushButton("⏹ DISCONNECT")
            self.btn_disconnect.setObjectName("dangerBtn")
            self.btn_disconnect.setMinimumHeight(42)
            self.btn_disconnect.clicked.connect(self.start_disconnect_flow)

            self.btn_test = QPushButton("🧪 TEST VPN")
            self.btn_test.setObjectName("accentBtn")
            self.btn_test.setMinimumHeight(42)
            self.btn_test.clicked.connect(self.start_test_flow)

            self.btn_add_custom = QPushButton("＋ Add VPN")
            self.btn_add_custom.setMinimumHeight(42)
            self.btn_add_custom.clicked.connect(self.add_custom_vpn)

            act_row.addWidget(self.btn_connect)
            act_row.addWidget(self.btn_disconnect)
            act_row.addWidget(self.btn_test)
            act_row.addWidget(self.btn_add_custom)
            ctrl_col.addLayout(act_row)

            hero_hbox.addLayout(ctrl_col, 1)
            self.vpn_layout.addWidget(hero_card)

            # STEP 3 CARD: STRICT CONNECTION TIMER (Only activates what you explicitly choose!)
            self.duration_card = QFrame()
            self.duration_card.setObjectName("stepCard")
            add_3d_shadow(self.duration_card, blur=22, y_offset=5)
            dur_vbox = QVBoxLayout(self.duration_card)
            self.dur_title = QLabel(
                "⏱ Step 3: কত মিনিটের জন্য কানেক্ট করতে চান? (নির্ধারিত সময়ের ১ সেকেন্ড আগেও ডিসকানেক্ট হবে না)"
            )
            self.dur_title.setObjectName("stepTitle")
            dur_vbox.addWidget(self.dur_title)

            dur_row = QHBoxLayout()
            btn_unlimited = QPushButton("♾ Unlimited (অটো অফ হবে না)")
            btn_unlimited.clicked.connect(lambda: self.select_duration(0))
            dur_row.addWidget(btn_unlimited)

            for mins in (5, 10, 15, 30, 60):
                b = QPushButton(f"⏳ {mins} মিনিট")
                b.clicked.connect(lambda checked=False, m=mins: self.select_duration(m))
                dur_row.addWidget(b)

            dur_row.addSpacing(8)
            dur_row.addWidget(QLabel("Custom (Min):"))
            self.custom_min_spin = QSpinBox()
            self.custom_min_spin.setRange(1, 1440)
            self.custom_min_spin.setValue(15)
            dur_row.addWidget(self.custom_min_spin)

            apply_custom_min = QPushButton("Set Time")
            apply_custom_min.clicked.connect(lambda: self.select_duration(self.custom_min_spin.value()))
            dur_row.addWidget(apply_custom_min)
            dur_vbox.addLayout(dur_row)
            self.duration_card.setVisible(False)
            self.vpn_layout.addWidget(self.duration_card)

            # STEP 4 CARD: ROTATION / RECONNECT OPTION MODE
            self.mode_card = QFrame()
            self.mode_card.setObjectName("stepCard")
            add_3d_shadow(self.mode_card, blur=22, y_offset=5)
            mode_vbox = QVBoxLayout(self.mode_card)
            mode_title = QLabel("🔄 Step 4: Option Mode — আপনার দেওয়া সময় পূর্ণ হলে কী হবে?")
            mode_title.setObjectName("stepTitle")
            mode_vbox.addWidget(mode_title)

            self.radio_same_country_loop = QRadioButton(
                "🔁 Same Country & City Loop — নির্ধারিত সময় শেষ হলে অফ হয়ে আবার একই কান্ট্রি ও সিটিতে কানেক্ট হবে"
            )
            self.radio_rotate_country = QRadioButton(
                "🌍 Auto Country Rotation — নির্ধারিত সময় শেষ হলে স্বয়ংক্রিয়ভাবে অন্য কান্ট্রি ও সিটিতে চেঞ্জ হবে"
            )
            self.radio_single_disconnect = QRadioButton(
                "⏹ One-Time Disconnect — নির্ধারিত সময় শেষ হলে ভিপিএন ডিসকানেক্ট হয়ে বন্ধ থাকবে"
            )
            self.radio_same_country_loop.setChecked(True)

            mode_vbox.addWidget(self.radio_same_country_loop)
            mode_vbox.addWidget(self.radio_rotate_country)
            mode_vbox.addWidget(self.radio_single_disconnect)

            launch_session_btn = QPushButton("🚀 CONNECT WITH SELECTED TIMER NOW")
            launch_session_btn.setObjectName("primaryBtn")
            launch_session_btn.setMinimumHeight(42)
            launch_session_btn.clicked.connect(self.start_connect_flow)
            mode_vbox.addWidget(launch_session_btn)

            self.mode_card.setVisible(False)
            self.vpn_layout.addWidget(self.mode_card)

            # Activity Log Panel
            log_card = QFrame()
            log_card.setObjectName("card3d")
            log_vbox = QVBoxLayout(log_card)
            log_hdr = QLabel("📋 Live Connection & Timer Console")
            log_hdr.setStyleSheet("font-weight:700;")
            self.log = QTextEdit()
            self.log.setReadOnly(True)
            self.log.setMinimumHeight(110)
            log_vbox.addWidget(log_hdr)
            log_vbox.addWidget(self.log)
            self.vpn_layout.addWidget(log_card)

            vpn_scroll.setWidget(vpn_container)
            self.tabs.addTab(vpn_scroll, "🚀 VPN Dashboard 3D")

            # ==================== TAB 2: DOWNLOAD CENTER (FIXED UNCUT LAYOUT) ====================
            dl_scroll = QScrollArea()
            dl_scroll.setWidgetResizable(True)
            dl_scroll.setFrameShape(QFrame.NoFrame)
            downloads = QWidget()
            dl = QVBoxLayout(downloads)
            dl.setContentsMargins(10, 10, 10, 10)
            dl.setSpacing(14)

            intro = QLabel("⬇ OFFICIAL VPN DOWNLOAD CENTER")
            intro.setStyleSheet("font-size:18px;font-weight:800;")
            note = QLabel(
                "যেকোনো Download বাটনে ক্লিক করলে অফিসিয়াল ইনস্টলার সরাসরি এই অ্যাপের ভেতরেই "
                "Downloads/SalmanBossVPN ফোল্ডারে নামবে।"
            )
            note.setObjectName("muted")
            note.setWordWrap(True)
            dl.addWidget(intro)
            dl.addWidget(note)

            self.download_folder = Path.home() / "Downloads" / "SalmanBossVPN"
            self.download_workers = {}
            self.download_rows = {}

            group = QGroupBox("Official VPN Installers")
            gl = QGridLayout(group)
            gl.setSpacing(14)
            gl.setContentsMargins(14, 20, 14, 14)

            for i, (name, url) in enumerate(OFFICIAL_DOWNLOADS):
                card = QFrame()
                card.setObjectName("card3d")
                card.setMinimumHeight(195)  # Prevents any text or button from cutting off!
                cv = QVBoxLayout(card)
                cv.setContentsMargins(16, 14, 16, 14)
                cv.setSpacing(8)

                t_lbl = QLabel(f"🛡 {name} Official Installer")
                t_lbl.setStyleSheet("font-weight:800;font-size:15px;")
                t_lbl.setMinimumHeight(24)

                btn = QPushButton(f"⬇  Download {name}")
                btn.setObjectName("primaryBtn")
                btn.setMinimumHeight(40)

                bar = QProgressBar()
                bar.setRange(0, 100)
                bar.setValue(0)
                bar.setMinimumHeight(22)

                status = QLabel("Ready to download")
                status.setObjectName("muted")
                status.setMinimumHeight(20)

                cancel = QPushButton("✖ Cancel Download")
                cancel.setMinimumHeight(34)
                cancel.setEnabled(False)

                btn.clicked.connect(lambda checked=False, n=name, u=url: self.start_download(n, u))
                cancel.clicked.connect(lambda checked=False, n=name: self.cancel_download(n))

                cv.addWidget(t_lbl)
                cv.addWidget(btn)
                cv.addWidget(bar)
                cv.addWidget(status)
                cv.addWidget(cancel)
                gl.addWidget(card, i // 2, i % 2)
                self.download_rows[name] = (bar, status, cancel, btn)

            dl.addWidget(group)

            self.download_history = QListWidget()
            self.download_history.setMinimumHeight(110)
            dl.addWidget(QLabel("📂 Download History:"))
            dl.addWidget(self.download_history)

            dl_scroll.setWidget(downloads)
            self.tabs.addTab(dl_scroll, "⬇ Download Center")

            # ==================== TAB 3: MASTER ADMIN PANEL (PIN PROTECTED) ====================
            admin_scroll = QScrollArea()
            admin_scroll.setWidgetResizable(True)
            admin_scroll.setFrameShape(QFrame.NoFrame)
            admin_tab = QWidget()
            adm_layout = QVBoxLayout(admin_tab)
            adm_layout.setContentsMargins(10, 10, 10, 10)
            adm_layout.setSpacing(14)

            # Lock Screen Card for Admin Tab
            self.admin_lock_card = QFrame()
            self.admin_lock_card.setObjectName("card3d")
            lock_vbox = QVBoxLayout(self.admin_lock_card)
            lock_vbox.setContentsMargins(24, 24, 24, 24)
            lock_vbox.setSpacing(12)

            lock_title = QLabel("🔐 SALMAN BOSS — MASTER ADMIN PANEL (PIN REQUIRED)")
            lock_title.setStyleSheet("font-size:18px;font-weight:900;")
            lock_desc = QLabel(
                "এই প্যানেলটি শুধুমাত্র মেইন অ্যাডমিনের (Salman Boss) জন্য সংরক্ষিত। "
                "পিন কোড দিয়ে আনলক করলে আপনি অন্য সব পিসির সফটওয়্যার অফ/অন (Kill-Switch) করতে পারবেন এবং নতুন আপডেট পুশ করতে পারবেন।"
            )
            lock_desc.setObjectName("muted")
            lock_desc.setWordWrap(True)

            pin_row = QHBoxLayout()
            self.pin_input = QLineEdit()
            self.pin_input.setEchoMode(QLineEdit.Password)
            self.pin_input.setPlaceholderText("🔑 Enter Admin PIN Code (Default: 3579)...")
            self.pin_input.setMinimumHeight(40)
            unlock_btn = QPushButton("🔓 Unlock Master Admin Panel")
            unlock_btn.setObjectName("primaryBtn")
            unlock_btn.setMinimumHeight(40)
            unlock_btn.clicked.connect(self.unlock_admin_panel)
            pin_row.addWidget(self.pin_input, 1)
            pin_row.addWidget(unlock_btn)

            lock_vbox.addWidget(lock_title)
            lock_vbox.addWidget(lock_desc)
            lock_vbox.addLayout(pin_row)
            adm_layout.addWidget(self.admin_lock_card)

            # Unlocked Master Control Center
            self.admin_control_card = QFrame()
            self.admin_control_card.setObjectName("stepCard")
            ctrl_vbox = QVBoxLayout(self.admin_control_card)
            ctrl_vbox.setContentsMargins(20, 20, 20, 20)
            ctrl_vbox.setSpacing(14)

            adm_hdr = QLabel("👑 MASTER SERVER & REMOTE ACCESS CONTROL CENTER")
            adm_hdr.setStyleSheet("font-size:18px;font-weight:900;")
            ctrl_vbox.addWidget(adm_hdr)

            self.chk_master_pc = QCheckBox(
                "✅ এটি আমার মেইন অ্যাডমিন পিসি (Master PC) — রিমোট লক করলেও আমার পিসিতে সবসময় কাজ চলবে"
            )
            self.chk_master_pc.setChecked(self.is_master_admin_unlocked)
            self.chk_master_pc.toggled.connect(self.toggle_master_pc_mode)
            ctrl_vbox.addWidget(self.chk_master_pc)

            # 1. Remote Kill-Switch
            kill_box = QGroupBox("1. Global Client Access Switch (অন্যান্য পিসিতে সফটওয়্যার চালু/বন্ধ করুন)")
            kill_l = QHBoxLayout(kill_box)
            self.btn_allow_all = QPushButton("🟢 ALLOW ALL CLIENTS (সবার পিসিতে সফটওয়্যার চালু রাখুন)")
            self.btn_allow_all.setObjectName("accentBtn")
            self.btn_allow_all.setMinimumHeight(42)
            self.btn_allow_all.clicked.connect(lambda: self.admin_set_client_access(True))

            self.btn_block_all = QPushButton("🔴 TURN OFF ALL CLIENTS (সবার পিসিতে সফটওয়্যার বন্ধ করে দিন)")
            self.btn_block_all.setObjectName("dangerBtn")
            self.btn_block_all.setMinimumHeight(42)
            self.btn_block_all.clicked.connect(lambda: self.admin_set_client_access(False))

            kill_l.addWidget(self.btn_allow_all)
            kill_l.addWidget(self.btn_block_all)
            ctrl_vbox.addWidget(kill_box)

            # 2. Push Update & Broadcast Notification
            upd_box = QGroupBox("2. Push Update & Broadcast Notification to All User PCs")
            upd_grid = QGridLayout(upd_box)

            cur_state = load_control_state()
            upd_grid.addWidget(QLabel("New Version Number:"), 0, 0)
            self.adm_ver_input = QLineEdit(cur_state.get("latest_version", "0.8.5"))
            upd_grid.addWidget(self.adm_ver_input, 0, 1)

            upd_grid.addWidget(QLabel("Update Notification Text:"), 1, 0)
            self.adm_msg_input = QLineEdit(cur_state.get("update_message", "নতুন আপডেট এসেছে! এখনই আপডেট করুন।"))
            upd_grid.addWidget(self.adm_msg_input, 1, 1)

            upd_grid.addWidget(QLabel("Direct Update .py / .exe URL (Optional):"), 2, 0)
            self.adm_script_url = QLineEdit(cur_state.get("update_script_url", ""))
            self.adm_script_url.setPlaceholderText("https://.../Salman_Boss_VPN_Manager_v0_5_DirectDownload.py")
            upd_grid.addWidget(self.adm_script_url, 2, 1)

            upd_grid.addWidget(QLabel("Remote Cloud JSON Control URL (Optional):"), 3, 0)
            self.adm_cloud_url = QLineEdit(self.saved_cfg.get("remote_control_url", ""))
            self.adm_cloud_url.setPlaceholderText("https://gist.githubusercontent.com/.../raw/salman_admin_control.json")
            upd_grid.addWidget(self.adm_cloud_url, 3, 1)

            push_upd_btn = QPushButton("🚀 PUSH UPDATE & SAVE ADMIN CONTROL STATE NOW")
            push_upd_btn.setObjectName("primaryBtn")
            push_upd_btn.setMinimumHeight(42)
            push_upd_btn.clicked.connect(self.admin_push_update_now)
            upd_grid.addWidget(push_upd_btn, 4, 0, 1, 2)

            ctrl_vbox.addWidget(upd_box)

            # 3. Change Admin PIN
            pin_change_row = QHBoxLayout()
            self.new_pin_input = QLineEdit()
            self.new_pin_input.setPlaceholderText("New Admin PIN...")
            btn_change_pin = QPushButton("🔑 Change Admin PIN")
            btn_change_pin.clicked.connect(self.admin_change_pin)
            pin_change_row.addWidget(QLabel("Change PIN:"))
            pin_change_row.addWidget(self.new_pin_input, 1)
            pin_change_row.addWidget(btn_change_pin)
            ctrl_vbox.addLayout(pin_change_row)

            self.admin_control_card.setVisible(self.is_master_admin_unlocked)
            adm_layout.addWidget(self.admin_control_card)
            adm_layout.addStretch()

            admin_scroll.setWidget(admin_tab)
            self.tabs.addTab(admin_scroll, "🔐 Admin Panel")

            # ==================== TAB 4: SETTINGS, SYSTEM TRAY & RESIZE ====================
            settings_tab = QWidget()
            st_layout = QVBoxLayout(settings_tab)
            st_card = QFrame()
            st_card.setObjectName("card3d")
            st_vbox = QVBoxLayout(st_card)
            st_vbox.setSpacing(14)

            st_title = QLabel("⚙ অ্যাপ সেটিংস, নোটিফিকেশন, System Tray ও রিসাইজ কন্ট্রোল")
            st_title.setStyleSheet("font-size:18px;font-weight:800;")
            st_vbox.addWidget(st_title)

            size_row = QHBoxLayout()
            size_row.addWidget(QLabel("🖥 Quick Window Size:"))
            for lbl_txt, w, h in [
                ("Compact (740×580)", 740, 580),
                ("Standard (1020×800)", 1020, 800),
                ("Wide 3D (1240×880)", 1240, 880),
            ]:
                b_sz = QPushButton(lbl_txt)
                b_sz.clicked.connect(lambda checked=False, rw=w, rh=h: self.resize(rw, rh))
                size_row.addWidget(b_sz)
            st_vbox.addLayout(size_row)

            self.chk_minimize_to_tray = QCheckBox(
                "📥 Minimize বা Close (✕) করলে অ্যাপ বন্ধ না হয়ে System Tray-তে ব্যাকগ্রাউন্ডে চালু থাকবে"
            )
            self.chk_minimize_to_tray.setChecked(self.saved_cfg.get("minimize_to_tray", True))
            self.chk_minimize_to_tray.toggled.connect(lambda v: save_settings({"minimize_to_tray": v}))

            self.chk_desktop_notify = QCheckBox(
                "🔔 কানেক্ট, ডিসকানেক্ট, আপডেট এবং রোটেশনের সময় Windows Desktop Notification দেখান"
            )
            self.chk_desktop_notify.setChecked(self.saved_cfg.get("desktop_notify", True))
            self.chk_desktop_notify.toggled.connect(lambda v: save_settings({"desktop_notify": v}))

            self.chk_sound_alert = QCheckBox(
                "🔊 কানেক্ট বা ডিসকানেক্ট হওয়ার সময় সাউন্ড অ্যালার্ট (Sound Chime) বাজান"
            )
            self.chk_sound_alert.setChecked(self.saved_cfg.get("sound_alert", True))
            self.chk_sound_alert.toggled.connect(lambda v: save_settings({"sound_alert": v}))

            self.chk_always_top = QCheckBox("📌 Keep Window Always on Top (সব উইন্ডোর ওপরে রাখুন)")
            self.chk_always_top.toggled.connect(self.toggle_always_on_top)

            st_vbox.addWidget(self.chk_minimize_to_tray)
            st_vbox.addWidget(self.chk_desktop_notify)
            st_vbox.addWidget(self.chk_sound_alert)
            st_vbox.addWidget(self.chk_always_top)

            btn_row_st = QHBoxLayout()
            repair_btn = QPushButton("🔧 Auto-Configure VPN Paths & Permissions")
            repair_btn.setObjectName("accentBtn")
            repair_btn.clicked.connect(self.run_background_repair)

            quit_full_btn = QPushButton("🚪 Quit App Completely")
            quit_full_btn.setObjectName("dangerBtn")
            quit_full_btn.clicked.connect(self.quit_application_completely)

            btn_row_st.addWidget(repair_btn)
            btn_row_st.addWidget(quit_full_btn)
            st_vbox.addLayout(btn_row_st)

            st_vbox.addStretch()
            st_layout.addWidget(st_card)
            self.tabs.addTab(settings_tab, "⚙ Settings & Tray")

            # ==================== FOOTER: TELEGRAM + WHATSAPP (NUMBER HIDDEN IN LINK) ====================
            footer = QHBoxLayout()
            credit = QLabel("POWERED BY SALMAN BOSS  •  macOS 3D + MASTER CONTROL")
            credit.setObjectName("muted")

            tg_btn = QPushButton("💬 @Salman3579")
            tg_btn.setCursor(Qt.PointingHandCursor)
            tg_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(TELEGRAM_URL)))

            wa_btn = QPushButton("🟢 WhatsApp Support")
            wa_btn.setObjectName("whatsappBtn")
            wa_btn.setCursor(Qt.PointingHandCursor)
            wa_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(WHATSAPP_URL)))

            footer.addWidget(credit)
            footer.addStretch()
            footer.addWidget(wa_btn)
            footer.addWidget(tg_btn)
            grip = QSizeGrip(self)
            footer.addWidget(grip, 0, Qt.AlignBottom | Qt.AlignRight)
            root_vbox.addLayout(footer)

            # Initialize System Tray Icon
            self._init_system_tray()

            # Exact 1-Second Session Timer
            self.session_timer = QTimer(self)
            self.session_timer.setInterval(1000)
            self.session_timer.timeout.connect(self._on_session_second)

            # Background Provider Scanner (Every 12s — strictly passive, NEVER disconnects VPN)
            self.poll_timer = QTimer(self)
            self.poll_timer.timeout.connect(self.scan_providers)
            self.poll_timer.start(12000)

            # Remote Admin Kill-Switch & Live Update Watcher (Every 25s)
            self.remote_watch_timer = QTimer(self)
            self.remote_watch_timer.timeout.connect(lambda: self.check_remote_control_and_updates(manual=False))
            self.remote_watch_timer.start(25000)

            self.apply_theme(self.current_theme_name)
            self.load_locations_for_provider()
            self.scan_providers()
            QTimer.singleShot(1500, lambda: self.check_remote_control_and_updates(manual=False))

        # -------------------------------------------------------------------
        # MASTER ADMIN PANEL & REMOTE KILL-SWITCH / AUTO-UPDATE LOGIC
        # -------------------------------------------------------------------
        def unlock_admin_panel(self):
            entered = self.pin_input.text().strip()
            if entered == self.admin_pin:
                self.is_master_admin_unlocked = True
                self.chk_master_pc.setChecked(True)
                save_settings({"master_admin_pc": True})
                self.admin_control_card.setVisible(True)
                self.sub_lbl.setText(f"macOS 3D + ADMIN CONTROL  •  v{APP_VERSION}  •  MASTER ADMIN PC")
                self._apply_lock_ui(False, "")
                QMessageBox.information(
                    self,
                    "Master Admin Unlocked",
                    "স্বাগতম Salman Boss! মেইন অ্যাডমিন প্যানেল আনলক হয়েছে এবং এই পিসিটি Master PC হিসেবে সেট হয়েছে।",
                )
            else:
                QMessageBox.warning(self, "Wrong PIN", "ভুল পিন কোড! সঠিক অ্যাডমিন পিন দিন।")

        def toggle_master_pc_mode(self, checked: bool):
            self.is_master_admin_unlocked = checked
            save_settings({"master_admin_pc": checked})
            self.sub_lbl.setText(
                f"macOS 3D + ADMIN CONTROL  •  v{APP_VERSION}  •  "
                f"{'MASTER ADMIN PC' if checked else 'CLIENT MODE'}"
            )

        def admin_set_client_access(self, enabled: bool):
            state = load_control_state()
            state["app_enabled"] = enabled
            save_control_state(state)
            status_str = "চালু (ACTIVE)" if enabled else "বন্ধ (LOCKED / DISABLED)"
            self.log.append(f"[ADMIN CONTROL] অন্য সব পিসির জন্য সফটওয়্যার অ্যাক্সেস {status_str} করা হয়েছে।")
            self.send_notification("👑 Admin Control Updated", f"ক্লায়েন্ট অ্যাক্সেস এখন: {status_str}", "info")
            QMessageBox.information(
                self,
                "Client Access Updated",
                f"অন্যান্য পিসির জন্য সফটওয়্যার অ্যাক্সেস সফলভাবে {status_str} করা হয়েছে!\n"
                "(আপনার Master PC-তে কাজ স্বাভাবিকভাবে চলতে থাকবে।)",
            )

        def admin_push_update_now(self):
            new_ver = self.adm_ver_input.text().strip() or APP_VERSION
            new_msg = self.adm_msg_input.text().strip()
            script_url = self.adm_script_url.text().strip()
            cloud_url = self.adm_cloud_url.text().strip()

            save_settings({"remote_control_url": cloud_url})
            state = load_control_state()
            state["latest_version"] = new_ver
            state["update_message"] = new_msg
            state["update_script_url"] = script_url
            save_control_state(state)

            self.log.append(f"[ADMIN PUSH] নতুন ভার্সন v{new_ver} সব পিসির জন্য ব্রডকাস্ট করা হয়েছে।")
            self.send_notification(
                "🚀 Update Pushed to All PCs",
                f"ভার্সন v{new_ver} সফলভাবে রিলিজ করা হয়েছে। ক্লায়েন্ট পিসিগুলোতে নোটিফিকেশন চলে যাবে।",
                "success",
            )
            QMessageBox.information(
                self,
                "Update Broadcasted",
                f"ভার্সন v{new_ver} সফলভাবে সেভ ও পুশ করা হয়েছে!\n"
                "যাদের পিসিতে সফটওয়্যারটি আছে তাদের কাছে নিউ আপডেট নোটিফিকেশন শো করবে।",
            )

        def admin_change_pin(self):
            np = self.new_pin_input.text().strip()
            if len(np) < 4:
                QMessageBox.warning(self, "PIN", "কমপক্ষে ৪ সংখ্যার পিন দিন।")
                return
            self.admin_pin = np
            save_settings({"admin_pin": np})
            self.new_pin_input.clear()
            QMessageBox.information(self, "PIN Updated", "অ্যাডমিন পিন সফলভাবে পরিবর্তন করা হয়েছে।")

        def _apply_lock_ui(self, locked: bool, message: str):
            self.lock_banner.setVisible(locked)
            if message:
                self.lock_lbl.setText(message)
            self.btn_connect.setEnabled(not locked)
            self.country_folder_btn.setEnabled(not locked)
            self.city_folder_btn.setEnabled(not locked)
            self.provider_combo.setEnabled(not locked)

        def check_remote_control_and_updates(self, manual: bool = False):
            state = load_control_state()
            app_enabled = bool(state.get("app_enabled", True))
            latest_ver = str(state.get("latest_version", APP_VERSION)).strip()
            upd_msg = str(state.get("update_message", "নতুন আপডেট এসেছে!"))
            script_url = str(state.get("update_script_url", "")).strip()
            lock_msg = str(state.get("lock_message", "⛔ অ্যাডমিন এই সফটওয়্যারের অ্যাক্সেস বন্ধ রেখেছেন।"))

            # 1. Check Remote Kill-Switch (Master Admin PC is never blocked)
            if not app_enabled and not self.is_master_admin_unlocked:
                self._apply_lock_ui(True, lock_msg)
                if self.session_timer.isActive():
                    self.start_disconnect_flow()
                self.send_notification("⛔ Software Access Disabled", lock_msg, "failed")
                return
            else:
                self._apply_lock_ui(False, "")

            # 2. Check for New Update Broadcast
            if latest_ver != APP_VERSION and (manual or latest_ver != self.last_notified_version):
                self.last_notified_version = latest_ver
                save_settings({"last_notified_version": latest_ver})
                self.send_notification(
                    f"🔔 New Update Available (v{latest_ver})",
                    upd_msg,
                    "info",
                )
                ans = QMessageBox.question(
                    self,
                    f"🔔 New Update Available — v{latest_ver}",
                    f"নতুন আপডেট এসেছে!\n\n"
                    f"বর্তমান ভার্সন: v{APP_VERSION}\n"
                    f"নতুন ভার্সন: v{latest_ver}\n\n"
                    f"বার্তা: {upd_msg}\n\n"
                    f"আপনি কি এখনই অটোমেটিক আপডেট করতে চান?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if ans == QMessageBox.Yes:
                    self.perform_auto_update(latest_ver, script_url)
            elif manual:
                QMessageBox.information(
                    self,
                    "Up to Date",
                    f"আপনি সর্বশেষ ভার্সন (v{APP_VERSION}) ব্যবহার করছেন।",
                )

        def perform_auto_update(self, target_version: str, script_url: str):
            global APP_VERSION
            try:
                if script_url.startswith(("http://", "https://")):
                    req = urllib.request.Request(script_url, headers={"User-Agent": "SalmanBossVPNUpdater"})
                    with urllib.request.urlopen(req, timeout=25) as resp:
                        new_code = resp.read()
                    if len(new_code) > 500:
                        Path(__file__).resolve().write_bytes(new_code)
                APP_VERSION = target_version
                self.setWindowTitle(f"{APP} v{APP_VERSION} — Master 3D Edition")
                self.load_locations_for_provider()
                self.send_notification(
                    "✅ Auto-Update Complete",
                    f"সফটওয়্যারটি সফলভাবে v{target_version}-এ আপডেট হয়েছে!",
                    "success",
                )
                QMessageBox.information(
                    self,
                    "Update Successful",
                    f"Salman Boss VPN Manager সফলভাবে v{target_version}-এ আপডেট হয়েছে!",
                )
            except Exception as exc:
                QMessageBox.warning(self, "Auto-Update Error", f"আপডেট ডাউনলোডে সমস্যা হয়েছে: {exc}")

        # -------------------------------------------------------------------
        # SYSTEM TRAY & NOTIFICATION ENGINE
        # -------------------------------------------------------------------
        def _init_system_tray(self):
            self.tray_icon = QSystemTrayIcon(self)
            self.tray_icon.setIcon(create_3d_tray_icon("#38bdf8", "#6366f1"))
            self.tray_icon.setToolTip(f"{APP} v{APP_VERSION} — Standby")

            tray_menu = QMenu(self)
            act_show = QAction("🖥 Show / Restore Window", self)
            act_show.triggered.connect(self.restore_from_tray)

            act_connect = QAction("⚡ Quick Connect VPN", self)
            act_connect.triggered.connect(self.start_connect_flow)

            act_disconnect = QAction("⏹ Disconnect VPN", self)
            act_disconnect.triggered.connect(self.start_disconnect_flow)

            act_test = QAction("🧪 Test VPN Status", self)
            act_test.triggered.connect(self.start_test_flow)

            act_quit = QAction("🚪 Exit Completely", self)
            act_quit.triggered.connect(self.quit_application_completely)

            tray_menu.addAction(act_show)
            tray_menu.addSeparator()
            tray_menu.addAction(act_connect)
            tray_menu.addAction(act_disconnect)
            tray_menu.addAction(act_test)
            tray_menu.addSeparator()
            tray_menu.addAction(act_quit)

            self.tray_icon.setContextMenu(tray_menu)
            self.tray_icon.activated.connect(self._on_tray_activated)
            self.tray_icon.show()

        def _update_tray_appearance(self, mode: str, status_text: str):
            palette = {
                "idle": ("#38bdf8", "#6366f1"),
                "connecting": ("#f59e0b", "#38bdf8"),
                "success": ("#10b981", "#059669"),
                "failed": ("#ef4444", "#dc2626"),
            }
            c1, c2 = palette.get(mode, palette["idle"])
            icon = create_3d_tray_icon(c1, c2)
            self.tray_icon.setIcon(icon)
            self.setWindowIcon(icon)
            self.tray_icon.setToolTip(f"{APP} — {status_text}")

        def send_notification(self, title: str, message: str, kind: str = "info"):
            play_sound_alert(kind, enabled=self.chk_sound_alert.isChecked())
            if not self.chk_desktop_notify.isChecked():
                return
            if self.tray_icon and self.tray_icon.isVisible():
                icon_type = QSystemTrayIcon.Information
                if kind == "failed":
                    icon_type = QSystemTrayIcon.Critical
                elif kind == "warning":
                    icon_type = QSystemTrayIcon.Warning
                self.tray_icon.showMessage(title, message, icon_type, 4500)

        def _on_tray_activated(self, reason):
            if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
                if self.isVisible() and not self.isMinimized():
                    self.hide_to_system_tray()
                else:
                    self.restore_from_tray()

        def hide_to_system_tray(self):
            self.hide()
            self.send_notification(
                "Salman Boss VPN Manager (Running in Tray)",
                "অ্যাপটি System Tray-তে চালু আছে।",
                "info",
            )

        def restore_from_tray(self):
            self.showNormal()
            self.activateWindow()
            self.raise_()

        def changeEvent(self, event):
            if event.type() == QEvent.WindowStateChange:
                if self.isMinimized() and self.chk_minimize_to_tray.isChecked():
                    event.ignore()
                    QTimer.singleShot(0, self.hide_to_system_tray)
                    return
            super().changeEvent(event)

        def closeEvent(self, event):
            if not self.force_quit and self.chk_minimize_to_tray.isChecked():
                event.ignore()
                self.hide_to_system_tray()
            else:
                self.tray_icon.hide()
                event.accept()

        def quit_application_completely(self):
            self.force_quit = True
            self.session_timer.stop()
            self.poll_timer.stop()
            self.remote_watch_timer.stop()
            self.tray_icon.hide()
            QApplication.quit()

        # -------------------------------------------------------------------
        # THEME ENGINE
        # -------------------------------------------------------------------
        def apply_theme(self, theme_name: str):
            t = THEMES.get(theme_name, THEMES["macOS Sonoma Dark (3D)"])
            self.current_theme_name = theme_name
            save_settings({"theme": theme_name})

            self.setStyleSheet(
                f"""
                QMainWindow, QWidget {{
                    background: {t['bg']};
                    color: {t['text']};
                    font-family: 'Segoe UI', 'SF Pro Display', sans-serif;
                    font-size: 13px;
                }}
                QFrame#card3d {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 {t['card']}, stop:1 {t['card_alt']});
                    border: 1.5px solid {t['border']};
                    border-radius: 16px;
                }}
                QFrame#dangerCard {{
                    background: #dc2626;
                    border: 2px solid #f87171;
                    border-radius: 12px;
                    padding: 8px;
                }}
                QFrame#stepCard {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 {t['card_alt']}, stop:1 {t['card']});
                    border: 2px solid {t['accent']};
                    border-radius: 16px;
                    padding: 10px;
                }}
                QLabel#heroTitle {{
                    font-size: 22px;
                    font-weight: 900;
                    letter-spacing: 0.6px;
                    color: {t['text']};
                }}
                QLabel#stepTitle {{
                    font-size: 15px;
                    font-weight: 800;
                    color: {t['accent']};
                }}
                QLabel#muted {{
                    color: {t['muted']};
                }}
                QLabel#badgeLabel {{
                    background: {t['card_alt']};
                    border: 1px solid {t['border']};
                    border-radius: 10px;
                    padding: 5px 10px;
                    font-weight: 700;
                    color: {t['accent']};
                }}
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 {t['card_alt']}, stop:1 {t['card']});
                    border: 1.5px solid {t['border']};
                    border-bottom: 3px solid {t['border']};
                    border-radius: 11px;
                    padding: 8px 14px;
                    font-weight: 700;
                    color: {t['text']};
                }}
                QPushButton:hover {{
                    border-color: {t['accent']};
                }}
                QPushButton#macFolderBtn {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 {t['card_alt']}, stop:1 {t['card']});
                    border: 2px solid {t['accent']};
                    border-bottom: 4px solid {t['accent_2']};
                    border-radius: 13px;
                    padding: 8px 14px;
                    font-size: 13px;
                    font-weight: 800;
                    text-align: left;
                }}
                QPushButton#macCityBtn {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 {t['card']}, stop:1 {t['card_alt']});
                    border: 2px solid {t['success']};
                    border-bottom: 4px solid {t['accent']};
                    border-radius: 13px;
                    padding: 8px 14px;
                    font-size: 13px;
                    font-weight: 800;
                    text-align: left;
                }}
                QPushButton#primaryBtn {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 {t['accent']}, stop:1 {t['accent_2']});
                    color: #ffffff;
                    border: none;
                    border-bottom: 3px solid #1e3a8a;
                    font-weight: 800;
                }}
                QPushButton#dangerBtn {{
                    background: {t['danger']};
                    color: #ffffff;
                    border: none;
                    font-weight: 800;
                }}
                QPushButton#accentBtn {{
                    background: {t['success']};
                    color: #ffffff;
                    border: none;
                    font-weight: 800;
                }}
                QPushButton#whatsappBtn {{
                    background: #16a34a;
                    color: #ffffff;
                    border: 1px solid #22c55e;
                    border-bottom: 3px solid #15803d;
                    font-weight: 800;
                }}
                QComboBox, QLineEdit, QSpinBox, QTextEdit, QListWidget, QMenu {{
                    background: {t['card']};
                    border: 1.5px solid {t['border']};
                    border-radius: 10px;
                    padding: 7px 10px;
                    color: {t['text']};
                    font-weight: 600;
                }}
                QTabWidget::pane {{
                    border: 1px solid {t['border']};
                    border-radius: 14px;
                }}
                QTabBar::tab {{
                    background: {t['card']};
                    padding: 10px 18px;
                    margin-right: 6px;
                    border-radius: 10px;
                    font-weight: 700;
                }}
                QTabBar::tab:selected {{
                    background: {t['accent_2']};
                    color: #ffffff;
                }}
                """
            )

        # -------------------------------------------------------------------
        # COMPACT COUNTRY BUTTON -> COMPACT CITY BUTTON -> STRICT TIMER FLOW
        # -------------------------------------------------------------------
        def refresh_provider_list(self, select_key=None):
            self.provider_combo.clear()
            for key, provider in PROVIDERS.items():
                self.provider_combo.addItem(provider.label, key)
            if select_key:
                idx = self.provider_combo.findData(select_key)
                if idx >= 0:
                    self.provider_combo.setCurrentIndex(idx)

        def current_provider(self) -> Provider:
            key = self.provider_combo.currentData()
            return PROVIDERS.get(key, PROVIDERS["pia"])

        def on_provider_changed(self):
            self.duration_card.setVisible(False)
            self.mode_card.setVisible(False)
            self.load_locations_for_provider()

        def load_locations_for_provider(self):
            prov = self.current_provider()
            raw = prov.locations() if not isinstance(prov, CustomVPN) else []
            self.country_tree = build_country_city_tree(raw)
            self.selected_country = ""
            self.selected_city_label = "Automatic"
            self.selected_region_slug = "Automatic"
            self.country_folder_btn.setText("📂  1. Select Country")
            self.city_folder_btn.setText("🏙  2. City: Automatic")
            self.log.append(f"[{prov.label}] Loaded {len(self.country_tree)} countries.")

        def open_country_finder(self):
            if not self.country_tree:
                self.country_tree = build_country_city_tree([])
            dlg = MacCountryFinderDialog(self, self.country_tree)
            if dlg.exec() == QDialog.Accepted and dlg.selected_country:
                self.selected_country = dlg.selected_country
                flag = COUNTRY_FLAGS.get(self.selected_country, "🌐")
                self.country_folder_btn.setText(f"{flag}  {self.selected_country}")
                # Automatically open the City Finder Popup so cities never clutter the main UI
                self.open_city_finder()

        def open_city_finder(self):
            if not self.selected_country:
                self.open_country_finder()
                return
            cities = self.country_tree.get(
                self.selected_country,
                [(f"{self.selected_country} Central", self.selected_country.lower())],
            )
            dlg = MacCityFinderDialog(self, self.selected_country, cities)
            if dlg.exec() == QDialog.Accepted and dlg.selected_city:
                city_label, region_slug = dlg.selected_city
                self.on_city_selected(city_label, region_slug)

        def on_city_selected(self, city_label: str, region_slug: str):
            self.selected_city_label = city_label
            self.selected_region_slug = region_slug
            flag = COUNTRY_FLAGS.get(self.selected_country, "🌐")
            # Show the chosen Country & City cleanly inside the button itself!
            self.country_folder_btn.setText(f"{flag}  {self.selected_country}")
            self.city_folder_btn.setText(f"🏙  {self.selected_country} • {city_label}")
            self.dur_title.setText(
                f"⏱ Step 3: {self.selected_country} ({city_label}) কত মিনিটের জন্য কানেক্ট করতে চান?"
            )
            self.duration_card.setVisible(True)
            self.log.append(f"Selected: {self.selected_country} ➔ {city_label} ({region_slug}).")

        def select_duration(self, minutes: int):
            # Stop any running countdown immediately so user changes never misfire
            self.session_timer.stop()
            if minutes <= 0:
                self.timer_enabled = False
                self.configured_minutes = 0
                self.remaining_seconds = 0
                self.timer_badge.setText("⏱ Timer: ♾ Unlimited")
                self.mode_card.setVisible(False)
                self.log.append("Timer Mode: ♾ Unlimited (আপনি ডিসকানেক্ট না করা পর্যন্ত চলবে)।")
            else:
                self.timer_enabled = True
                self.configured_minutes = int(minutes)
                self.remaining_seconds = int(minutes) * 60
                self.custom_min_spin.setValue(int(minutes))
                self.timer_badge.setText(f"⏱ Set: {minutes} Min ({self.remaining_seconds}s)")
                self.mode_card.setVisible(True)
                self.log.append(
                    f"Timer strictly locked to {minutes} minutes ({self.remaining_seconds} seconds)."
                )

        # -------------------------------------------------------------------
        # CONNECT, DISCONNECT, TEST VPN & STRICT TIMER ENGINE
        # -------------------------------------------------------------------
        def start_connect_flow(self):
            if self.active_worker and self.active_worker.isRunning():
                return
            # Pause timer while connecting so it never triggers mid-connection
            self.session_timer.stop()

            prov = self.current_provider()
            target_loc = self.selected_region_slug or "Automatic"
            city_disp = self.selected_city_label or target_loc
            self.orb.set_state("connecting", "CONNECTING...", city_disp[:18], spinning=True)
            self._update_tray_appearance("connecting", f"Connecting to {city_disp}...")
            self.log.append(f"Connecting {prov.label} to {city_disp} ({target_loc})...")

            self.active_worker = ActionWorker(prov, "connect", target_loc)
            self.active_worker.finished_result.connect(self._on_worker_done)
            self.active_worker.start()

        def start_disconnect_flow(self):
            self.session_timer.stop()
            self.is_reconnecting_cycle = False
            self.remaining_seconds = 0
            self.timer_badge.setText("⏱ Timer: Stopped")
            prov = self.current_provider()
            self.orb.set_state("connecting", "STOPPING...", prov.label[:16], spinning=True)
            self._update_tray_appearance("connecting", "Disconnecting...")

            self.active_worker = ActionWorker(prov, "disconnect")
            self.active_worker.finished_result.connect(self._on_worker_done)
            self.active_worker.start()

        def start_test_flow(self):
            if self.active_worker and self.active_worker.isRunning():
                return
            prov = self.current_provider()
            self.orb.set_state("connecting", "TESTING...", prov.label[:16], spinning=True)
            self._update_tray_appearance("connecting", f"Testing {prov.label}...")
            self.log.append(f"Testing {prov.label} service & connection readiness...")

            self.active_worker = ActionWorker(prov, "test")
            self.active_worker.finished_result.connect(self._on_worker_done)
            self.active_worker.start()

        def _on_worker_done(self, ok: bool, message: str, action: str):
            self.log.append(message)
            prov = self.current_provider()

            if action == "test":
                if ok:
                    self.orb.set_state("success", "TEST SUCCESS", "VPN Ready", spinning=False)
                    self._update_tray_appearance("success", "VPN Test: Ready")
                    self.send_notification("✅ VPN Test Successful", message, "success")
                else:
                    self.orb.set_state("failed", "TEST FAILED", "Check App", spinning=False)
                    self._update_tray_appearance("failed", "VPN Test: Failed")
                    self.send_notification("❌ VPN Test Failed", message, "failed")
                if self.isVisible():
                    QMessageBox.information(self, "VPN Diagnostic Test Result", message)
                return

            if action == "connect":
                self.is_reconnecting_cycle = False
                if ok:
                    city_disp = self.selected_city_label or self.selected_region_slug or "Automatic"
                    country_disp = self.selected_country or prov.label
                    self.orb.set_state("success", "CONNECTED", city_disp[:18], spinning=False)
                    self._update_tray_appearance("success", f"Connected: {country_disp} ({city_disp})")
                    if self.selected_country:
                        self.city_folder_btn.setText(f"🟢 {self.selected_country} • {city_disp} (Connected)")

                    # ONLY start countdown if user explicitly enabled a timer > 0 minutes!
                    if self.timer_enabled and self.configured_minutes > 0:
                        self.remaining_seconds = self.configured_minutes * 60
                        self.session_timer.start(1000)
                        timer_note = f" | টাইমার: {self.configured_minutes} মিনিট"
                    else:
                        self.session_timer.stop()
                        self.timer_badge.setText("⏱ Timer: ♾ Unlimited")
                        timer_note = " | ♾ Unlimited"

                    self.send_notification(
                        "🛡 VPN Connected Successfully",
                        f"{prov.label} ➔ {country_disp} ({city_disp}) কানেক্ট হয়েছে{timer_note}।",
                        "success",
                    )
                else:
                    self.orb.set_state("failed", "FAILED", "See Log", spinning=False)
                    self._update_tray_appearance("failed", "Connection Failed")
                    self.send_notification("❌ VPN Connection Failed", message, "failed")
                    if self.isVisible():
                        QMessageBox.warning(self, "VPN Connection Failed", message)

            elif action == "disconnect":
                if ok:
                    self.orb.set_state("idle", "DISCONNECTED", "Standby", spinning=False)
                    self._update_tray_appearance("idle", "Disconnected (Standby)")
                    if self.selected_country and self.selected_city_label:
                        self.city_folder_btn.setText(f"🏙  {self.selected_country} • {self.selected_city_label}")
                    self.send_notification(
                        "⏹ VPN Disconnected",
                        f"{prov.label} সফলভাবে ডিসকানেক্ট হয়েছে।",
                        "info",
                    )
                else:
                    self.orb.set_state("failed", "CHECK APP", "Manual Stop", spinning=False)
                    self._update_tray_appearance("failed", "Disconnect Needs Official App")
                    self.send_notification("⚠ Disconnect Notice", message, "warning")

        def _on_session_second(self):
            # Guard against firing if timer is disabled or already cycling
            if not self.timer_enabled or self.configured_minutes <= 0 or self.is_reconnecting_cycle:
                self.session_timer.stop()
                return

            if self.remaining_seconds > 0:
                self.remaining_seconds -= 1
                m, s = divmod(self.remaining_seconds, 60)
                self.timer_badge.setText(f"⏱ Left: {m:02d}:{s:02d}")
                return

            # Full user-specified duration has elapsed!
            self.session_timer.stop()
            self.is_reconnecting_cycle = True
            prov = self.current_provider()

            if self.radio_single_disconnect.isChecked():
                self.log.append(f"⏰ {self.configured_minutes} মিনিট পূর্ণ হয়েছে। VPN ডিসকানেক্ট করা হচ্ছে...")
                self.send_notification(
                    "⏰ VPN Timer Complete",
                    f"আপনার নির্ধারিত {self.configured_minutes} মিনিট শেষ হওয়ায় ভিপিএন ডিসকানেক্ট করা হচ্ছে।",
                    "info",
                )
                self.start_disconnect_flow()

            elif self.radio_same_country_loop.isChecked():
                msg = (
                    f"{self.configured_minutes} মিনিট পূর্ণ হয়েছে! "
                    f"{self.selected_country} ({self.selected_city_label}) পুনরায় কানেক্ট করা হচ্ছে..."
                )
                self.log.append("🔁 " + msg)
                self.send_notification("🔁 Same Country Reconnect Loop", msg, "info")
                prov.disconnect()
                self.remaining_seconds = self.configured_minutes * 60
                QTimer.singleShot(3000, self.start_connect_flow)

            elif self.radio_rotate_country.isChecked():
                countries = list(self.country_tree.keys())
                if countries:
                    other_countries = [c for c in countries if c != self.selected_country] or countries
                    next_country = random.choice(other_countries)
                    next_city, next_slug = random.choice(self.country_tree[next_country])
                    self.selected_country = next_country
                    self.selected_city_label = next_city
                    self.selected_region_slug = next_slug
                    flag = COUNTRY_FLAGS.get(next_country, "🌐")
                    self.country_folder_btn.setText(f"{flag}  {next_country}")
                    self.city_folder_btn.setText(f"🏙  {next_country} • {next_city}")
                    msg = f"{self.configured_minutes} মিনিট পর নতুন লোকেশন {next_country} ({next_city})-এ কানেক্ট হচ্ছে..."
                    self.log.append("🌍 " + msg)
                    self.send_notification("🌍 Auto Country Rotation", msg, "info")
                prov.disconnect()
                self.remaining_seconds = self.configured_minutes * 60
                QTimer.singleShot(3000, self.start_connect_flow)

        # -------------------------------------------------------------------
        # SETTINGS & DOWNLOAD HANDLERS
        # -------------------------------------------------------------------
        def toggle_always_on_top(self, checked: bool):
            self.setWindowFlag(Qt.WindowStaysOnTopHint, checked)
            self.show()

        def run_background_repair(self):
            ensure_background_environment()
            for key in ("pia", "expressvpn"):
                p = PROVIDERS.get(key)
                exe = p.detect() if p else None
                if exe:
                    run_hidden(exe, ["background", "enable"], timeout=10)
            self.scan_providers()
            self.send_notification(
                "🔧 Background Repair Complete",
                "সব VPN পাথ এবং ব্যাকগ্রাউন্ড সার্ভিস পারমিশন সেটআপ হয়েছে।",
                "success",
            )

        def scan_providers(self):
            found = [v.label for v in PROVIDERS.values() if v.detect()]
            self.detect_lbl.setText(
                "DETECTED VPN APPS: " + (", ".join(found) if found else "None (Install from Download Center)")
            )

        def add_custom_vpn(self):
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Select VPN application",
                "",
                "Windows applications (*.exe);;All files (*.*)",
            )
            if not path:
                return
            name, ok = QInputDialog.getText(self, "Add VPN", "VPN provider / app name:")
            if not ok or not name.strip():
                return
            key = "custom_" + str(abs(hash(os.path.normcase(path))))
            PROVIDERS[key] = CustomVPN(key, name.strip(), path)
            save_custom_vpns()
            self.refresh_provider_list(key)
            self.load_locations_for_provider()
            self.scan_providers()
            self.log.append(f"Added custom VPN: {name.strip()}")

        def start_download(self, name, url):
            if name in self.download_workers and self.download_workers[name].isRunning():
                return
            bar, status, cancel, button = self.download_rows[name]
            bar.setValue(0)
            status.setText("Connecting to official server…")
            cancel.setEnabled(True)
            button.setEnabled(False)
            worker = DownloadWorker(name, url, self.download_folder)
            worker.progress.connect(lambda pct, msg, n=name: self.update_download_progress(n, pct, msg))
            worker.completed.connect(self.download_completed)
            worker.failed.connect(self.download_failed)
            self.download_workers[name] = worker
            worker.start()

        def update_download_progress(self, name, percent, message):
            bar, status, cancel, button = self.download_rows[name]
            if percent > 0:
                bar.setValue(percent)
            status.setText(message)

        def cancel_download(self, name):
            worker = self.download_workers.get(name)
            if worker and worker.isRunning():
                worker.cancel()
                self.download_rows[name][1].setText("Cancelling…")

        def download_completed(self, name, path):
            bar, status, cancel, button = self.download_rows[name]
            bar.setValue(100)
            status.setText("Download complete")
            cancel.setEnabled(False)
            button.setEnabled(True)
            self.download_history.addItem(f"{name}  —  {path}")
            self.log.append(f"Downloaded {name}: {path}")
            self.send_notification("⬇ Download Complete", f"{name} ইনস্টলার ডাউনলোড সম্পন্ন হয়েছে।", "success")
            answer = QMessageBox.question(
                self,
                "Download complete",
                f"{name} installer downloaded successfully.\n\n{path}\n\nOpen installer now?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer == QMessageBox.Yes:
                try:
                    os.startfile(path)
                except Exception as exc:
                    QMessageBox.warning(self, "Installer", str(exc))

        def download_failed(self, name, message):
            bar, status, cancel, button = self.download_rows[name]
            cancel.setEnabled(False)
            button.setEnabled(True)
            status.setText(message)
            self.log.append(f"{name} download: {message}")
            if message != "Download cancelled.":
                self.send_notification(f"❌ {name} Download Failed", message, "failed")
                QMessageBox.warning(self, f"{name} download failed", message)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    win = Window()
    win.show()
    return app.exec()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != "gui":
        sys.exit(cli())
    ensure_background_environment()
    hide_console_window()
    sys.exit(launch_gui())
