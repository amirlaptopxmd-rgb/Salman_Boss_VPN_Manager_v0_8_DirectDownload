# Salman Boss VPN Manager v0.9 — Direct GitHub API Admin Control & Portable Edition
# Windows 10/11 | macOS 3D GUI + Exact Timer + City Button + Direct GitHub Gist Push
from __future__ import annotations
import argparse, base64, csv, ctypes, hashlib, json, logging, os, random, re, shutil, socket, subprocess, sys, time, urllib.request, urllib.parse, urllib.error
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Optional

try:
    import winsound
except ImportError:
    winsound = None

APP = "Salman Boss VPN Manager"
APP_VERSION = "0.10.3"

# এখানে আপনার তৈরি হওয়া GitHub Gist-এর Raw URL বসিয়ে দিলে অন্যদের পিসিতে অটো কাজ করবে
DEFAULT_CLOUD_CONTROL_URL = "https://gist.githubusercontent.com/amir4445/4eb1a994a2bfc853ed9465bb5f5c1a64/raw/salman_admin_control.json"

# টেলিগ্রাম এবং হোয়াটসঅ্যাপ লিংক (নাম্বার বাটনে শো করবে না, লিংকে কাজ করবে)
TELEGRAM_URL = "https://t.me/Salman3579"
WHATSAPP_URL = "https://wa.me/8801955858703"

# ডিফল্ট অ্যাডমিন পিন কোড
DEFAULT_ADMIN_PIN = "3579"

BASE = Path(os.environ.get("APPDATA", str(Path.home()))) / "SalmanBossVPN"
BASE.mkdir(parents=True, exist_ok=True)
CONFIG = BASE / "settings.json"
REMOTE_CONTROL_FILE = BASE / "remote_control_state.json"
LOGFILE = BASE / "manager.log"
HISTORY_FILE = BASE / "usage_history.json"

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
# SETTINGS & DIRECT GITHUB GIST API ENGINE (NO BROWSER NEEDED)
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
        "update_message": "নতুন আপডেট এসেছে! সর্বশেষ ফিচার পেতে এখনই আপডেট করুন।",
        "update_script_url": "",
        "update_sha256": "",
        "update_file_name": "",
        "control_json_url": "",
        "lock_message": "⛔ অ্যাডমিন (Salman Boss) এই সফটওয়্যারের অ্যাক্সেস সাময়িকভাবে বন্ধ রেখেছেন। যোগাযোগ করুন: WhatsApp / Telegram।",
    }


def extract_gist_id(gist_input: str) -> str:
    """Extracts the hexadecimal Gist ID from a full Gist URL, Raw URL, or plain ID string."""
    s = gist_input.strip()
    if not s:
        return ""
    m = re.search(r"([a-fA-F0-9]{20,40})", s)
    if m:
        return m.group(1)
    return s.split("/")[-1]


def application_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def load_control_state() -> dict:
    """Loads remote control JSON from GitHub Gist API / Raw URL or local fallback file."""
    cfg = load_settings()
    remote_url = cfg.get("remote_control_url", DEFAULT_CLOUD_CONTROL_URL).strip()
    gist_id = extract_gist_id(cfg.get("github_gist_id", "") or remote_url)
    state = get_default_remote_state()

    # 1. Local fallback check
    local_shared = application_directory() / "salman_admin_control.json"
    for candidate in (local_shared, REMOTE_CONTROL_FILE):
        if candidate.exists():
            try:
                loaded = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    state.update(loaded)
            except Exception:
                pass

    # 2. If Gist ID is available, fetch directly from GitHub Gist API (bypasses CDN caching!)
    if gist_id and re.fullmatch(r"[a-fA-F0-9]{20,40}", gist_id):
        try:
            api_url = f"https://api.github.com/gists/{gist_id}"
            headers = {
                "Accept": "application/vnd.github+json",
                "User-Agent": f"SalmanBossVPN/{APP_VERSION}",
                "Cache-Control": "no-cache",
            }
            req = urllib.request.Request(api_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                gist_data = json.loads(resp.read().decode("utf-8"))
            files = gist_data.get("files", {})
            ctrl_file = files.get("salman_admin_control.json")
            if ctrl_file and ctrl_file.get("content"):
                remote_data = json.loads(ctrl_file["content"])
                if isinstance(remote_data, dict):
                    state.update(remote_data)
                    return state
        except Exception as e:
            logging.warning("Direct Gist API read fallback: %s", e)

    # 3. Fallback to Raw URL with cache-buster timestamp
    if remote_url.startswith(("http://", "https://")):
        try:
            sep = "&" if "?" in remote_url else "?"
            bust_url = f"{remote_url}{sep}_t={random.randint(100000, 999999)}"
            req = urllib.request.Request(
                bust_url,
                headers={"User-Agent": f"SalmanBossVPN/{APP_VERSION}", "Cache-Control": "no-cache"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                remote_data = json.loads(resp.read().decode("utf-8"))
                if isinstance(remote_data, dict):
                    state.update(remote_data)
        except Exception as e:
            logging.warning("Remote control URL fetch skipped: %s", e)

    return state


def save_control_state_locally(new_state: dict) -> dict:
    state = get_default_remote_state()
    state.update(new_state)
    payload = json.dumps(state, indent=2, ensure_ascii=False)
    try:
        REMOTE_CONTROL_FILE.write_text(payload, encoding="utf-8")
    except Exception:
        pass
    try:
        local_shared = application_directory() / "salman_admin_control.json"
        local_shared.write_text(payload, encoding="utf-8")
    except Exception:
        pass
    return state


def push_state_to_github_gist(
    token: str,
    gist_id_or_url: str,
    state: dict,
    include_live_script: bool = False,
) -> tuple[bool, str, str, str]:
    """
    Directly creates or updates the GitHub Gist from the Admin Panel without opening a browser.
    Returns: (success, message, gist_id, control_raw_url)
    """
    clean_token = token.strip()
    if not clean_token:
        return (
            False,
            "GitHub Personal Access Token দেওয়া হয়নি। লোকাল কন্ট্রোল ফাইলে সেভ হয়েছে।",
            "",
            "",
        )

    gist_id = extract_gist_id(gist_id_or_url)
    headers = {
        "Authorization": f"Bearer {clean_token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": f"SalmanBossVPN-Admin/{APP_VERSION}",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    files_payload: dict[str, dict[str, str]] = {}

    # Optionally bundle the current Python file into the Gist so clients auto-download the code
    if include_live_script:
        try:
            script_path = Path(__file__).resolve()
            script_text = script_path.read_text(encoding="utf-8")
            # Ensure DEFAULT_CLOUD_CONTROL_URL is embedded for clients if known
            cfg_url = load_settings().get("remote_control_url", "").strip()
            if cfg_url:
                script_text = re.sub(
                    r'^DEFAULT_CLOUD_CONTROL_URL\s*=\s*".*"',
                    f'DEFAULT_CLOUD_CONTROL_URL = "{cfg_url}"',
                    script_text,
                     count=1,
                    flags=re.MULTILINE,
                )
            # Also update APP_VERSION in the uploaded script to match the pushed version
            target_ver = str(state.get("latest_version", APP_VERSION)).strip()
            if target_ver:
                script_text = re.sub(
                    r'^APP_VERSION\s*=\s*".*"',
                    f'APP_VERSION = "{target_ver}"',
                    script_text,
                    count=1,
                    flags=re.MULTILINE,
                )
            files_payload["Salman_Boss_VPN_Manager_v0_5_DirectDownload.py"] = {"content": script_text}
        except Exception as e:
            logging.warning("Could not read local script for upload: %s", e)

    files_payload["salman_admin_control.json"] = {
        "content": json.dumps(state, indent=2, ensure_ascii=False)
    }

    body_dict = {
        "description": "Salman Boss VPN Manager — Live Remote Control & Auto-Updater",
        "public": False,
        "files": files_payload,
    }

    try:
        if gist_id and re.fullmatch(r"[a-fA-F0-9]{20,40}", gist_id):
            api_url = f"https://api.github.com/gists/{gist_id}"
            method = "PATCH"
        else:
            api_url = "https://api.github.com/gists"
            method = "POST"

        req = urllib.request.Request(
            api_url,
            data=json.dumps(body_dict).encode("utf-8"),
            headers=headers,
            method=method,
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))

        new_gist_id = resp_data.get("id", gist_id)
        owner_login = (resp_data.get("owner") or {}).get("login", "")
        files_resp = resp_data.get("files") or {}

        # Build stable latest Raw URLs (without commit hash so it always points to latest revision)
        if owner_login and new_gist_id:
            stable_ctrl_raw = (
                f"https://gist.githubusercontent.com/{owner_login}/{new_gist_id}/raw/salman_admin_control.json"
            )
            stable_script_raw = (
                f"https://gist.githubusercontent.com/{owner_login}/{new_gist_id}/raw/Salman_Boss_VPN_Manager_v0_5_DirectDownload.py"
            )
        else:
            stable_ctrl_raw = (files_resp.get("salman_admin_control.json") or {}).get("raw_url", "")
            stable_script_raw = (
                files_resp.get("Salman_Boss_VPN_Manager_v0_5_DirectDownload.py") or {}
            ).get("raw_url", "")

        # If we uploaded the live script and update_script_url wasn't set to stable_script_raw yet, patch it once
        if include_live_script and stable_script_raw and state.get("update_script_url") != stable_script_raw:
            state["update_script_url"] = stable_script_raw
            patch_body = {
                "files": {
                    "salman_admin_control.json": {
                        "content": json.dumps(state, indent=2, ensure_ascii=False)
                    }
                }
            }
            req2 = urllib.request.Request(
                f"https://api.github.com/gists/{new_gist_id}",
                data=json.dumps(patch_body).encode("utf-8"),
                headers=headers,
                method="PATCH",
            )
            urllib.request.urlopen(req2, timeout=15).close()

        save_control_state_locally(state)
        save_settings(
            {
                "github_gist_id": new_gist_id,
                "remote_control_url": stable_ctrl_raw,
            }
        )
        return (
            True,
            f"সফলভাবে সরাসরি GitHub Gist-এ আপডেট হয়েছে! (Gist ID: {new_gist_id})",
            new_gist_id,
            stable_ctrl_raw,
        )

    except urllib.error.HTTPError as he:
        err_body = he.read().decode("utf-8", errors="replace")
        return False, f"GitHub API Error ({he.code}): {err_body[:220]}", gist_id, ""
    except Exception as exc:
        return False, f"GitHub সংযোগ ত্রুটি: {exc}", gist_id, ""


def _load_requests():
    """Imports requests, installing it once if the admin PC does not have it yet."""
    try:
        import requests
    except ImportError:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "requests>=2.31", "--quiet"],
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        import requests
    return requests


def _github_repo_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token.strip()}",
        "Accept": "application/vnd.github+json",
        "User-Agent": f"SalmanBossVPN-Admin/{APP_VERSION}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _github_api_error(response) -> str:
    detail = ""
    try:
        body = response.json()
        detail = str(body.get("message", ""))
        errors = body.get("errors") or []
        if errors:
            detail = f"{detail} {errors[0]}".strip()
    except Exception:
        detail = (response.text or "")[:300]
    return f"GitHub API Error ({response.status_code}): {detail[:400]}"


def _raw_github_url(repository: str, branch: str, path: str) -> str:
    encoded_branch = urllib.parse.quote(branch, safe="")
    encoded_path = "/".join(urllib.parse.quote(part) for part in path.strip("/").split("/"))
    return f"https://raw.githubusercontent.com/{repository}/{encoded_branch}/{encoded_path}"


def _contents_api_url(repository: str, path: str) -> str:
    encoded_path = "/".join(urllib.parse.quote(part) for part in path.strip("/").split("/"))
    return f"https://api.github.com/repos/{repository}/contents/{encoded_path}"


def _prepare_published_script(text: str, version: str, control_url: str) -> str:
    """Bakes the version and control URL into this app before it is committed."""
    if control_url:
        text = re.sub(
            r'^DEFAULT_CLOUD_CONTROL_URL\s*=\s*".*"',
            f'DEFAULT_CLOUD_CONTROL_URL = "{control_url}"',
            text,
            count=1,
            flags=re.MULTILINE,
        )
    if version:
        text = re.sub(
            r'^APP_VERSION\s*=\s*".*"',
            f'APP_VERSION = "{version}"',
            text,
            count=1,
            flags=re.MULTILINE,
        )
    return text


def _put_repo_file(session, headers: dict, repository: str, branch: str, path: str, payload: bytes, message: str) -> str:
    """Creates or updates one file through the GitHub Contents API. Returns its raw URL."""
    url = _contents_api_url(repository, path)
    existing = session.get(url, headers=headers, params={"ref": branch}, timeout=30)
    sha = None
    if existing.status_code == 200:
        sha = (existing.json() or {}).get("sha")
    elif existing.status_code != 404:
        raise RuntimeError(_github_api_error(existing))

    body = {
        "message": message,
        "content": base64.b64encode(payload).decode("ascii"),
        "branch": branch,
    }
    if sha:
        body["sha"] = sha
    put_headers = dict(headers)
    put_headers["Content-Type"] = "application/json; charset=utf-8"
    saved = session.put(url, headers=put_headers, data=json.dumps(body).encode("utf-8"), timeout=90)
    if saved.status_code in (409, 422):
        lowered = (saved.text or "").lower()
        if "identical" in lowered or "has not changed" in lowered:
            return _raw_github_url(repository, branch, path)
        raise RuntimeError(_github_api_error(saved))
    if saved.status_code not in (200, 201):
        raise RuntimeError(_github_api_error(saved))
    content = (saved.json() or {}).get("content") or {}
    download_url = str(content.get("download_url") or "")
    if download_url.startswith("https://raw.githubusercontent.com/"):
        return download_url
    return _raw_github_url(repository, branch, path)


def publish_python_file_to_github(
    token: str,
    repository: str,
    branch: str,
    local_file: str,
    repo_path: str,
    version: str,
    update_message: str,
    state: dict,
    progress=None,
) -> dict:
    """
    Commits a local Python file to a public GitHub repository and updates
    salman_admin_control.json in that same repository.
    """
    def report(text: str):
        if progress:
            progress(text)

    clean_token = token.strip()
    repository = repository.strip()
    branch = (branch or "main").strip()
    version = version.strip()
    repo_path = repo_path.strip().replace("\\", "/").lstrip("/")
    local_path = Path(local_file)

    if not clean_token:
        raise ValueError("GitHub Personal Access Token দিন।")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Repository format must be owner/repository.")
    if (
        not re.fullmatch(r"[A-Za-z0-9._/-]{1,120}", branch)
        or branch.startswith("/")
        or ".." in branch.split("/")
    ):
        raise ValueError("Branch name is not valid.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}", version):
        raise ValueError("Version must use letters, numbers, dot, underscore, +, or hyphen.")
    if not local_path.is_file():
        raise ValueError("Browse Script দিয়ে একটি লোকাল Python ফাইল সিলেক্ট করুন।")
    if local_path.suffix.lower() not in {".py", ".pyw"}:
        raise ValueError("শুধু .py বা .pyw ফাইল রিপোজিটরিতে কমিট করা যাবে।")
    if not repo_path:
        repo_path = local_path.name
    if ".." in repo_path.split("/") or not repo_path.lower().endswith((".py", ".pyw")):
        raise ValueError("Repository path must be a relative .py or .pyw path.")

    raw = local_path.read_bytes()
    if len(raw) > 900_000:
        raise ValueError("ফাইল 900 KB-এর বেশি। GitHub Contents API-তে এই সাইজের স্ক্রিপ্ট কমিট করা হয়নি।")
    had_bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        script_text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Python ফাইলটি UTF-8 নয়।") from exc

    requests = _load_requests()
    session = requests.Session()
    headers = _github_repo_headers(clean_token)
    report("Checking GitHub repository...")
    repo_response = session.get(f"https://api.github.com/repos/{repository}", headers=headers, timeout=30)
    if repo_response.status_code != 200:
        raise RuntimeError(_github_api_error(repo_response))
    repo_info = repo_response.json()
    if repo_info.get("private"):
        raise ValueError("ক্লায়েন্ট যাতে টোকেন ছাড়া ডাউনলোড করতে পারে, রিপোজিটরিটি Public হতে হবে।")
    if not branch:
        branch = str(repo_info.get("default_branch") or "main")

    saved_control_url = str(load_settings().get("remote_control_url", "")).strip()
    control_raw_url = _raw_github_url(repository, branch, "salman_admin_control.json")
    client_control_url = saved_control_url if saved_control_url.startswith("https://") else control_raw_url
    script_text = _prepare_published_script(script_text, version, client_control_url)
    script_bytes = (b"\xef\xbb\xbf" if had_bom else b"") + script_text.encode("utf-8")
    digest = hashlib.sha256(script_bytes).hexdigest()

    report("Committing Python file to GitHub...")
    script_raw_url = _put_repo_file(
        session,
        headers,
        repository,
        branch,
        repo_path,
        script_bytes,
        f"Publish {Path(repo_path).name} {version}",
    )

    published_state = get_default_remote_state()
    if isinstance(state, dict):
        published_state.update(state)
    published_state.update(
        {
            "latest_version": version,
            "update_message": update_message.strip() or published_state.get("update_message", ""),
            "update_script_url": script_raw_url,
            "update_sha256": digest,
            "update_file_name": Path(repo_path).name,
            "control_json_url": control_raw_url,
        }
    )
    control_bytes = json.dumps(published_state, indent=2, ensure_ascii=False).encode("utf-8")
    report("Updating salman_admin_control.json...")
    _put_repo_file(
        session,
        headers,
        repository,
        branch,
        "salman_admin_control.json",
        control_bytes,
        f"Update control JSON to {version}",
    )
    save_control_state_locally(published_state)
    report("GitHub repository update complete.")
    return {
        "message": f"স্ক্রিপ্ট ও কন্ট্রোল JSON GitHub রিপোতে কমিট হয়েছে ({repository}@{branch})।",
        "download_url": script_raw_url,
        "control_url": control_raw_url,
        "sha256": digest,
        "state": published_state,
        "branch": branch,
    }


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
        install_roots = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Proton",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Proton",
        ]
        candidates = []
        for root in install_roots:
            candidates.extend(
                [
                    root / "VPN" / "ProtonVPN.exe",
                    root / "VPN" / "ProtonVPN.Launcher.exe",
                    *root.glob("VPN*/*ProtonVPN*.exe"),
                    *root.glob("VPN/*ProtonVPN*.exe"),
                ]
            )
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        return locate(["ProtonVPN.exe", "ProtonVPN.Launcher.exe", "ProtonVPNLauncher.exe"])

    def _press_app_button(self, button_name: str, location: str = "Automatic") -> Result:
        powershell = locate(["powershell.exe", "powershell"])
        if not powershell:
            return Result(False, "Windows PowerShell পাওয়া যায়নি; Proton app-এর Connect button চাপুন।")

        city = ""
        if button_name == "Connect" and location and location != "Automatic":
            city = location
            for cities in DEFAULT_COUNTRY_CITIES.values():
                for city_label, region_slug in cities:
                    if location.casefold() in (city_label.casefold(), region_slug.casefold()):
                        city = city_label.split("(", 1)[0].strip()
                        break

        automation_id = {
            "Connect": "ConnectionCardConnectButton",
            "Disconnect": "ConnectionCardDisconnectButton",
        }[button_name]
        target_id = {
            "Connect": "ConnectionCardDisconnectButton",
            "Disconnect": "ConnectionCardConnectButton",
        }[button_name]
        city = city.replace("'", "''")
        script = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement
$windowCondition = [System.Windows.Automation.PropertyCondition]::new(
    [System.Windows.Automation.AutomationElement]::NameProperty, 'Proton VPN')
$buttonId = '{automation_id}'
$targetId = '{target_id}'
$buttonName = '{button_name}'
$city = '{city}'
$invoked = $false
$conflictMessage = ''
for ($attempt = 0; $attempt -lt 120; $attempt++) {{
    $windows = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $windowCondition)
    foreach ($window in $windows) {{
        $targetCondition = [System.Windows.Automation.PropertyCondition]::new(
            [System.Windows.Automation.AutomationElement]::AutomationIdProperty, $targetId)
        $target = $window.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $targetCondition)
        if ($target -and (-not $city -or $invoked)) {{
            Write-Output $(if ($invoked) {{ 'TARGET_STATE_CONFIRMED' }} else {{ 'ALREADY_IN_TARGET_STATE' }})
            exit 0
        }}

        $cancelCondition = [System.Windows.Automation.PropertyCondition]::new(
            [System.Windows.Automation.AutomationElement]::AutomationIdProperty, 'ConnectionCardCancelButton')
        $cancel = $window.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cancelCondition)
        if ($cancel) {{
            $texts = $window.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                [System.Windows.Automation.PropertyCondition]::new(
                    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
                    [System.Windows.Automation.ControlType]::Text))
            foreach ($text in $texts) {{
                $message = $text.Current.Name
                if ($message -match 'Another app might be preventing|Data Channel Offload') {{
                    $conflictMessage = $message
                }}
            }}
            if (-not $invoked) {{ Write-Output 'CONNECTION_IN_PROGRESS'; exit 0 }}
        }}

        if (-not $invoked) {{
            if ($city) {{
                $searchCondition = [System.Windows.Automation.PropertyCondition]::new(
                    [System.Windows.Automation.AutomationElement]::AutomationIdProperty, 'SearchTextBox')
                $search = $window.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $searchCondition)
                if (-not $search) {{ throw 'Proton VPN city search field was not found.' }}
                $search.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue($city)
                Start-Sleep -Milliseconds 250
                $cityButtonId = 'Connect_to_' + $city
                $cityButtonCondition = [System.Windows.Automation.PropertyCondition]::new(
                    [System.Windows.Automation.AutomationElement]::AutomationIdProperty, $cityButtonId)
                $button = $window.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cityButtonCondition)
                if (-not $button) {{ continue }}
            }} else {{
                $idCondition = [System.Windows.Automation.PropertyCondition]::new(
                    [System.Windows.Automation.AutomationElement]::AutomationIdProperty, $buttonId)
                $button = $window.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $idCondition)
                if (-not $button) {{
                    $nameCondition = [System.Windows.Automation.PropertyCondition]::new(
                        [System.Windows.Automation.AutomationElement]::NameProperty, $buttonName)
                    $button = $window.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $nameCondition)
                }}
            }}
            if ($button -and $button.Current.IsEnabled) {{
                $pattern = $button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
                $pattern.Invoke()
                $invoked = $true
            }}
        }}
    }}
    Start-Sleep -Milliseconds 500
}}
if ($invoked -and $conflictMessage) {{ Write-Output "CONFLICT:$conflictMessage"; exit 3 }}
if ($invoked) {{ Write-Error 'Proton VPN did not confirm the requested connection state.' }}
else {{ Write-Error "Proton VPN window or $buttonName button was not available." }}
exit 2
"""
        try:
            encoded_script = base64.b64encode(script.encode("utf-16le")).decode("ascii")
            result = subprocess.run(
                [powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded_script],
                capture_output=True,
                text=True,
                timeout=70,
                creationflags=CREATE_NO_WINDOW,
                encoding="utf-8",
                errors="replace",
            )
            output = (result.stdout or "").strip()
            if result.returncode == 0 and "ALREADY_IN_TARGET_STATE" in output:
                return Result(True, f"Proton VPN is already in the requested {button_name.lower()} state.")
            if result.returncode == 0 and "TARGET_STATE_CONFIRMED" in output:
                return Result(True, f"Proton VPN confirmed the {button_name.lower()} request in its app.")
            if result.returncode == 0 and "CONNECTION_IN_PROGRESS" in output:
                return Result(True, "Proton VPN is already attempting to connect; waiting for its app to finish.")
            if "CONFLICT:" in output:
                conflict = output.split("CONFLICT:", 1)[1].strip()
                return Result(False, f"Proton VPN connection blocked by another VPN adapter: {conflict}")
            details = (result.stderr or output).strip()
            return Result(False, details or "Proton VPN button could not be activated.")
        except Exception as exc:
            return Result(False, f"Proton VPN UI control failed: {exc}")

    def connect(self, location="Automatic"):
        exe = self.detect()
        if not exe:
            return Result(False, "Proton VPN ইনস্টল করা নেই।")
        try:
            subprocess.Popen([exe], creationflags=CREATE_NO_WINDOW)
            return self._press_app_button("Connect", location)
        except Exception as ex:
            return Result(False, str(ex))

    def disconnect(self):
        exe = self.detect()
        if not exe:
            return Result(False, "Proton VPN ইনস্টল করা নেই।")
        try:
            subprocess.Popen([exe], creationflags=CREATE_NO_WINDOW)
            return self._press_app_button("Disconnect")
        except Exception as ex:
            return Result(False, str(ex))

    def status(self):
        return "Installed (connection state unavailable)" if self.detect() else "Not installed"

    def test_connection_ready(self) -> Result:
        if not self.detect():
            return Result(False, "FAILED: Proton VPN ইনস্টল করা নেই।")
        return Result(True, "SUCCESS: Proton VPN app পাওয়া গেছে; connection state অ্যাপ থেকেই দেখুন।")


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
# MACOS 3D GUI + EXACT TIMER + CITY BUTTON + DIRECT GITHUB ADMIN PANEL
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
    "Graphite Studio": {
        "bg": "#17191c",
        "card": "#22262a",
        "card_alt": "#2d3337",
        "border": "#4b5657",
        "accent": "#69d2b1",
        "accent_2": "#d8a66a",
        "success": "#55bd87",
        "danger": "#e56f70",
        "text": "#f1f3ef",
        "muted": "#aebbb7",
    },
    "Arctic Glass": {
        "bg": "#e8f1f2",
        "card": "#f8fbfa",
        "card_alt": "#dce9e9",
        "border": "#a9c1c2",
        "accent": "#087f8c",
        "accent_2": "#356b8c",
        "success": "#23845d",
        "danger": "#c5454b",
        "text": "#17323a",
        "muted": "#526e73",
    },
    "Midnight Copper": {
        "bg": "#171819",
        "card": "#242627",
        "card_alt": "#303333",
        "border": "#5c5148",
        "accent": "#e6a15b",
        "accent_2": "#c86d55",
        "success": "#73bd91",
        "danger": "#e36d67",
        "text": "#f4eee6",
        "muted": "#c0b5a8",
    },
    "Citrus Light": {
        "bg": "#f2f4e9",
        "card": "#ffffff",
        "card_alt": "#e8edd8",
        "border": "#c0cba5",
        "accent": "#39805b",
        "accent_2": "#cf7a32",
        "success": "#39805b",
        "danger": "#c94d48",
        "text": "#26362c",
        "muted": "#627264",
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
        QTableWidget,
        QTableWidgetItem,
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
    OFFICIAL_DOWNLOAD_PAGES = [
        ("Hotspot Shield", "https://www.hotspotshield.com/vpn/vpn-for-windows/"),
        ("Surfshark", "https://surfshark.com/download/windows"),
        ("CyberGhost", "https://www.cyberghostvpn.com/download/windows-vpn"),
        ("IPVanish", "https://www.ipvanish.com/vpn-setup/windows/"),
        ("PrivateVPN", "https://privatevpn.com/download/windows/"),
        ("Windscribe", "https://windscribe.com/download"),
        ("TunnelBear", "https://www.tunnelbear.com/download"),
        ("Mullvad", "https://mullvad.net/en/download/vpn/windows"),
        ("hide.me", "https://hide.me/en/software/windows"),
        ("PureVPN", "https://www.purevpn.com/download/windows-vpn"),
        ("VyprVPN", "https://www.vyprvpn.com/apps/"),
        ("AdGuard VPN", "https://adguard-vpn.com/en/download.html"),
        ("Bitdefender VPN", "https://www.bitdefender.com/en-us/consumer/vpn"),
        ("McAfee Secure VPN", "https://www.mcafee.com/en-us/vpn.html"),
        ("Norton VPN", "https://us.norton.com/products/norton-vpn"),
        ("Avast SecureLine VPN", "https://www.avast.com/secureline-vpn"),
        ("AVG Secure VPN", "https://www.avg.com/en-us/secure-vpn"),
        ("Kaspersky VPN", "https://www.kaspersky.com/vpn-secure-connection/download-vpn"),
        ("Mozilla VPN", "https://www.mozilla.org/en-US/products/vpn/download/"),
        ("PrivadoVPN", "https://privadovpn.com/software/"),
    ]

    UI_TRANSLATIONS = {
        "en": {
            "🚀 VPN Dashboard 3D": "🚀 VPN Dashboard",
            "⬇ Download Center": "⬇ Download Center",
            "🔐 Admin Panel": "🔐 Admin Panel",
            "⚙ Settings & Tray": "⚙ Settings & Tray",
            "⚡ CONNECT VPN": "⚡ CONNECT VPN",
            "⏹ DISCONNECT": "⏹ DISCONNECT",
            "🧪 TEST VPN": "🧪 TEST VPN",
            "🛡 VPN Provider:": "🛡 VPN Provider:",
            "📁 Location & City:": "📁 Location & City:",
            "⏱ Timer: ♾ Unlimited": "⏱ Timer: Unlimited",
            "♾ Unlimited (অটো অফ হবে না)": "♾ Unlimited (no auto-disconnect)",
            "⏳ 5 মিনিট": "⏳ 5 min",
            "⏳ 10 মিনিট": "⏳ 10 min",
            "⏳ 15 মিনিট": "⏳ 15 min",
            "⏳ 30 মিনিট": "⏳ 30 min",
            "⏳ 60 মিনিট": "⏳ 60 min",
            "Custom (Min):": "Custom (min):",
            "Set Time": "Set Time",
            "📋 Live Connection & Cloud Sync Console": "📋 Live Connection & Cloud Sync Console",
            "⬇ OFFICIAL VPN DOWNLOAD CENTER": "⬇ VPN DOWNLOAD CENTER",
            "Official VPN Installers": "Official VPN Installers",
            "📂 Download History:": "📂 Download History:",
            "📥 Minimize to Tray": "📥 Minimize to Tray",
            "🔄 Update Check": "🔄 Check for Updates",
            "⏱ Step 3: কত মিনিটের জন্য কানেক্ট করতে চান? (নির্ধারিত সময়ের আগে কখনোই ডিসকানেক্ট হবে না)": "⏱ Step 3: Choose session duration. The VPN stays connected until the timer ends.",
            "🔄 Step 4: Option Mode — আপনার দেওয়া সময় পূর্ণ হলে কী হবে?": "🔄 Step 4: Choose what happens when the timer ends.",
            "🔁 Same Country & City Loop — নির্ধারিত সময় শেষ হলে অফ হয়ে আবার একই কান্ট্রি ও সিটিতে কানেক্ট হবে": "🔁 Same Country & City Loop — reconnect to the same location.",
            "🌍 Auto Country Rotation — নির্ধারিত সময় শেষ হলে স্বয়ংক্রিয়ভাবে অন্য কান্ট্রি ও সিটিতে চেঞ্জ হবে": "🌍 Auto Country Rotation — reconnect to a different location.",
            "⏹ One-Time Disconnect — নির্ধারিত সময় শেষ হলে ভিপিএন ডিসকানেক্ট হয়ে বন্ধ থাকবে": "⏹ One-Time Disconnect — disconnect when the timer ends.",
            "📥 Minimize বা Close (✕) করলে অ্যাপ বন্ধ না হয়ে System Tray-তে ব্যাকগ্রাউন্ডে চালু থাকবে": "📥 Keep running in the system tray when minimized or closed",
            "🔔 কানেক্ট, ডিসকানেক্ট, আপডেট এবং রোটেশনের সময় Windows Desktop Notification দেখান": "🔔 Show Windows notifications for connections and updates",
            "🔊 কানেক্ট বা ডিসকানেক্ট হওয়ার সময় সাউন্ড অ্যালার্ট (Sound Chime) বাজান": "🔊 Play a sound when connecting or disconnecting",
            "📌 Keep Window Always on Top (সব উইন্ডোর ওপরে রাখুন)": "📌 Keep window always on top",
            "Download চাপলে অফিসিয়াল উৎস থেকে ইনস্টলার Downloads/SalmanBossVPN-এ নামবে। শেষ হলে ইনস্টলারটি চালু হবে।": "Download installers from official sources to Downloads/SalmanBossVPN and launch them when complete.",
        },
        "bn": {
            "🚀 VPN Dashboard 3D": "🚀 ভিপিএন ড্যাশবোর্ড",
            "⬇ Download Center": "⬇ ডাউনলোড সেন্টার",
            "🔐 Admin Panel": "🔐 অ্যাডমিন প্যানেল",
            "⚙ Settings & Tray": "⚙ সেটিংস ও ট্রে",
            "⚡ CONNECT VPN": "⚡ ভিপিএন কানেক্ট",
            "⏹ DISCONNECT": "⏹ সংযোগ বিচ্ছিন্ন",
            "🧪 TEST VPN": "🧪 ভিপিএন পরীক্ষা",
            "🛡 VPN Provider:": "🛡 ভিপিএন সেবা:",
            "📁 Location & City:": "📁 অবস্থান ও শহর:",
            "📂  1. Select Country": "📂  ১. দেশ নির্বাচন",
            "🏙  2. City: Automatic": "🏙  ২. শহর: স্বয়ংক্রিয়",
            "⏱ Timer: ♾ Unlimited": "⏱ টাইমার: সীমাহীন",
            "♾ Unlimited (অটো অফ হবে না)": "♾ সীমাহীন (অটো বন্ধ হবে না)",
            "⏳ 5 মিনিট": "⏳ ৫ মিনিট",
            "⏳ 10 মিনিট": "⏳ ১০ মিনিট",
            "⏳ 15 মিনিট": "⏳ ১৫ মিনিট",
            "⏳ 30 মিনিট": "⏳ ৩০ মিনিট",
            "⏳ 60 মিনিট": "⏳ ৬০ মিনিট",
            "Custom (Min):": "নিজস্ব সময় (মিনিট):",
            "Set Time": "সময় নির্ধারণ",
            "📋 Live Connection & Cloud Sync Console": "📋 সংযোগ ও ক্লাউড লগ",
            "⬇ OFFICIAL VPN DOWNLOAD CENTER": "⬇ ভিপিএন ডাউনলোড সেন্টার",
            "Official VPN Installers": "অফিসিয়াল ভিপিএন ইনস্টলার",
            "📂 Download History:": "📂 ডাউনলোড ইতিহাস:",
            "📥 Minimize to Tray": "📥 ট্রেতে ছোট করুন",
            "🔄 Update Check": "🔄 আপডেট দেখুন",
            "⏱ Step 3: কত মিনিটের জন্য কানেক্ট করতে চান? (নির্ধারিত সময়ের আগে কখনোই ডিসকানেক্ট হবে না)": "⏱ ধাপ ৩: কতক্ষণ সংযুক্ত থাকবেন? (সময় শেষ হওয়ার আগে সংযোগ বিচ্ছিন্ন হবে না)",
            "🔄 Step 4: Option Mode — আপনার দেওয়া সময় পূর্ণ হলে কী হবে?": "🔄 ধাপ ৪: সময় শেষ হলে কী হবে",
            "🔁 Same Country & City Loop — নির্ধারিত সময় শেষ হলে অফ হয়ে আবার একই কান্ট্রি ও সিটিতে কানেক্ট হবে": "🔁 একই দেশ ও শহরে আবার সংযোগ",
            "🌍 Auto Country Rotation — নির্ধারিত সময় শেষ হলে স্বয়ংক্রিয়ভাবে অন্য কান্ট্রি ও সিটিতে চেঞ্জ হবে": "🌍 স্বয়ংক্রিয়ভাবে অন্য দেশে সংযোগ",
            "⏹ One-Time Disconnect — নির্ধারিত সময় শেষ হলে ভিপিএন ডিসকানেক্ট হয়ে বন্ধ থাকবে": "⏹ সময় শেষে সংযোগ বিচ্ছিন্ন",
            "📥 Minimize বা Close (✕) করলে অ্যাপ বন্ধ না হয়ে System Tray-তে ব্যাকগ্রাউন্ডে চালু থাকবে": "📥 ছোট বা বন্ধ করলে অ্যাপ ট্রেতে চালু থাকবে",
            "🔔 কানেক্ট, ডিসকানেক্ট, আপডেট এবং রোটেশনের সময় Windows Desktop Notification দেখান": "🔔 সংযোগ ও আপডেটে Windows নোটিফিকেশন দেখান",
            "🔊 কানেক্ট বা ডিসকানেক্ট হওয়ার সময় সাউন্ড অ্যালার্ট (Sound Chime) বাজান": "🔊 সংযোগ বা বিচ্ছিন্ন হলে শব্দ করুন",
            "📌 Keep Window Always on Top (সব উইন্ডোর ওপরে রাখুন)": "📌 উইন্ডো সবসময় ওপরে রাখুন",
            "Download চাপলে অফিসিয়াল উৎস থেকে ইনস্টলার Downloads/SalmanBossVPN-এ নামবে। শেষ হলে ইনস্টলারটি চালু হবে।": "অফিসিয়াল ইনস্টলার Downloads/SalmanBossVPN-এ নামবে এবং শেষে চালু হবে।",
        },
        "both": {
            "🚀 VPN Dashboard 3D": "🚀 VPN Dashboard / ভিপিএন ড্যাশবোর্ড",
            "⬇ Download Center": "⬇ Download Center / ডাউনলোড সেন্টার",
            "🔐 Admin Panel": "🔐 Admin Panel / অ্যাডমিন প্যানেল",
            "⚙ Settings & Tray": "⚙ Settings / সেটিংস",
            "⚡ CONNECT VPN": "⚡ CONNECT VPN / ভিপিএন কানেক্ট",
            "⏹ DISCONNECT": "⏹ DISCONNECT / সংযোগ বিচ্ছিন্ন",
            "🧪 TEST VPN": "🧪 TEST VPN / ভিপিএন পরীক্ষা",
            "🛡 VPN Provider:": "🛡 VPN Provider / ভিপিএন সেবা:",
            "📁 Location & City:": "📁 Location & City / অবস্থান ও শহর:",
            "⏱ Timer: ♾ Unlimited": "⏱ Timer: Unlimited / সীমাহীন",
            "♾ Unlimited (অটো অফ হবে না)": "♾ Unlimited / সীমাহীন",
            "⏳ 5 মিনিট": "⏳ 5 min / ৫ মিনিট",
            "⏳ 10 মিনিট": "⏳ 10 min / ১০ মিনিট",
            "⏳ 15 মিনিট": "⏳ 15 min / ১৫ মিনিট",
            "⏳ 30 মিনিট": "⏳ 30 min / ৩০ মিনিট",
            "⏳ 60 মিনিট": "⏳ 60 min / ৬০ মিনিট",
            "Custom (Min):": "Custom (min) / নিজস্ব সময়:",
            "Set Time": "Set Time / সময় নির্ধারণ",
            "📋 Live Connection & Cloud Sync Console": "📋 Live Connection & Cloud Sync / সংযোগ ও ক্লাউড লগ",
            "⬇ OFFICIAL VPN DOWNLOAD CENTER": "⬇ VPN DOWNLOAD CENTER / ডাউনলোড সেন্টার",
            "Official VPN Installers": "Official VPN Installers / অফিসিয়াল ইনস্টলার",
            "📂 Download History:": "📂 Download History / ডাউনলোড ইতিহাস:",
            "📥 Minimize to Tray": "📥 Minimize to Tray / ট্রেতে ছোট করুন",
            "🔄 Update Check": "🔄 Check Updates / আপডেট দেখুন",
            "⏱ Step 3: কত মিনিটের জন্য কানেক্ট করতে চান? (নির্ধারিত সময়ের আগে কখনোই ডিসকানেক্ট হবে না)": "⏱ Step 3: Session duration / সংযোগের সময়",
            "🔄 Step 4: Option Mode — আপনার দেওয়া সময় পূর্ণ হলে কী হবে?": "🔄 Step 4: When the timer ends / সময় শেষে",
            "🔁 Same Country & City Loop — নির্ধারিত সময় শেষ হলে অফ হয়ে আবার একই কান্ট্রি ও সিটিতে কানেক্ট হবে": "🔁 Same Country & City Loop / একই দেশ ও শহরে আবার সংযোগ",
            "🌍 Auto Country Rotation — নির্ধারিত সময় শেষ হলে স্বয়ংক্রিয়ভাবে অন্য কান্ট্রি ও সিটিতে চেঞ্জ হবে": "🌍 Auto Country Rotation / অন্য দেশে স্বয়ংক্রিয় সংযোগ",
            "⏹ One-Time Disconnect — নির্ধারিত সময় শেষ হলে ভিপিএন ডিসকানেক্ট হয়ে বন্ধ থাকবে": "⏹ One-Time Disconnect / সময় শেষে বিচ্ছিন্ন",
            "📥 Minimize বা Close (✕) করলে অ্যাপ বন্ধ না হয়ে System Tray-তে ব্যাকগ্রাউন্ডে চালু থাকবে": "📥 System tray / ট্রেতে চালু রাখুন",
            "🔔 কানেক্ট, ডিসকানেক্ট, আপডেট এবং রোটেশনের সময় Windows Desktop Notification দেখান": "🔔 Windows notifications / Windows নোটিফিকেশন",
            "🔊 কানেক্ট বা ডিসকানেক্ট হওয়ার সময় সাউন্ড অ্যালার্ট (Sound Chime) বাজান": "🔊 Sound alerts / শব্দ সতর্কতা",
            "📌 Keep Window Always on Top (সব উইন্ডোর ওপরে রাখুন)": "📌 Always on top / সবসময় ওপরে",
            "Download চাপলে অফিসিয়াল উৎস থেকে ইনস্টলার Downloads/SalmanBossVPN-এ নামবে। শেষ হলে ইনস্টলারটি চালু হবে।": "Download from official sources / অফিসিয়াল ইনস্টলার নামিয়ে চালু করুন",
        },
    }

    class LaunchSetupDialog(QDialog):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setWindowTitle("Welcome | স্বাগতম")
            self.setMinimumWidth(420)
            layout = QVBoxLayout(self)
            layout.addWidget(QLabel("Choose language / ভাষা নির্বাচন করুন"))
            self.language_combo = QComboBox()
            self.language_combo.addItem("English", "en")
            self.language_combo.addItem("বাংলা", "bn")
            self.language_combo.addItem("Both / উভয়", "both")
            layout.addWidget(self.language_combo)

            layout.addWidget(QLabel("Choose role / ব্যবহারের ধরন নির্বাচন করুন"))
            self.role_combo = QComboBox()
            self.role_combo.addItem("Client / ক্লায়েন্ট", "client")
            self.role_combo.addItem("Administrator / অ্যাডমিন", "admin")
            layout.addWidget(self.role_combo)

            self.pin_label = QLabel("Admin PIN / অ্যাডমিন পিন")
            self.pin_input = QLineEdit()
            self.pin_input.setEchoMode(QLineEdit.Password)
            self.pin_input.setPlaceholderText("Enter PIN / পিন লিখুন")
            layout.addWidget(self.pin_label)
            layout.addWidget(self.pin_input)
            self.role_combo.currentIndexChanged.connect(self._update_pin_visibility)
            self._update_pin_visibility()

            start_button = QPushButton("Continue / এগিয়ে যান")
            start_button.clicked.connect(self.accept)
            layout.addWidget(start_button)

        def _update_pin_visibility(self):
            is_admin = self.role_combo.currentData() == "admin"
            self.pin_label.setVisible(is_admin)
            self.pin_input.setVisible(is_admin)

        @property
        def selections(self):
            return self.language_combo.currentData(), self.role_combo.currentData(), self.pin_input.text()

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
    # MACOS 3D COUNTRY & CITY PICKER DIALOGS
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
    # BACKGROUND WORKERS (VPN ACTION + GITHUB GIST CLOUD SYNC + DOWNLOAD)
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

    class GitHubSyncWorker(QThread):
        """Runs GitHub Gist API calls in a background thread so the GUI stays smooth."""
        finished_sync = Signal(bool, str, str, str)

        def __init__(self, token: str, gist_id_or_url: str, state: dict, include_live_script: bool):
            super().__init__()
            self.token = token
            self.gist_id_or_url = gist_id_or_url
            self.state = state
            self.include_live_script = include_live_script

        def run(self):
            ok, msg, gid, raw_url = push_state_to_github_gist(
                self.token,
                self.gist_id_or_url,
                self.state,
                self.include_live_script,
            )
            self.finished_sync.emit(ok, msg, gid, raw_url)

    class GitHubReleaseUploadWorker(QThread):
        progress = Signal(str)
        completed = Signal(str, str)
        failed = Signal(str)

        def __init__(self, token: str, repository: str, version: str, file_path: str, notes: str):
            super().__init__()
            self.token = token.strip()
            self.repository = repository.strip()
            self.version = version.strip()
            self.file_path = Path(file_path)
            self.notes = notes

        def run(self):
            try:
                if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository):
                    raise ValueError("Repository format must be owner/repository.")
                if not self.token:
                    raise ValueError("A GitHub token is required.")
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}", self.version):
                    raise ValueError("Version must use letters, numbers, dot, underscore, +, or hyphen.")
                if not self.file_path.is_file() or self.file_path.suffix.lower() != ".exe":
                    raise ValueError("Select a valid portable .exe file.")
                if self.file_path.stat().st_size > 500 * 1024 * 1024:
                    raise ValueError("The portable EXE is larger than the 500 MB upload limit.")

                api_root = f"https://api.github.com/repos/{self.repository}"
                headers = {
                    "Authorization": f"Bearer {self.token}",
                    "Accept": "application/vnd.github+json",
                    "User-Agent": f"SalmanBossVPN-Admin/{APP_VERSION}",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "Content-Type": "application/json; charset=utf-8",
                }
                repository_request = urllib.request.Request(f"{api_root}", headers=headers)
                with urllib.request.urlopen(repository_request, timeout=30) as response:
                    repository_info = json.loads(response.read().decode("utf-8"))
                if repository_info.get("private"):
                    raise ValueError("The Release repository must be public so client PCs can download updates.")
                release_request = urllib.request.Request(
                    f"{api_root}/releases",
                    data=json.dumps(
                        {
                            "tag_name": self.version,
                            "name": f"Salman Boss VPN Manager {self.version}",
                            "body": self.notes,
                            "draft": True,
                            "prerelease": False,
                        }
                    ).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )
                self.progress.emit("Creating draft GitHub Release...")
                with urllib.request.urlopen(release_request, timeout=30) as response:
                    release = json.loads(response.read().decode("utf-8"))

                asset_bytes = self.file_path.read_bytes()
                digest = hashlib.sha256(asset_bytes).hexdigest()
                upload_url = release["upload_url"].split("{", 1)[0]
                upload_url += "?name=" + urllib.parse.quote(self.file_path.name)
                upload_headers = {
                    "Authorization": f"Bearer {self.token}",
                    "Accept": "application/vnd.github+json",
                    "User-Agent": f"SalmanBossVPN-Admin/{APP_VERSION}",
                    "Content-Type": "application/octet-stream",
                    "X-GitHub-Api-Version": "2022-11-28",
                }
                asset_request = urllib.request.Request(
                    upload_url,
                    data=asset_bytes,
                    headers=upload_headers,
                    method="POST",
                )
                self.progress.emit("Uploading EXE asset...")
                with urllib.request.urlopen(asset_request, timeout=180) as response:
                    asset = json.loads(response.read().decode("utf-8"))

                publish_request = urllib.request.Request(
                    f"{api_root}/releases/{release['id']}",
                    data=json.dumps({"draft": False}).encode("utf-8"),
                    headers=headers,
                    method="PATCH",
                )
                self.progress.emit("Publishing release...")
                with urllib.request.urlopen(publish_request, timeout=30):
                    pass
                self.completed.emit(asset["browser_download_url"], digest)
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", errors="replace")
                self.failed.emit(f"GitHub Release API Error ({error.code}): {detail[:500]}")
            except Exception as error:
                self.failed.emit(str(error))

    class GitHubScriptCommitWorker(QThread):
        """Commits a selected Python file and refreshes the repo control JSON."""
        progress = Signal(str)
        completed = Signal(object)
        failed = Signal(str)

        def __init__(
            self,
            token: str,
            repository: str,
            branch: str,
            local_file: str,
            repo_path: str,
            version: str,
            update_message: str,
            state: dict,
        ):
            super().__init__()
            self.token = token
            self.repository = repository
            self.branch = branch
            self.local_file = local_file
            self.repo_path = repo_path
            self.version = version
            self.update_message = update_message
            self.state = state

        def run(self):
            try:
                result = publish_python_file_to_github(
                    self.token,
                    self.repository,
                    self.branch,
                    self.local_file,
                    self.repo_path,
                    self.version,
                    self.update_message,
                    self.state,
                    progress=self.progress.emit,
                )
                self.completed.emit(result)
            except Exception as error:
                self.failed.emit(str(error))

    class InstallerLinkParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.links = []
            self.current_link = None

        def handle_starttag(self, tag, attrs):
            if tag.lower() == "a":
                href = dict(attrs).get("href")
                if href:
                    self.current_link = [href, []]

        def handle_data(self, data):
            if self.current_link is not None:
                self.current_link[1].append(data)

        def handle_endtag(self, tag):
            if tag.lower() == "a" and self.current_link is not None:
                href, text = self.current_link
                self.links.append((href, " ".join(text).strip()))
                self.current_link = None

    class DownloadWorker(QThread):
        progress = Signal(int, str)
        completed = Signal(str, str)
        failed = Signal(str, str)

        def __init__(self, name, url, folder, allowed_domains=()):
            super().__init__()
            self.name, self.url, self.folder = name, url, folder
            self.allowed_domains = tuple(allowed_domains)
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

                trusted_domains = {
                    "PIA": ("privateinternetaccess.com",),
                    "ExpressVPN": ("expressvpn.com",),
                    "Proton VPN": ("github.com", "githubusercontent.com"),
                    "NordVPN": ("nordcdn.com", "nordvpn.com"),
                    "Hotspot Shield": ("hotspotshield.com", "anchorfree.com"),
                    "Surfshark": ("surfshark.com",),
                    "CyberGhost": ("cyberghostvpn.com", "cyberghost.com"),
                    "IPVanish": ("ipvanish.com",),
                    "PrivateVPN": ("privatevpn.com",),
                    "Windscribe": ("windscribe.com",),
                    "TunnelBear": ("tunnelbear.com",),
                    "Mullvad": ("mullvad.net",),
                    "hide.me": ("hide.me",),
                    "PureVPN": ("purevpn.com", "dzglif4kkvz04.cloudfront.net"),
                    "VyprVPN": ("vyprvpn.com",),
                    "AdGuard VPN": ("adguard.com", "adguardcdn.com"),
                    "Bitdefender VPN": ("bitdefender.com",),
                    "McAfee Secure VPN": ("mcafee.com",),
                    "Norton VPN": ("norton.com", "nortonlifelock.com"),
                    "Avast SecureLine VPN": ("avast.com", "avcdn.net"),
                    "AVG Secure VPN": ("avg.com", "avcdn.net"),
                    "Kaspersky VPN": ("kaspersky.com", "kaspersky-labs.com"),
                    "Mozilla VPN": ("mozilla.org", "mozilla.net"),
                    "PrivadoVPN": ("privadovpn.com",),
                }

                for _ in range(3):
                    if self.cancel_requested:
                        self.failed.emit(self.name, "Download cancelled.")
                        return
                    path = urllib.parse.urlparse(url).path.lower()
                    if path.endswith((".exe", ".msi")):
                        break
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=40) as response:
                        page_url = response.geturl()
                        content_type = response.headers.get_content_type()
                        if content_type not in ("text/html", "application/xhtml+xml"):
                            url = page_url
                            break
                        page = response.read(4 * 1024 * 1024).decode("utf-8", errors="replace")
                    parser = InstallerLinkParser()
                    parser.feed(page)
                    installer_links = []
                    next_pages = []
                    for href, link_text in parser.links:
                        target = urllib.parse.urljoin(page_url, href)
                        target_path = urllib.parse.urlparse(target).path.lower()
                        label = link_text.lower()
                        if target_path.endswith((".exe", ".msi")):
                            installer_links.append((target, label))
                        elif "windows" in label and any(word in label for word in ("download", "install", "app")):
                            next_pages.append(target)
                    if installer_links:
                        installer_links.sort(
                            key=lambda item: (
                                "windows" not in item[1],
                                not any(word in item[1] for word in ("download", "installer", "setup")),
                            )
                        )
                        url = installer_links[0][0]
                        break
                    if next_pages:
                        url = next_pages[0]
                        continue
                    raise RuntimeError("Official page did not expose a direct Windows installer link.")
                else:
                    raise RuntimeError("Could not resolve a direct Windows installer from the official page.")

                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=60) as response:
                    final_url = response.geturl()
                    host = urllib.parse.urlparse(final_url).hostname or ""
                    trusted = any(
                        host == domain or host.endswith("." + domain)
                        for domain in (trusted_domains.get(self.name) or self.allowed_domains)
                    )
                    if not trusted:
                        raise RuntimeError("Download redirect left the provider's trusted official domain.")
                    filename = response.headers.get_filename()
                    if not filename:
                        filename = Path(urllib.parse.urlparse(final_url).path).name
                    filename = Path(filename).name
                    if not filename.lower().endswith((".exe", ".msi")):
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
                    last_report_time = time.monotonic()
                    last_report_bytes = 0
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
                            now = time.monotonic()
                            elapsed = now - last_report_time
                            speed_mbps = (received - last_report_bytes) / 1048576 / elapsed if elapsed else 0
                            size_text = f"{speed_mbps:.2f} MB/s  •  {received / 1048576:.1f} MB"
                            if total:
                                size_text += f" / {total / 1048576:.1f} MB"
                            self.progress.emit(percent, f"{self.name}: {percent}%  •  {size_text}")
                            if elapsed >= 0.35:
                                last_report_time = now
                                last_report_bytes = received
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
        def __init__(self, user_role: str, language: str):
            super().__init__()
            self.saved_cfg = load_settings()
            self.user_role = user_role
            self.interface_language = language
            self.is_admin_session = user_role == "admin"
            self.current_theme_name = self.saved_cfg.get("theme", "macOS Sonoma Dark (3D)")
            if self.current_theme_name not in THEMES:
                self.current_theme_name = "macOS Sonoma Dark (3D)"

            self.is_master_admin_unlocked = self.is_admin_session
            self.admin_pin = str(self.saved_cfg.get("admin_pin", DEFAULT_ADMIN_PIN))
            self.last_notified_version = self.saved_cfg.get("last_notified_version", APP_VERSION)

            self.force_quit = False
            self.setWindowTitle(f"{APP} v{APP_VERSION} — Direct GitHub Cloud Edition")
            self.setWindowIcon(create_3d_tray_icon("#38bdf8", "#6366f1"))
            self.setMinimumSize(720, 560)
            self.resize(1040, 820)

            self.country_tree: dict[str, list[tuple[str, str]]] = {}
            self.selected_country: str = ""
            self.selected_city_label: str = ""
            self.selected_region_slug: str = "Automatic"
            self.timer_enabled: bool = False
            self.configured_minutes: int = 0
            self.remaining_seconds: int = 0
            self.is_reconnecting_cycle: bool = False
            self.active_worker: Optional[ActionWorker] = None
            self.gh_worker: Optional[GitHubSyncWorker] = None
            self.release_worker: Optional[GitHubReleaseUploadWorker] = None
            self.proxy_profiles = list(self.saved_cfg.get("proxy_profiles", []))
            self.active_history_sessions = {}
            self.proxy_session_started = None
            try:
                self.usage_history = json.loads(HISTORY_FILE.read_text(encoding="utf-8")) if HISTORY_FILE.exists() else []
                if not isinstance(self.usage_history, list):
                    self.usage_history = []
            except Exception:
                self.usage_history = []
            self.previous_user_proxy = self.saved_cfg.get("proxy_previous_user_settings")

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
                f"macOS 3D + GITHUB CLOUD  •  v{APP_VERSION}  •  "
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

            # Remote Lock Banner
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

            # COMPACT COUNTRY BUTTON + COMPACT CITY BUTTON
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

            self.favorite_servers = list(self.saved_cfg.get("favorite_servers", []))
            favorite_bar = QFrame()
            favorite_bar.setObjectName("card3d")
            favorite_layout = QHBoxLayout(favorite_bar)
            favorite_layout.setContentsMargins(12, 8, 12, 8)
            favorite_layout.addWidget(QLabel("★ Favorite Servers"))
            self.favorite_buttons_layout = QHBoxLayout()
            favorite_layout.addLayout(self.favorite_buttons_layout, 1)
            add_favorite_button = QPushButton("＋ Save Current")
            add_favorite_button.clicked.connect(self.add_current_favorite)
            favorite_layout.addWidget(add_favorite_button)
            self.vpn_layout.addWidget(favorite_bar)
            self.refresh_favorite_servers()

            # STEP 3 CARD: STRICT CONNECTION TIMER
            self.duration_card = QFrame()
            self.duration_card.setObjectName("stepCard")
            add_3d_shadow(self.duration_card, blur=22, y_offset=5)
            dur_vbox = QVBoxLayout(self.duration_card)
            self.dur_title = QLabel(
                "⏱ Step 3: কত মিনিটের জন্য কানেক্ট করতে চান? (নির্ধারিত সময়ের আগে কখনোই ডিসকানেক্ট হবে না)"
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
            log_hdr = QLabel("📋 Live Connection & Cloud Sync Console")
            log_hdr.setStyleSheet("font-weight:700;")
            self.log = QTextEdit()
            self.log.setReadOnly(True)
            self.log.setMinimumHeight(110)
            log_vbox.addWidget(log_hdr)
            log_vbox.addWidget(self.log)
            self.vpn_layout.addWidget(log_card)

            vpn_scroll.setWidget(vpn_container)
            self.tabs.addTab(vpn_scroll, "🚀 VPN Dashboard 3D")

            proxy_scroll = QScrollArea()
            proxy_scroll.setWidgetResizable(True)
            proxy_scroll.setFrameShape(QFrame.NoFrame)
            proxy_tab = QWidget()
            proxy_layout = QVBoxLayout(proxy_tab)
            proxy_layout.setContentsMargins(12, 12, 12, 12)
            proxy_layout.setSpacing(12)
            proxy_title = QLabel("🌐 IP & Proxy Setup")
            proxy_title.setStyleSheet("font-size:18px;font-weight:800;")
            proxy_note = QLabel(
                "Applies only to this Windows user's Internet Settings. Does not change WinHTTP, VPN/TAP adapters, or other users. "
                "Proxy username/password are not saved and are not applied by this Windows setting."
            )
            proxy_note.setObjectName("muted")
            proxy_note.setWordWrap(True)
            proxy_layout.addWidget(proxy_title)
            proxy_layout.addWidget(proxy_note)

            proxy_form = QGridLayout()
            proxy_form.addWidget(QLabel("Provider:"), 0, 0)
            self.proxy_provider_input = QLineEdit()
            self.proxy_provider_input.setPlaceholderText("BigMama Proxy, 9Proxy, NiceProxy...")
            proxy_form.addWidget(self.proxy_provider_input, 0, 1)
            proxy_form.addWidget(QLabel("Protocol:"), 0, 2)
            self.proxy_protocol_input = QComboBox()
            self.proxy_protocol_input.addItems(("HTTP", "HTTPS", "SOCKS5"))
            proxy_form.addWidget(self.proxy_protocol_input, 0, 3)

            proxy_form.addWidget(QLabel("Host / IP:"), 1, 0)
            self.proxy_host_input = QLineEdit()
            proxy_form.addWidget(self.proxy_host_input, 1, 1)
            proxy_form.addWidget(QLabel("Port:"), 1, 2)
            self.proxy_port_input = QLineEdit()
            self.proxy_port_input.setMaximumWidth(110)
            proxy_form.addWidget(self.proxy_port_input, 1, 3)

            proxy_form.addWidget(QLabel("Username (not saved):"), 2, 0)
            self.proxy_user_input = QLineEdit()
            proxy_form.addWidget(self.proxy_user_input, 2, 1)
            proxy_form.addWidget(QLabel("Password (not saved):"), 2, 2)
            self.proxy_password_input = QLineEdit()
            self.proxy_password_input.setEchoMode(QLineEdit.Password)
            proxy_form.addWidget(self.proxy_password_input, 2, 3)

            proxy_form.addWidget(QLabel("Paste Host:Port:User:Pass:"), 3, 0)
            self.proxy_paste_input = QLineEdit()
            proxy_form.addWidget(self.proxy_paste_input, 3, 1, 1, 2)
            parse_proxy_btn = QPushButton("Parse")
            parse_proxy_btn.clicked.connect(self.parse_proxy_paste)
            proxy_form.addWidget(parse_proxy_btn, 3, 3)
            proxy_layout.addLayout(proxy_form)

            proxy_actions = QHBoxLayout()
            save_proxy_btn = QPushButton("＋ Save Profile")
            save_proxy_btn.clicked.connect(self.save_proxy_profile)
            self.apply_proxy_btn = QPushButton("🚀 Apply to Windows User Proxy")
            self.apply_proxy_btn.setObjectName("primaryBtn")
            self.apply_proxy_btn.clicked.connect(self.apply_selected_proxy)
            disconnect_proxy_btn = QPushButton("🛑 Disconnect & Restore Previous Proxy")
            disconnect_proxy_btn.setObjectName("dangerBtn")
            disconnect_proxy_btn.clicked.connect(self.restore_user_proxy)
            delete_proxy_btn = QPushButton("🗑 Delete Profile")
            delete_proxy_btn.clicked.connect(self.delete_proxy_profile)
            proxy_actions.addWidget(save_proxy_btn)
            proxy_actions.addWidget(self.apply_proxy_btn)
            proxy_actions.addWidget(disconnect_proxy_btn)
            proxy_actions.addWidget(delete_proxy_btn)
            proxy_layout.addLayout(proxy_actions)

            self.proxy_profile_list = QListWidget()
            self.proxy_profile_list.currentRowChanged.connect(self.load_selected_proxy_profile)
            proxy_layout.addWidget(self.proxy_profile_list, 1)
            self.proxy_status_label = QLabel("Proxy status: inactive")
            self.proxy_ping_label = QLabel("Ping: not measured")
            self.proxy_timer_label = QLabel("Session: 00:00:00")
            self.proxy_data_label = QLabel("Data used: not measured")
            status_row = QHBoxLayout()
            for label in (self.proxy_status_label, self.proxy_ping_label, self.proxy_timer_label, self.proxy_data_label):
                label.setObjectName("muted")
                status_row.addWidget(label)
            proxy_layout.addLayout(status_row)
            self.refresh_proxy_profiles()
            proxy_scroll.setWidget(proxy_tab)
            self.tabs.addTab(proxy_scroll, "🌐 IP & Proxy Setup")

            history_scroll = QScrollArea()
            history_scroll.setWidgetResizable(True)
            history_scroll.setFrameShape(QFrame.NoFrame)
            history_tab = QWidget()
            history_layout = QVBoxLayout(history_tab)
            history_title = QLabel("📊 Usage & Data History")
            history_title.setStyleSheet("font-size:18px;font-weight:800;")
            history_note = QLabel("History is stored locally. Data volume is not measured by this app.")
            history_note.setObjectName("muted")
            history_layout.addWidget(history_title)
            history_layout.addWidget(history_note)
            self.history_table = QTableWidget(0, 5)
            self.history_table.setHorizontalHeaderLabels(("Type / Provider", "Target", "Started", "Duration", "Data"))
            history_layout.addWidget(self.history_table, 1)
            history_actions = QHBoxLayout()
            clear_history_btn = QPushButton("🗑 Clear History")
            clear_history_btn.clicked.connect(self.clear_usage_history)
            export_history_btn = QPushButton("📥 Export History")
            export_history_btn.clicked.connect(self.export_usage_history)
            history_actions.addWidget(clear_history_btn)
            history_actions.addWidget(export_history_btn)
            history_layout.addLayout(history_actions)
            history_scroll.setWidget(history_tab)
            self.tabs.addTab(history_scroll, "📊 Usage & Data History")
            self.refresh_usage_history()

            # ==================== TAB 2: DOWNLOAD CENTER ====================
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
                "Download চাপলে অফিসিয়াল উৎস থেকে ইনস্টলার Downloads/SalmanBossVPN-এ নামবে। "
                "শেষ হলে ইনস্টলারটি চালু হবে।"
            )
            note.setObjectName("muted")
            note.setWordWrap(True)
            dl.addWidget(intro)
            dl.addWidget(note)

            self.download_folder = Path.home() / "Downloads" / "SalmanBossVPN"
            self.download_workers = {}
            self.download_rows = {}
            self.download_allowed_domains = {}
            self.download_grid = None
            self.download_card_count = 0

            add_custom_installer = QPushButton("＋ Add Custom VPN Installer")
            add_custom_installer.setObjectName("accentBtn")
            add_custom_installer.clicked.connect(self.add_custom_installer)
            dl.addWidget(add_custom_installer)

            group = QGroupBox("Official VPN Installers")
            gl = QGridLayout(group)
            gl.setSpacing(14)
            gl.setContentsMargins(14, 20, 14, 14)
            self.download_grid = gl
            for name, url in OFFICIAL_DOWNLOADS + OFFICIAL_DOWNLOAD_PAGES:
                self._add_download_card(name, url)
            for item in self.saved_cfg.get("custom_installers", []):
                if isinstance(item, dict):
                    name = str(item.get("name", "")).strip()
                    url = str(item.get("url", "")).strip()
                    host = urllib.parse.urlparse(url).hostname or ""
                    if name and url.startswith("https://") and host:
                        self._add_download_card(name, url, (host.lower(),))

            dl.addWidget(group)

            self.download_history = QListWidget()
            self.download_history.setMinimumHeight(110)
            dl.addWidget(QLabel("📂 Download History:"))
            dl.addWidget(self.download_history)

            dl_scroll.setWidget(downloads)
            self.tabs.addTab(dl_scroll, "⬇ Download Center")

            # ==================== TAB 3: MASTER ADMIN PANEL (DIRECT GITHUB API PUSH) ====================
            admin_scroll = QScrollArea()
            admin_scroll.setWidgetResizable(True)
            admin_scroll.setFrameShape(QFrame.NoFrame)
            admin_tab = QWidget()
            adm_layout = QVBoxLayout(admin_tab)
            adm_layout.setContentsMargins(10, 10, 10, 10)
            adm_layout.setSpacing(14)

            # PIN Lock Card
            self.admin_lock_card = QFrame()
            self.admin_lock_card.setObjectName("card3d")
            lock_vbox = QVBoxLayout(self.admin_lock_card)
            lock_vbox.setContentsMargins(20, 18, 20, 18)
            lock_vbox.setSpacing(10)

            lock_title = QLabel("🔐 SALMAN BOSS — MASTER ADMIN PANEL (DIRECT GITHUB CLOUD)")
            lock_title.setStyleSheet("font-size:17px;font-weight:900;")
            lock_desc = QLabel(
                "পিন কোড দিয়ে আনলক করুন। ব্রাউজারে না ঢুকেই এখান থেকে সরাসরি GitHub-এ কমান্ড পাঠিয়ে "
                "অন্য সব পিসির সফটওয়্যার অফ/অন এবং অটো-আপডেট করতে পারবেন।"
            )
            lock_desc.setObjectName("muted")
            lock_desc.setWordWrap(True)

            pin_row = QHBoxLayout()
            self.pin_input = QLineEdit()
            self.pin_input.setEchoMode(QLineEdit.Password)
            self.pin_input.setPlaceholderText("🔑 Enter Admin PIN Code...")
            self.pin_input.setMinimumHeight(38)
            unlock_btn = QPushButton("🔓 Unlock Master Admin Panel")
            unlock_btn.setObjectName("primaryBtn")
            unlock_btn.setMinimumHeight(38)
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
            ctrl_vbox.setContentsMargins(18, 18, 18, 18)
            ctrl_vbox.setSpacing(14)

            adm_hdr = QLabel("👑 DIRECT GITHUB CLOUD CONTROL CENTER (NO BROWSER REQUIRED)")
            adm_hdr.setStyleSheet("font-size:17px;font-weight:900;")
            ctrl_vbox.addWidget(adm_hdr)

            self.chk_master_pc = QCheckBox(
                "✅ এটি আমার মেইন অ্যাডমিন পিসি (Master PC) — রিমোট লক করলেও আমার পিসিতে সবসময় কাজ চলবে"
            )
            self.chk_master_pc.setChecked(self.is_master_admin_unlocked)
            self.chk_master_pc.toggled.connect(self.toggle_master_pc_mode)
            ctrl_vbox.addWidget(self.chk_master_pc)

            # SECTION A: GitHub Direct API Credentials (One-Time Setup)
            gh_box = QGroupBox("1. GitHub API Setup (PAT needs gist + selected repo Contents: write)")
            gh_grid = QGridLayout(gh_box)

            gh_grid.addWidget(QLabel("GitHub Token (PAT):"), 0, 0)
            self.adm_gh_token = QLineEdit(self.saved_cfg.get("github_token", ""))
            self.adm_gh_token.setEchoMode(QLineEdit.Password)
            self.adm_gh_token.setPlaceholderText("GitHub PAT with gist and Contents: write for the selected repo")
            gh_grid.addWidget(self.adm_gh_token, 0, 1)

            btn_get_token = QPushButton("🌐 Get Token")
            btn_get_token.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl("https://github.com/settings/tokens/new?scopes=gist,repo&description=SalmanBossVPNManager"))
            )
            gh_grid.addWidget(btn_get_token, 0, 2)

            gh_grid.addWidget(QLabel("Gist ID / Gist URL:"), 1, 0)
            self.adm_gist_id = QLineEdit(self.saved_cfg.get("github_gist_id", ""))
            self.adm_gist_id.setPlaceholderText("আপনার Gist URL বা ID দিন (না থাকলে ডানপাশের Auto-Create বাটনে ক্লিক করুন)")
            gh_grid.addWidget(self.adm_gist_id, 1, 1)

            self.btn_auto_create_gist = QPushButton("✨ Auto-Create New GitHub Gist")
            self.btn_auto_create_gist.setObjectName("accentBtn")
            self.btn_auto_create_gist.clicked.connect(self.admin_auto_create_gist)
            gh_grid.addWidget(self.btn_auto_create_gist, 1, 2)

            gh_grid.addWidget(QLabel("Client Raw Control URL:"), 2, 0)
            self.adm_cloud_url = QLineEdit(
                self.saved_cfg.get("remote_control_url", DEFAULT_CLOUD_CONTROL_URL)
            )
            self.adm_cloud_url.setPlaceholderText("Auto-filled when you Create or Push to GitHub Gist")
            gh_grid.addWidget(self.adm_cloud_url, 2, 1, 1, 2)

            self.gh_status_lbl = QLabel("☁ Cloud Status: Ready")
            self.gh_status_lbl.setObjectName("badgeLabel")
            gh_grid.addWidget(QLabel("GitHub Release Repo (owner/repo):"), 3, 0)
            self.adm_release_repo = QLineEdit(self.saved_cfg.get("github_release_repo", ""))
            self.adm_release_repo.setPlaceholderText("example: username/SalmanBossVPN")
            gh_grid.addWidget(self.adm_release_repo, 3, 1, 1, 2)
            gh_grid.addWidget(self.gh_status_lbl, 4, 0, 1, 3)

            ctrl_vbox.addWidget(gh_box)

            # SECTION B: 1-Click Remote Kill-Switch (Directly updates GitHub Gist!)
            kill_box = QGroupBox("2. One-Click Global Kill-Switch (সরাসরি GitHub-এ কমান্ড চলে যাবে)")
            kill_v = QVBoxLayout(kill_box)

            cur_state = load_control_state()
            lock_msg_row = QHBoxLayout()
            lock_msg_row.addWidget(QLabel("Lock Message:"))
            self.adm_lock_msg_input = QLineEdit(
                cur_state.get(
                    "lock_message",
                    "⛔ অ্যাডমিন (Salman Boss) এই সফটওয়্যারের অ্যাক্সেস সাময়িকভাবে বন্ধ রেখেছেন। যোগাযোগ করুন: WhatsApp / Telegram।",
                )
            )
            lock_msg_row.addWidget(self.adm_lock_msg_input, 1)
            kill_v.addLayout(lock_msg_row)

            kill_l = QHBoxLayout()
            self.btn_allow_all = QPushButton("🟢 ALLOW ALL CLIENTS (সবার পিসিতে সফটওয়্যার চালু করুন)")
            self.btn_allow_all.setObjectName("accentBtn")
            self.btn_allow_all.setMinimumHeight(42)
            self.btn_allow_all.clicked.connect(lambda: self.admin_set_client_access(True))

            self.btn_block_all = QPushButton("🔴 TURN OFF ALL CLIENTS (সবার পিসিতে সফটওয়্যার বন্ধ করে দিন)")
            self.btn_block_all.setObjectName("dangerBtn")
            self.btn_block_all.setMinimumHeight(42)
            self.btn_block_all.clicked.connect(lambda: self.admin_set_client_access(False))

            kill_l.addWidget(self.btn_allow_all)
            kill_l.addWidget(self.btn_block_all)
            kill_v.addLayout(kill_l)
            ctrl_vbox.addWidget(kill_box)

            # SECTION C: 1-Click Push Update & Live Code to GitHub
            upd_box = QGroupBox("3. One-Click Push Update & Live Code to GitHub (সব পিসিতে অটো আপডেট যাবে)")
            upd_grid = QGridLayout(upd_box)

            upd_grid.addWidget(QLabel("New Version Number:"), 0, 0)
            self.adm_ver_input = QLineEdit(cur_state.get("latest_version", APP_VERSION))
            upd_grid.addWidget(self.adm_ver_input, 0, 1)

            upd_grid.addWidget(QLabel("Update Notification Text:"), 1, 0)
            self.adm_msg_input = QLineEdit(
                cur_state.get("update_message", "নতুন আপডেট এসেছে! নতুন ফিচার পেতে এখনই আপডেট করুন।")
            )
            upd_grid.addWidget(self.adm_msg_input, 1, 1)
            upd_grid.addWidget(
                QLabel("Version must match the EXE build; client PCs verify SHA-256 before updating."),
                4,
                0,
                1,
                3,
            )

            upd_grid.addWidget(QLabel("Portable Windows EXE:"), 2, 0)
            self.adm_update_file = QLineEdit()
            self.adm_update_file.setReadOnly(True)
            self.adm_update_file.setPlaceholderText("Select SalmanBossVPNManager.exe")
            upd_grid.addWidget(self.adm_update_file, 2, 1)
            self.btn_select_update_file = QPushButton("📂 Browse EXE")
            self.btn_select_update_file.clicked.connect(self.select_update_exe)
            upd_grid.addWidget(self.btn_select_update_file, 2, 2)

            self.btn_push_upd = QPushButton("🚀 UPLOAD EXE & NOTIFY CLIENTS")
            self.btn_push_upd.setObjectName("primaryBtn")
            self.btn_push_upd.setMinimumHeight(44)
            self.btn_push_upd.clicked.connect(self.admin_push_update_now)
            upd_grid.addWidget(self.btn_push_upd, 3, 0, 1, 3)

            ctrl_vbox.addWidget(upd_box)

            script_box = QGroupBox("4. Browse Python Script → Commit to GitHub Repository + Control JSON")
            script_grid = QGridLayout(script_box)
            script_grid.addWidget(QLabel("Branch:"), 0, 0)
            self.adm_repo_branch = QLineEdit(self.saved_cfg.get("github_repo_branch", "main"))
            self.adm_repo_branch.setPlaceholderText("main")
            script_grid.addWidget(self.adm_repo_branch, 0, 1, 1, 2)

            script_grid.addWidget(QLabel("Path inside repo:"), 1, 0)
            self.adm_repo_script_path = QLineEdit(self.saved_cfg.get("github_script_path", ""))
            self.adm_repo_script_path.setPlaceholderText("খালি রাখলে সিলেক্ট করা ফাইলের নামই রিপোতে যাবে")
            script_grid.addWidget(self.adm_repo_script_path, 1, 1, 1, 2)

            script_grid.addWidget(QLabel("Local Python file:"), 2, 0)
            self.adm_script_file = QLineEdit()
            self.adm_script_file.setReadOnly(True)
            self.adm_script_file.setPlaceholderText("Browse দিয়ে .py স্ক্রিপ্ট সিলেক্ট করুন")
            script_grid.addWidget(self.adm_script_file, 2, 1)
            self.btn_select_script = QPushButton("📂 Browse Script")
            self.btn_select_script.clicked.connect(self.select_python_script)
            script_grid.addWidget(self.btn_select_script, 2, 2)

            self.btn_push_script = QPushButton("⬆ UPLOAD SCRIPT & UPDATE CONTROL JSON")
            self.btn_push_script.setObjectName("primaryBtn")
            self.btn_push_script.setMinimumHeight(44)
            self.btn_push_script.clicked.connect(self.admin_publish_python_script)
            script_grid.addWidget(self.btn_push_script, 3, 0, 1, 3)

            script_note = QLabel(
                "Public রিপোতে কমিট হবে এবং salman_admin_control.json-এ নতুন ভার্সন, নোটিফিকেশন ও ডাউনলোড লিংক আপডেট হবে। "
                "ক্লায়েন্ট অ্যাপ ২০ সেকেন্ড পর পর চেক করে; ইউজার আপডেট চাইলে SHA-256 মিলিয়ে পুরনো ফাইল রিপ্লেস করে।"
            )
            script_note.setWordWrap(True)
            script_note.setObjectName("muted")
            script_grid.addWidget(script_note, 4, 0, 1, 3)
            ctrl_vbox.addWidget(script_box)

            # SECTION D: Change Admin PIN
            pin_change_row = QHBoxLayout()
            self.new_pin_input = QLineEdit()
            self.new_pin_input.setPlaceholderText("New Admin PIN...")
            btn_change_pin = QPushButton("🔑 Change Admin PIN")
            btn_change_pin.clicked.connect(self.admin_change_pin)
            pin_change_row.addWidget(QLabel("Change PIN:"))
            pin_change_row.addWidget(self.new_pin_input, 1)
            pin_change_row.addWidget(btn_change_pin)
            ctrl_vbox.addLayout(pin_change_row)

            config_backup_row = QHBoxLayout()
            backup_config_btn = QPushButton("📦 Backup Config")
            backup_config_btn.clicked.connect(self.backup_app_config)
            restore_config_btn = QPushButton("↩ Restore Config")
            restore_config_btn.clicked.connect(self.restore_app_config)
            config_backup_row.addWidget(backup_config_btn)
            config_backup_row.addWidget(restore_config_btn)
            ctrl_vbox.addLayout(config_backup_row)

            self.admin_lock_card.setVisible(not self.is_admin_session)
            self.admin_control_card.setVisible(self.is_admin_session)
            adm_layout.addWidget(self.admin_control_card)
            adm_layout.addStretch()

            admin_scroll.setWidget(admin_tab)
            if self.is_admin_session:
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
                ("Standard (1040×820)", 1040, 820),
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

            self.chk_run_on_startup = QCheckBox("▶ Run on Windows Startup (current user)")
            self.chk_run_on_startup.setChecked(self.is_run_on_startup_enabled())
            self.chk_run_on_startup.toggled.connect(self.toggle_run_on_startup)

            self.chk_always_top = QCheckBox("📌 Keep Window Always on Top (সব উইন্ডোর ওপরে রাখুন)")
            self.chk_always_top.toggled.connect(self.toggle_always_on_top)

            st_vbox.addWidget(self.chk_minimize_to_tray)
            st_vbox.addWidget(self.chk_desktop_notify)
            st_vbox.addWidget(self.chk_run_on_startup)
            st_vbox.addWidget(self.chk_always_top)

            studio_card = QFrame()
            studio_card.setObjectName("card3d")
            studio_layout = QVBoxLayout(studio_card)
            studio_title = QLabel("🎨 3D Theme & Sound Studio")
            studio_title.setObjectName("stepTitle")
            studio_layout.addWidget(studio_title)
            studio_row = QHBoxLayout()
            studio_row.addWidget(QLabel("Color theme:"))
            self.studio_theme_combo = QComboBox()
            self.studio_theme_combo.addItems(list(THEMES.keys()))
            self.studio_theme_combo.setCurrentText(self.current_theme_name)
            self.studio_theme_combo.currentTextChanged.connect(self.apply_theme)
            studio_row.addWidget(self.studio_theme_combo, 1)
            studio_row.addWidget(self.chk_sound_alert)
            studio_layout.addLayout(studio_row)
            st_vbox.addWidget(studio_card)

            btn_row_st = QHBoxLayout()
            repair_btn = QPushButton("🔧 Auto-Configure VPN Paths & Permissions")
            repair_btn.setObjectName("accentBtn")
            repair_btn.clicked.connect(self.run_background_repair)

            reset_network_btn = QPushButton("🌐 Fix Network / Reset Proxy")
            reset_network_btn.clicked.connect(self.reset_user_proxy_and_dns)

            quit_full_btn = QPushButton("🚪 Quit App Completely")
            quit_full_btn.setObjectName("dangerBtn")
            quit_full_btn.clicked.connect(self.quit_application_completely)

            btn_row_st.addWidget(repair_btn)
            btn_row_st.addWidget(reset_network_btn)
            btn_row_st.addWidget(quit_full_btn)
            st_vbox.addLayout(btn_row_st)

            st_vbox.addStretch()
            st_layout.addWidget(st_card)
            self.tabs.addTab(settings_tab, "⚙ Settings & Tray")

            page_actions = QHBoxLayout()
            save_page_btn = QPushButton("💾 Save Page")
            save_page_btn.clicked.connect(self.save_current_page)
            self.version_save_btn = QPushButton("⬆ Auto-Update Version & Save")
            self.version_save_btn.setEnabled(self.is_master_admin_unlocked)
            self.version_save_btn.clicked.connect(self.auto_update_version_and_save)
            smart_reset_btn = QPushButton("↺ Smart Reset")
            smart_reset_btn.clicked.connect(self.smart_reset)
            page_actions.addWidget(save_page_btn)
            page_actions.addWidget(self.version_save_btn)
            page_actions.addWidget(smart_reset_btn)
            root_vbox.addLayout(page_actions)

            # ==================== FOOTER: TELEGRAM + WHATSAPP ====================
            footer = QHBoxLayout()
            credit = QLabel("POWERED BY SALMAN BOSS  •  macOS 3D + GITHUB CLOUD")
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

            self._init_system_tray()

            # Exact 1-Second Session Timer
            self.session_timer = QTimer(self)
            self.session_timer.setInterval(1000)
            self.session_timer.timeout.connect(self._on_session_second)

            self.proxy_ui_timer = QTimer(self)
            self.proxy_ui_timer.setInterval(1000)
            self.proxy_ui_timer.timeout.connect(self.update_proxy_session_display)

            # Passive Background Provider Scanner
            self.poll_timer = QTimer(self)
            self.poll_timer.timeout.connect(self.scan_providers)
            self.poll_timer.start(12000)

            # Live GitHub Remote Control & Update Watcher (Every 20s)
            self.remote_watch_timer = QTimer(self)
            self.remote_watch_timer.timeout.connect(lambda: self.check_remote_control_and_updates(manual=False))
            self.remote_watch_timer.start(20000)

            self.apply_interface_language()
            self.apply_theme(self.current_theme_name)
            self.load_locations_for_provider()
            self.scan_providers()
            QTimer.singleShot(1500, lambda: self.check_remote_control_and_updates(manual=False))

        # -------------------------------------------------------------------
        # DIRECT GITHUB API ADMIN PANEL FUNCTIONS
        # -------------------------------------------------------------------
        def apply_interface_language(self):
            translations = UI_TRANSLATIONS.get(self.interface_language, UI_TRANSLATIONS["both"])
            for widget in self.findChildren(QWidget):
                if hasattr(widget, "text") and hasattr(widget, "setText"):
                    original = widget.text()
                    if original in translations:
                        widget.setText(translations[original])
            for index in range(self.tabs.count()):
                original = self.tabs.tabText(index)
                if original in translations:
                    self.tabs.setTabText(index, translations[original])

        def unlock_admin_panel(self):
            entered = self.pin_input.text().strip()
            if entered == self.admin_pin:
                self.is_master_admin_unlocked = True
                self.version_save_btn.setEnabled(True)
                self.chk_master_pc.setChecked(True)
                save_settings({"master_admin_pc": True})
                self.admin_control_card.setVisible(True)
                self.sub_lbl.setText(f"macOS 3D + GITHUB CLOUD  •  v{APP_VERSION}  •  MASTER ADMIN PC")
                self._apply_lock_ui(False, "")
                QMessageBox.information(
                    self,
                    "Master Admin Unlocked",
                    "স্বাগতম Salman Boss! মেইন অ্যাডমিন প্যানেল আনলক হয়েছে।",
                )
            else:
                QMessageBox.warning(self, "Wrong PIN", "ভুল পিন কোড! সঠিক অ্যাডমিন পিন দিন।")

        def toggle_master_pc_mode(self, checked: bool):
            self.is_master_admin_unlocked = checked
            self.version_save_btn.setEnabled(checked)
            save_settings({"master_admin_pc": checked})
            self.sub_lbl.setText(
                f"macOS 3D + GITHUB CLOUD  •  v{APP_VERSION}  •  "
                f"{'MASTER ADMIN PC' if checked else 'CLIENT MODE'}"
            )

        def _save_admin_github_fields(self) -> tuple[str, str]:
            token = self.adm_gh_token.text().strip()
            gist_id_or_url = self.adm_gist_id.text().strip() or self.adm_cloud_url.text().strip()
            cloud_url = self.adm_cloud_url.text().strip()
            save_settings(
                {
                    "github_token": token,
                    "github_gist_id": extract_gist_id(gist_id_or_url),
                    "remote_control_url": cloud_url,
                    "github_release_repo": self.adm_release_repo.text().strip(),
                    "github_repo_branch": self.adm_repo_branch.text().strip() or "main",
                    "github_script_path": self.adm_repo_script_path.text().strip(),
                }
            )
            return token, gist_id_or_url

        def _trigger_github_sync(self, state: dict, include_live_script: bool):
            token, gist_ref = self._save_admin_github_fields()
            save_control_state_locally(state)
            if not token:
                self.gh_status_lbl.setText("⚠ Saved Locally (Add GitHub Token to push online automatically)")
                QMessageBox.information(
                    self,
                    "Saved Locally",
                    "কমান্ড লোকাল ফাইলে সেভ হয়েছে।\n"
                    "ইন্টারনেটের মাধ্যমে অন্য পিসিতে অটো পাঠাতে 1 নম্বর বক্সে আপনার GitHub Token দিন।",
                )
                return

            self.gh_status_lbl.setText("⏳ Pushing command directly to GitHub Gist API...")
            self.btn_allow_all.setEnabled(False)
            self.btn_block_all.setEnabled(False)
            self.btn_push_upd.setEnabled(False)
            self.btn_push_script.setEnabled(False)
            self.btn_auto_create_gist.setEnabled(False)

            self.gh_worker = GitHubSyncWorker(token, gist_ref, state, include_live_script)
            self.gh_worker.finished_sync.connect(self._on_github_sync_finished)
            self.gh_worker.start()

        def _on_github_sync_finished(self, ok: bool, msg: str, gist_id: str, raw_url: str):
            self.btn_allow_all.setEnabled(True)
            self.btn_block_all.setEnabled(True)
            self.btn_push_upd.setEnabled(True)
            self.btn_push_script.setEnabled(True)
            self.btn_auto_create_gist.setEnabled(True)

            self.log.append(f"[GITHUB CLOUD] {msg}")
            if ok:
                if gist_id:
                    self.adm_gist_id.setText(gist_id)
                if raw_url:
                    self.adm_cloud_url.setText(raw_url)
                    # Also embed DEFAULT_CLOUD_CONTROL_URL into local script so any future copies have it pre-configured!
                    try:
                        p = Path(__file__).resolve()
                        txt = p.read_text(encoding="utf-8")
                        updated_txt = re.sub(
                            r'^DEFAULT_CLOUD_CONTROL_URL\s*=\s*".*"',
                            f'DEFAULT_CLOUD_CONTROL_URL = "{raw_url}"',
                            txt,
                            count=1,
                            flags=re.MULTILINE,
                        )
                        if updated_txt != txt:
                            p.write_text(updated_txt, encoding="utf-8")
                    except Exception:
                        pass
                self.gh_status_lbl.setText(f"✅ Synced Live with GitHub Gist ({gist_id})")
                self.send_notification("☁ GitHub Cloud Synced", msg, "success")
                script_url = getattr(self, "_published_script_url", "")
                self._published_script_url = ""
                extra = f"\n\nScript download:\n{script_url}" if script_url else ""
                QMessageBox.information(
                    self,
                    "GitHub Cloud Sync Success",
                    f"{msg}\n\nClient Raw URL:\n{raw_url}{extra}",
                )
            else:
                self.gh_status_lbl.setText(f"❌ Sync Failed: {msg[:80]}")
                self.send_notification("❌ GitHub Sync Failed", msg, "failed")
                QMessageBox.warning(self, "GitHub API Error", msg)

        def admin_auto_create_gist(self):
            token = self.adm_gh_token.text().strip()
            if not token:
                QMessageBox.warning(
                    self,
                    "GitHub Token Required",
                    "প্রথমে 'GitHub Token (PAT)' বক্সে আপনার টোকেন পেস্ট করুন।\n"
                    "টোকেন না থাকলে ডানপাশের '🌐 Get Token' বাটনে ক্লিক করে ১টি টোকেন তৈরি করে নিন।",
                )
                return
            state = load_control_state()
            state["latest_version"] = self.adm_ver_input.text().strip() or APP_VERSION
            state["update_message"] = self.adm_msg_input.text().strip()
            state["lock_message"] = self.adm_lock_msg_input.text().strip()
            # Clear Gist ID so it creates a brand-new Gist via POST
            self.adm_gist_id.clear()
            self._trigger_github_sync(state, include_live_script=True)

        def admin_set_client_access(self, enabled: bool):
            state = load_control_state()
            state["app_enabled"] = enabled
            state["lock_message"] = self.adm_lock_msg_input.text().strip()
            status_str = "চালু (ALLOW ALL)" if enabled else "বন্ধ (TURN OFF ALL)"
            self.log.append(f"[ADMIN COMMAND] ক্লায়েন্ট অ্যাক্সেস {status_str} কমান্ড পাঠানো হচ্ছে...")
            self._trigger_github_sync(state, include_live_script=False)

        def admin_push_update_now(self):
            new_ver = self.adm_ver_input.text().strip() or APP_VERSION
            token = self.adm_gh_token.text().strip()
            repository = self.adm_release_repo.text().strip()
            file_path = self.adm_update_file.text().strip()
            if not token:
                QMessageBox.warning(self, "GitHub Token Required", "GitHub token দিন।")
                return
            if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
                QMessageBox.warning(self, "GitHub Repository", "Public repository এভাবে দিন: owner/repository")
                return
            if not file_path or not Path(file_path).is_file():
                QMessageBox.warning(self, "Portable EXE Required", "প্রথমে Browse EXE দিয়ে portable EXE নির্বাচন করুন।")
                return

            self._save_admin_github_fields()
            self.btn_push_upd.setEnabled(False)
            self.btn_select_update_file.setEnabled(False)
            self.gh_status_lbl.setText("⏳ Uploading EXE to a draft GitHub Release...")
            self.release_worker = GitHubReleaseUploadWorker(
                token,
                repository,
                new_ver,
                file_path,
                self.adm_msg_input.text().strip(),
            )
            self.release_worker.progress.connect(self.gh_status_lbl.setText)
            self.release_worker.completed.connect(self._on_release_upload_finished)
            self.release_worker.failed.connect(self._on_release_upload_failed)
            self.release_worker.start()

        def select_update_exe(self):
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Select portable Salman Boss VPN Manager EXE",
                "",
                "Windows executable (*.exe)",
            )
            if path:
                self.adm_update_file.setText(path)

        def select_python_script(self):
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Select Python script to publish",
                str(Path(__file__).resolve().parent),
                "Python script (*.py *.pyw)",
            )
            if path:
                self.adm_script_file.setText(path)
                if not self.adm_repo_script_path.text().strip():
                    self.adm_repo_script_path.setText(Path(path).name)

        def admin_publish_python_script(self):
            version = self.adm_ver_input.text().strip() or APP_VERSION
            token = self.adm_gh_token.text().strip()
            repository = self.adm_release_repo.text().strip()
            local_file = self.adm_script_file.text().strip()
            if not token:
                QMessageBox.warning(self, "GitHub Token Required", "GitHub token দিন। Contents: write অনুমতি থাকতে হবে।")
                return
            if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
                QMessageBox.warning(self, "GitHub Repository", "Public repository এভাবে দিন: owner/repository")
                return
            if not local_file or not Path(local_file).is_file():
                QMessageBox.warning(self, "Python Script Required", "প্রথমে Browse Script দিয়ে একটি .py ফাইল সিলেক্ট করুন।")
                return

            self._save_admin_github_fields()
            state = load_control_state()
            state["lock_message"] = self.adm_lock_msg_input.text().strip()
            state["latest_version"] = version
            state["update_message"] = self.adm_msg_input.text().strip()
            self.btn_push_script.setEnabled(False)
            self.btn_select_script.setEnabled(False)
            self.gh_status_lbl.setText("⏳ Committing Python file to GitHub...")
            self.script_worker = GitHubScriptCommitWorker(
                token,
                repository,
                self.adm_repo_branch.text().strip() or "main",
                local_file,
                self.adm_repo_script_path.text().strip(),
                version,
                self.adm_msg_input.text().strip(),
                state,
            )
            self.script_worker.progress.connect(self.gh_status_lbl.setText)
            self.script_worker.completed.connect(self._on_script_commit_finished)
            self.script_worker.failed.connect(self._on_script_commit_failed)
            self.script_worker.start()

        def _on_script_commit_finished(self, result: dict):
            self.btn_push_script.setEnabled(True)
            self.btn_select_script.setEnabled(True)
            state = result.get("state") or {}
            download_url = str(result.get("download_url", ""))
            control_url = str(result.get("control_url", ""))
            self.adm_repo_branch.setText(str(result.get("branch") or self.adm_repo_branch.text()))
            self.log.append(
                f"[GITHUB REPO] {result.get('message', '')} SHA-256: {result.get('sha256', '')}"
            )
            gist_id = extract_gist_id(self.adm_gist_id.text().strip())
            self._published_script_url = download_url
            if gist_id:
                self.gh_status_lbl.setText("⏳ Repository committed. Syncing the same control JSON to Gist...")
                self._trigger_github_sync(state, include_live_script=False)
                return
            if control_url:
                self.adm_cloud_url.setText(control_url)
                save_settings({"remote_control_url": control_url})
            self.gh_status_lbl.setText("✅ Script and control JSON committed")
            self.send_notification("⬆ GitHub Script Published", download_url, "success")
            QMessageBox.information(
                self,
                "GitHub Script Published",
                f"{result.get('message', '')}\n\n"
                f"Download link:\n{download_url}\n\n"
                f"Control JSON:\n{control_url}\n\n"
                f"SHA-256:\n{result.get('sha256', '')}",
            )

        def _on_script_commit_failed(self, message: str):
            self.btn_push_script.setEnabled(True)
            self.btn_select_script.setEnabled(True)
            self.gh_status_lbl.setText(f"❌ Script commit failed: {message[:100]}")
            self.log.append(f"[GITHUB REPO] {message}")
            QMessageBox.warning(self, "GitHub Script Upload Failed", message)

        def _on_release_upload_finished(self, asset_url: str, sha256: str):
            self.btn_push_upd.setEnabled(True)
            self.btn_select_update_file.setEnabled(True)
            self.log.append(f"[GITHUB RELEASE] Uploaded portable EXE. SHA-256: {sha256}")

            state = load_control_state()
            state["latest_version"] = self.adm_ver_input.text().strip() or APP_VERSION
            state["update_message"] = self.adm_msg_input.text().strip()
            state["lock_message"] = self.adm_lock_msg_input.text().strip()
            state["update_script_url"] = asset_url
            state["update_sha256"] = sha256
            self._trigger_github_sync(state, include_live_script=False)

        def _on_release_upload_failed(self, message: str):
            self.btn_push_upd.setEnabled(True)
            self.btn_select_update_file.setEnabled(True)
            self.gh_status_lbl.setText(f"❌ Release upload failed: {message[:100]}")
            self.log.append(f"[GITHUB RELEASE] {message}")
            QMessageBox.warning(self, "GitHub Release Upload Failed", message)

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
            update_sha256 = str(state.get("update_sha256", "")).strip().lower()
            update_file_name = str(state.get("update_file_name", "")).strip()
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
                    f"GitHub থেকে যাচাইকৃত আপডেট ডাউনলোড করে পুরনো ফাইল রিপ্লেস করতে চান?\n"
                    f"SHA-256: {update_sha256 or 'missing'}",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if ans == QMessageBox.Yes:
                    self.perform_auto_update(latest_ver, script_url, update_sha256, update_file_name)
            elif manual:
                QMessageBox.information(
                    self,
                    "Up to Date",
                    f"আপনি সর্বশেষ ভার্সন (v{APP_VERSION}) ব্যবহার করছেন।",
                )

        def perform_auto_update(
            self,
            target_version: str,
            script_url: str,
            expected_sha256: str,
            file_name: str = "",
        ):
            try:
                if not script_url.startswith("https://"):
                    raise ValueError("Update URL must use HTTPS.")
                if not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
                    raise ValueError("Update checksum is missing or invalid; ask the administrator to publish the release again.")

                file_url = script_url.split("?", 1)[0].lower()
                max_size = 500 * 1024 * 1024 if file_url.endswith(".exe") else 8 * 1024 * 1024
                sep = "&" if "?" in script_url else "?"
                download_url = f"{script_url}{sep}_t={random.randint(100000, 999999)}"
                req = urllib.request.Request(
                    download_url,
                    headers={"User-Agent": "SalmanBossVPNUpdater", "Cache-Control": "no-cache"},
                )
                with urllib.request.urlopen(req, timeout=60) as response:
                    final_host = (urllib.parse.urlparse(response.geturl()).hostname or "").lower()
                    if not (
                        final_host == "github.com"
                        or final_host.endswith(".github.com")
                        or final_host == "githubusercontent.com"
                        or final_host.endswith(".githubusercontent.com")
                    ):
                        raise ValueError("Update download left the trusted GitHub domains.")
                    new_bytes = response.read(max_size + 1)
                if len(new_bytes) > max_size:
                    raise ValueError("The downloaded update is larger than the allowed size.")
                actual_sha256 = hashlib.sha256(new_bytes).hexdigest()
                if actual_sha256 != expected_sha256:
                    raise ValueError("Update checksum verification failed; the downloaded file was rejected.")
                if not new_bytes.startswith(b"MZ"):
                    self._install_python_update(new_bytes, file_name)
                    return

                new_exe = new_bytes
                if getattr(sys, "frozen", False):
                    target_path = Path(sys.executable).resolve()
                    staged_path = target_path.with_name(target_path.stem + ".update.exe")
                    staged_path.write_bytes(new_exe)
                    quote_ps = lambda value: "'" + str(value).replace("'", "''") + "'"
                    helper_script = f"""
$ErrorActionPreference = 'Stop'
$processIdToWait = {os.getpid()}
$staged = {quote_ps(staged_path)}
$target = {quote_ps(target_path)}
$backup = $target + '.old'
while (Get-Process -Id $processIdToWait -ErrorAction SilentlyContinue) {{ Start-Sleep -Milliseconds 500 }}
try {{
    Move-Item -LiteralPath $target -Destination $backup -Force
    Move-Item -LiteralPath $staged -Destination $target -Force
    Start-Process -FilePath $target
    Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
}} catch {{
    if ((Test-Path $backup) -and -not (Test-Path $target)) {{ Move-Item -LiteralPath $backup -Destination $target }}
    throw
}}
"""
                    encoded_helper = base64.b64encode(helper_script.encode("utf-16le")).decode("ascii")
                    powershell = locate(["powershell.exe", "powershell"])
                    if not powershell:
                        staged_path.unlink(missing_ok=True)
                        raise RuntimeError("PowerShell is required to replace the running portable EXE.")
                    subprocess.Popen(
                        [powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded_helper],
                        creationflags=CREATE_NO_WINDOW,
                    )
                    self.force_quit = True
                    self.tray_icon.hide()
                    QApplication.quit()
                else:
                    update_folder = Path.home() / "Downloads" / "SalmanBossVPN"
                    update_folder.mkdir(parents=True, exist_ok=True)
                    staged_path = update_folder / f"SalmanBossVPNManager-{target_version}.exe"
                    staged_path.write_bytes(new_exe)
                    subprocess.Popen([str(staged_path)], creationflags=CREATE_NO_WINDOW)
                    QMessageBox.information(
                        self,
                        "Update Started",
                        "Verified portable EXE downloaded and launched. Close the source-script window and use the new EXE.",
                    )
            except Exception as exc:
                QMessageBox.warning(self, "Auto-Update Error", f"আপডেট ডাউনলোডে সমস্যা হয়েছে: {exc}")

        def _install_python_update(self, payload: bytes, file_name: str):
            try:
                text = payload.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise ValueError("Downloaded update is not a UTF-8 Python file.") from exc
            current = Path(__file__).resolve()
            is_this_app = 'APP = "Salman Boss VPN Manager"' in text
            if is_this_app:
                if getattr(sys, "frozen", False):
                    raise ValueError("এই পিসিতে EXE চলছে। স্ক্রিপ্টের বদলে portable EXE রিলিজ পাবলিশ করুন।")
                self._schedule_script_replace(current, payload)
                return

            safe_name = Path(file_name).name
            if not re.fullmatch(r"[A-Za-z0-9._ -]{1,180}\.pyw?", safe_name):
                raise ValueError("Update file name is not a safe Python file name.")
            target = (current.parent / safe_name).resolve()
            if target.parent != current.parent or target == current:
                raise ValueError("Refusing to replace the running application with a different Python file.")
            target.write_bytes(payload)
            QMessageBox.information(
                self,
                "File Updated",
                f"{safe_name} ডাউনলোড হয়ে একই ফোল্ডারে পুরনো ফাইল রিপ্লেস করেছে।",
            )

        def _schedule_script_replace(self, target: Path, payload: bytes):
            staged = target.with_name(target.name + ".new")
            staged.write_bytes(payload)
            quote_ps = lambda value: "'" + str(value).replace("'", "''") + "'"
            helper_script = f"""
$ErrorActionPreference = 'Stop'
$processIdToWait = {os.getpid()}
$staged = {quote_ps(staged)}
$target = {quote_ps(target)}
$python = {quote_ps(sys.executable)}
while (Get-Process -Id $processIdToWait -ErrorAction SilentlyContinue) {{ Start-Sleep -Milliseconds 400 }}
Copy-Item -LiteralPath $staged -Destination $target -Force
Remove-Item -LiteralPath $staged -Force -ErrorAction SilentlyContinue
Start-Process -FilePath $python -ArgumentList @($target)
"""
            encoded_helper = base64.b64encode(helper_script.encode("utf-16le")).decode("ascii")
            powershell = locate(["powershell.exe", "powershell"])
            if not powershell:
                staged.unlink(missing_ok=True)
                raise RuntimeError("PowerShell is required to replace the running Python file.")
            subprocess.Popen(
                [powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded_helper],
                creationflags=CREATE_NO_WINDOW,
            )
            self.force_quit = True
            self.tray_icon.hide()
            QApplication.quit()

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
            if hasattr(self, "studio_theme_combo") and self.studio_theme_combo.currentText() != theme_name:
                self.studio_theme_combo.setCurrentText(theme_name)
            if hasattr(self, "quick_theme") and self.quick_theme.currentText() != theme_name:
                self.quick_theme.setCurrentText(theme_name)

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
                    color: #0b0f19;
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
                    color: #0b0f19;
                    border: none;
                    font-weight: 800;
                }}
                QPushButton#whatsappBtn {{
                    background: #16a34a;
                    color: #0b0f19;
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

        def refresh_favorite_servers(self):
            while self.favorite_buttons_layout.count():
                item = self.favorite_buttons_layout.takeAt(0)
                widget = item.widget()
                if widget:
                    widget.deleteLater()
            for index, favorite in enumerate(self.favorite_servers):
                if not isinstance(favorite, dict):
                    continue
                label = str(favorite.get("label", "Favorite server"))
                button = QPushButton(label)
                button.setObjectName("primaryBtn")
                button.clicked.connect(lambda checked=False, item=dict(favorite): self.connect_favorite(item))
                remove = QPushButton("×")
                remove.setToolTip(f"Remove {label}")
                remove.clicked.connect(lambda checked=False, item_index=index: self.remove_favorite(item_index))
                self.favorite_buttons_layout.addWidget(button)
                self.favorite_buttons_layout.addWidget(remove)

        def add_current_favorite(self):
            provider_key = str(self.provider_combo.currentData() or "")
            provider = self.current_provider()
            city_label = self.selected_city_label or "Automatic"
            favorite = {
                "provider_key": provider_key,
                "provider_label": provider.label,
                "country": self.selected_country,
                "city_label": city_label,
                "location": self.selected_city_label if isinstance(provider, ProtonVPN) else self.selected_region_slug,
                "label": f"{provider.label} • {city_label}",
            }
            if any(
                item.get("provider_key") == provider_key and item.get("location") == favorite["location"]
                for item in self.favorite_servers
                if isinstance(item, dict)
            ):
                return
            self.favorite_servers.append(favorite)
            save_settings({"favorite_servers": self.favorite_servers})
            self.refresh_favorite_servers()

        def remove_favorite(self, index: int):
            if 0 <= index < len(self.favorite_servers):
                self.favorite_servers.pop(index)
                save_settings({"favorite_servers": self.favorite_servers})
                self.refresh_favorite_servers()

        def connect_favorite(self, favorite: dict):
            provider_key = str(favorite.get("provider_key", ""))
            provider_index = self.provider_combo.findData(provider_key)
            if provider_index < 0:
                QMessageBox.warning(self, "Favorite server", "The saved VPN provider is no longer available.")
                return
            self.provider_combo.setCurrentIndex(provider_index)
            self.selected_country = str(favorite.get("country", ""))
            self.selected_city_label = str(favorite.get("city_label", "Automatic"))
            self.selected_region_slug = str(favorite.get("location", "Automatic"))
            if self.selected_country:
                self.country_folder_btn.setText(f"{COUNTRY_FLAGS.get(self.selected_country, '🌐')}  {self.selected_country}")
                self.city_folder_btn.setText(f"🏙  {self.selected_country} • {self.selected_city_label}")
            else:
                self.country_folder_btn.setText("📂  1. Select Country")
                self.city_folder_btn.setText(f"🏙  2. City: {self.selected_city_label}")
            self.start_connect_flow()

        def on_provider_changed(self):
            self.duration_card.setVisible(False)
            self.mode_card.setVisible(False)
            self.load_locations_for_provider()

        def load_locations_for_provider(self):
            prov = self.current_provider()
            is_proton = isinstance(prov, ProtonVPN)
            raw = prov.locations() if not isinstance(prov, (CustomVPN, ProtonVPN)) else []
            self.country_tree = (
                {country: list(cities) for country, cities in DEFAULT_COUNTRY_CITIES.items()}
                if is_proton
                else build_country_city_tree(raw)
            )
            self.selected_country = ""
            self.selected_city_label = "Automatic"
            self.selected_region_slug = "Automatic"
            self.country_folder_btn.setEnabled(True)
            self.city_folder_btn.setEnabled(True)
            self.country_folder_btn.setText("📂  1. Select Country")
            self.city_folder_btn.setText("🏙  2. City: Automatic")
            if is_proton:
                self.log.append("[Proton VPN] City selections are searched in Proton's own location picker.")
            else:
                self.log.append(f"[{prov.label}] Loaded {len(self.country_tree)} countries.")

        def open_country_finder(self):
            if not self.country_tree:
                self.country_tree = build_country_city_tree([])
            dlg = MacCountryFinderDialog(self, self.country_tree)
            if dlg.exec() == QDialog.Accepted and dlg.selected_country:
                self.selected_country = dlg.selected_country
                flag = COUNTRY_FLAGS.get(self.selected_country, "🌐")
                self.country_folder_btn.setText(f"{flag}  {self.selected_country}")
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
            self.country_folder_btn.setText(f"{flag}  {self.selected_country}")
            self.city_folder_btn.setText(f"🏙  {self.selected_country} • {city_label}")
            self.dur_title.setText(
                f"⏱ Step 3: {self.selected_country} ({city_label}) কত মিনিটের জন্য কানেক্ট করতে চান?"
            )
            self.duration_card.setVisible(True)
            self.log.append(f"Selected: {self.selected_country} ➔ {city_label} ({region_slug}).")

        def select_duration(self, minutes: int):
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
            prov = self.current_provider()
            self.session_timer.stop()
            target_loc = self.selected_city_label if isinstance(prov, ProtonVPN) else self.selected_region_slug or "Automatic"
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

            if isinstance(prov, ProtonVPN):
                if action == "test":
                    self.orb.set_state("idle", "APP READY", "Status unavailable", spinning=False)
                    self._update_tray_appearance("idle", "Proton VPN status unavailable")
                elif action in ("connect", "disconnect"):
                    pending = ok and "attempting to connect" in message.lower()
                    if action == "connect" and ok and not pending:
                        self._start_usage_session("VPN", prov.label, self.selected_city_label or "Automatic")
                        self.orb.set_state("success", "CONNECTED", "Proton VPN", spinning=False)
                        self._update_tray_appearance("success", "Proton VPN connected")
                        if self.timer_enabled and self.configured_minutes > 0:
                            self.remaining_seconds = self.configured_minutes * 60
                            self.session_timer.start(1000)
                            self.timer_badge.setText(f"⏱ Set: {self.configured_minutes} Min")
                        else:
                            self.timer_badge.setText("⏱ Timer: ♾ Unlimited")
                    elif pending:
                        self.orb.set_state("connecting", "CONNECTING", "Proton VPN", spinning=True)
                        self._update_tray_appearance("connecting", "Proton VPN connecting")
                    elif action == "disconnect" and ok:
                        self._finish_usage_session("VPN", "Disconnected")
                        self.session_timer.stop()
                        self.orb.set_state("idle", "DISCONNECTED", "Standby", spinning=False)
                        self._update_tray_appearance("idle", "Proton VPN disconnected")
                        self.timer_badge.setText("⏱ Timer: Stopped")
                    else:
                        self.orb.set_state("failed", "FAILED", "Check Proton", spinning=False)
                        self._update_tray_appearance("failed", "Proton VPN action failed")
                else:
                    return
                self.send_notification("Proton VPN", message, "info")
                if not ok and self.isVisible():
                    QMessageBox.warning(self, "Proton VPN", message)
                return

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
                    self._start_usage_session("VPN", prov.label, f"{country_disp} / {city_disp}")
                    self.orb.set_state("success", "CONNECTED", city_disp[:18], spinning=False)
                    self._update_tray_appearance("success", f"Connected: {country_disp} ({city_disp})")
                    if self.selected_country:
                        self.city_folder_btn.setText(f"🟢 {self.selected_country} • {city_disp} (Connected)")

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
                    self._finish_usage_session("VPN", "Disconnected")
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
            if not self.timer_enabled or self.configured_minutes <= 0 or self.is_reconnecting_cycle:
                self.session_timer.stop()
                return

            if self.remaining_seconds > 0:
                self.remaining_seconds -= 1
                m, s = divmod(self.remaining_seconds, 60)
                self.timer_badge.setText(f"⏱ Left: {m:02d}:{s:02d}")
                return

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

        def is_run_on_startup_enabled(self) -> bool:
            try:
                import winreg

                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Run",
                    0,
                    winreg.KEY_READ,
                ) as key:
                    winreg.QueryValueEx(key, "SalmanBossVPNManager")
                return True
            except (FileNotFoundError, OSError):
                return False

        def toggle_run_on_startup(self, enabled: bool):
            try:
                import winreg

                run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, run_key) as key:
                    if enabled:
                        if getattr(sys, "frozen", False):
                            command = f'"{sys.executable}"'
                        else:
                            command = f'"{sys.executable}" "{Path(sys.argv[0]).resolve()}"'
                        winreg.SetValueEx(key, "SalmanBossVPNManager", 0, winreg.REG_SZ, command)
                    else:
                        try:
                            winreg.DeleteValue(key, "SalmanBossVPNManager")
                        except FileNotFoundError:
                            pass
                save_settings({"run_on_startup": enabled})
            except OSError as exc:
                QMessageBox.warning(self, "Startup setting", str(exc))
                self.chk_run_on_startup.blockSignals(True)
                self.chk_run_on_startup.setChecked(not enabled)
                self.chk_run_on_startup.blockSignals(False)

        def reset_user_proxy_and_dns(self):
            answer = QMessageBox.question(
                self,
                "Reset proxy and DNS cache",
                "This clears the current user's Windows proxy settings and flushes DNS. "
                "VPN/TAP adapters will not be changed. Continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            try:
                import winreg

                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
                    winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
                    for value_name in ("ProxyServer", "ProxyOverride"):
                        try:
                            winreg.DeleteValue(key, value_name)
                        except FileNotFoundError:
                            pass
                result = subprocess.run(
                    ["ipconfig", "/flushdns"],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    creationflags=CREATE_NO_WINDOW,
                )
                if result.returncode:
                    raise RuntimeError((result.stderr or result.stdout).strip() or "DNS cache flush failed.")
                self.log.append("Current-user proxy settings cleared and DNS cache flushed.")
                QMessageBox.information(self, "Network reset", "Proxy settings cleared and DNS cache flushed.")
            except Exception as exc:
                QMessageBox.warning(self, "Network reset failed", str(exc))

        def backup_app_config(self):
            target, _ = QFileDialog.getSaveFileName(
                self,
                "Backup Salman Boss VPN Manager settings",
                str(Path.home() / "SalmanBossVPN-settings.json"),
                "JSON files (*.json)",
            )
            if not target:
                return
            try:
                payload = CONFIG.read_text(encoding="utf-8") if CONFIG.exists() else "{}"
                json.loads(payload)
                Path(target).write_text(payload, encoding="utf-8")
                QMessageBox.information(self, "Config backup", "Settings backup created.")
            except Exception as exc:
                QMessageBox.warning(self, "Config backup failed", str(exc))

        def save_current_page(self):
            save_settings(
                {
                    "theme": self.current_theme_name,
                    "favorite_servers": self.favorite_servers,
                    "custom_installers": self.saved_cfg.get("custom_installers", []),
                    "last_active_tab": self.tabs.currentIndex(),
                }
            )
            QMessageBox.information(self, "Save Page", "Current app settings saved on this PC.")

        def auto_update_version_and_save(self):
            global APP_VERSION
            if not self.is_master_admin_unlocked:
                QMessageBox.warning(self, "Admin only", "Unlock the administrator session first.")
                return
            match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", APP_VERSION)
            if not match:
                QMessageBox.warning(self, "Version", "The current version is not in major.minor.patch format.")
                return
            next_version = f"{match.group(1)}.{match.group(2)}.{int(match.group(3)) + 1}"
            if getattr(sys, "frozen", False):
                source_path = application_directory() / f"Salman_Boss_VPN_Manager_v{APP_VERSION}.py"
            else:
                source_path = Path(__file__).resolve()
            if not source_path.is_file():
                QMessageBox.warning(self, "Version", "Editable Python source was not found beside the app.")
                return
            target_path = source_path.with_name(f"Salman_Boss_VPN_Manager_v{next_version}.py")
            if target_path.exists():
                QMessageBox.warning(self, "Version", f"The staged source already exists:\n{target_path}")
                return
            if QMessageBox.question(
                self,
                "Update version",
                f"Create a new source file for v{next_version}? The current source and published control JSON will remain unchanged until you build and publish the release.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            ) != QMessageBox.Yes:
                return
            try:
                source_text = source_path.read_text(encoding="utf-8")
                updated_source, count = re.subn(
                    r'^APP_VERSION\s*=\s*"[^"]*"',
                    f'APP_VERSION = "{next_version}"',
                    source_text,
                    count=1,
                    flags=re.MULTILINE,
                )
                if count != 1:
                    raise ValueError("APP_VERSION could not be updated in the source.")
                target_path.write_text(updated_source, encoding="utf-8")
                QMessageBox.information(
                    self,
                    "Version source staged",
                    f"Created:\n{target_path}\n\nBuild the portable EXE and publish it from the Admin Panel to notify clients.",
                )
            except Exception as exc:
                QMessageBox.warning(self, "Version update failed", str(exc))

        def smart_reset(self):
            if QMessageBox.question(
                self,
                "Smart Reset",
                "Reset the current location and session timer? Saved favorites, settings, app version, and source will remain unchanged.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            ) != QMessageBox.Yes:
                return
            self.session_timer.stop()
            self.timer_enabled = False
            self.configured_minutes = 0
            self.remaining_seconds = 0
            self.is_reconnecting_cycle = False
            self.selected_country = ""
            self.selected_city_label = "Automatic"
            self.selected_region_slug = "Automatic"
            self.country_folder_btn.setText("📂  1. Select Country")
            self.city_folder_btn.setText("🏙  2. City: Automatic")
            self.duration_card.setVisible(False)
            self.mode_card.setVisible(False)
            self.timer_badge.setText("⏱ Timer: ♾ Unlimited")
            self.orb.set_state("idle", "READY", "Standby", spinning=False)
            self.log.append("Smart Reset: temporary location and timer state cleared; VPN was not disconnected.")

        def restore_app_config(self):
            source, _ = QFileDialog.getOpenFileName(
                self,
                "Restore Salman Boss VPN Manager settings",
                str(Path.home()),
                "JSON files (*.json)",
            )
            if not source:
                return
            if QMessageBox.question(
                self,
                "Restore config",
                "This replaces the app's saved settings. Continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            ) != QMessageBox.Yes:
                return
            try:
                restored = json.loads(Path(source).read_text(encoding="utf-8"))
                if not isinstance(restored, dict):
                    raise ValueError("Config file must contain a JSON object.")
                CONFIG.parent.mkdir(parents=True, exist_ok=True)
                CONFIG.write_text(json.dumps(restored, indent=2, ensure_ascii=False), encoding="utf-8")
                self.saved_cfg = restored
                QMessageBox.information(self, "Config restore", "Settings restored. Restart the app to apply all values.")
            except Exception as exc:
                QMessageBox.warning(self, "Config restore failed", str(exc))

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
            bar, status, cancel, button, open_folder, launch_button = self.download_rows[name]
            bar.setValue(0)
            status.setText("Connecting to official server…")
            cancel.setEnabled(True)
            button.setEnabled(False)
            worker = DownloadWorker(name, url, self.download_folder, self.download_allowed_domains.get(name, ()))
            worker.progress.connect(lambda pct, msg, n=name: self.update_download_progress(n, pct, msg))
            worker.completed.connect(self.download_completed)
            worker.failed.connect(self.download_failed)
            self.download_workers[name] = worker
            worker.start()

        def update_download_progress(self, name, percent, message):
            bar, status, cancel, button, open_folder, launch_button = self.download_rows[name]
            if percent > 0:
                bar.setValue(percent)
            status.setText(message)

        def cancel_download(self, name):
            worker = self.download_workers.get(name)
            if worker and worker.isRunning():
                worker.cancel()
                self.download_rows[name][1].setText("Cancelling…")

        def download_completed(self, name, path):
            bar, status, cancel, button, open_folder, launch_button = self.download_rows[name]
            bar.setValue(100)
            status.setText("Download complete")
            cancel.setEnabled(False)
            button.setEnabled(True)
            self.download_history.addItem(f"{name}  —  {path}")
            self.log.append(f"Downloaded {name}: {path}")
            self.send_notification("⬇ Download Complete", f"{name} ইনস্টলার ডাউনলোড সম্পন্ন হয়েছে।", "success")
            try:
                os.startfile(path)
                status.setText("Downloaded; installer launched")
            except Exception as exc:
                status.setText(f"Downloaded; could not launch: {exc}")
                QMessageBox.warning(self, "Installer", str(exc))

        def download_failed(self, name, message):
            bar, status, cancel, button, open_folder, launch_button = self.download_rows[name]
            cancel.setEnabled(False)
            button.setEnabled(True)
            status.setText(message)
            self.log.append(f"{name} download: {message}")
            if message != "Download cancelled.":
                self.send_notification(f"❌ {name} Download Failed", message, "failed")
                QMessageBox.warning(self, f"{name} download failed", message)

        def _add_download_card(self, name: str, url: str, allowed_domains=()):
            card = QFrame()
            card.setObjectName("card3d")
            card.setMinimumHeight(250)
            layout = QVBoxLayout(card)
            layout.setContentsMargins(16, 14, 16, 14)
            layout.setSpacing(7)

            title = QLabel(f"🛡 {name} Installer")
            title.setStyleSheet("font-weight:800;font-size:15px;")
            title.setMinimumHeight(24)

            provider_key = {
                "PIA": "pia",
                "ExpressVPN": "expressvpn",
                "Proton VPN": "proton",
                "NordVPN": "nord",
            }.get(name)
            provider = PROVIDERS.get(provider_key) if provider_key else None
            executable = provider.detect() if provider else None
            badge = QLabel("● Installed" if executable else "○ Not detected")
            badge.setObjectName("muted")

            launch_button = QPushButton("▶ Launch VPN")
            launch_button.setEnabled(bool(executable))
            launch_button.clicked.connect(
                lambda checked=False, path=executable, label=name: self.launch_installed_vpn(label, path)
            )

            download_button = QPushButton(f"⬇  Download {name}")
            download_button.setObjectName("primaryBtn")
            download_button.setMinimumHeight(38)
            download_button.clicked.connect(lambda checked=False, n=name, u=url: self.start_download(n, u))

            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setMinimumHeight(20)

            status = QLabel("Ready to download")
            status.setObjectName("muted")
            status.setMinimumHeight(24)
            status.setWordWrap(True)

            cancel = QPushButton("✖ Cancel Download")
            cancel.setMinimumHeight(30)
            cancel.setEnabled(False)
            cancel.clicked.connect(lambda checked=False, n=name: self.cancel_download(n))

            open_folder = QPushButton("📂 Open Folder")
            open_folder.clicked.connect(self.open_download_folder)

            layout.addWidget(title)
            layout.addWidget(badge)
            layout.addWidget(launch_button)
            layout.addWidget(download_button)
            layout.addWidget(bar)
            layout.addWidget(status)
            layout.addWidget(cancel)
            layout.addWidget(open_folder)

            index = self.download_card_count
            self.download_grid.addWidget(card, index // 2, index % 2)
            self.download_card_count += 1
            self.download_rows[name] = (bar, status, cancel, download_button, open_folder, launch_button)
            self.download_allowed_domains[name] = tuple(allowed_domains)

        def add_custom_installer(self):
            name, accepted = QInputDialog.getText(self, "Custom VPN Installer", "VPN name:")
            if not accepted or not name.strip():
                return
            url, accepted = QInputDialog.getText(self, "Custom VPN Installer", "Direct HTTPS .exe or .msi URL:")
            if not accepted or not url.strip():
                return
            parsed = urllib.parse.urlparse(url.strip())
            installer_name = name.strip()
            if parsed.scheme != "https" or not parsed.hostname or not parsed.path.lower().endswith((".exe", ".msi")):
                QMessageBox.warning(self, "Invalid installer URL", "Use a direct HTTPS URL ending in .exe or .msi.")
                return
            if installer_name in self.download_rows:
                QMessageBox.warning(self, "Duplicate name", "That installer name is already listed.")
                return
            installers = self.saved_cfg.get("custom_installers", [])
            installers.append({"name": installer_name, "url": url.strip()})
            self.saved_cfg["custom_installers"] = installers
            save_settings({"custom_installers": installers})
            self._add_download_card(installer_name, url.strip(), (parsed.hostname.lower(),))

        def launch_installed_vpn(self, name: str, executable: Optional[str]):
            if not executable:
                return
            try:
                os.startfile(executable)
            except Exception as exc:
                QMessageBox.warning(self, f"Launch {name}", str(exc))

        def open_download_folder(self):
            self.download_folder.mkdir(parents=True, exist_ok=True)
            os.startfile(str(self.download_folder))

        def refresh_proxy_profiles(self, selected_row: int = -1):
            self.proxy_profile_list.clear()
            for profile in self.proxy_profiles:
                text = f"{profile['provider']} | {profile['protocol']} | {profile['host']}:{profile['port']}"
                self.proxy_profile_list.addItem(text)
            if 0 <= selected_row < self.proxy_profile_list.count():
                self.proxy_profile_list.setCurrentRow(selected_row)
            if self.previous_user_proxy:
                self.proxy_status_label.setText("Proxy status: a saved previous setting can be restored")

        def parse_proxy_paste(self):
            parts = self.proxy_paste_input.text().strip().split(":", 3)
            if len(parts) != 4:
                QMessageBox.warning(self, "Proxy format", "Paste Host:Port:User:Pass.")
                return
            host, port, username, password = parts
            if not port.isdigit() or not 1 <= int(port) <= 65535:
                QMessageBox.warning(self, "Proxy format", "Port must be between 1 and 65535.")
                return
            self.proxy_host_input.setText(host.strip())
            self.proxy_port_input.setText(port)
            self.proxy_user_input.setText(username)
            self.proxy_password_input.setText(password)

        def save_proxy_profile(self):
            provider = self.proxy_provider_input.text().strip()
            host = self.proxy_host_input.text().strip()
            port_text = self.proxy_port_input.text().strip()
            protocol = self.proxy_protocol_input.currentText()
            if not provider or not host or not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
                QMessageBox.warning(self, "Proxy profile", "Enter a provider, host/IP, and valid port.")
                return
            profile = {"provider": provider, "protocol": protocol, "host": host, "port": int(port_text)}
            existing = next(
                (
                    index for index, item in enumerate(self.proxy_profiles)
                    if item.get("provider") == provider and item.get("host") == host and item.get("port") == int(port_text)
                ),
                -1,
            )
            if existing >= 0:
                self.proxy_profiles[existing] = profile
            else:
                self.proxy_profiles.append(profile)
                existing = len(self.proxy_profiles) - 1
            save_settings({"proxy_profiles": self.proxy_profiles})
            self.refresh_proxy_profiles(existing)
            if self.proxy_user_input.text() or self.proxy_password_input.text():
                self.proxy_status_label.setText("Profile saved without credentials; Windows proxy auth is not configured.")

        def load_selected_proxy_profile(self, row: int):
            if not 0 <= row < len(self.proxy_profiles):
                return
            profile = self.proxy_profiles[row]
            self.proxy_provider_input.setText(str(profile.get("provider", "")))
            self.proxy_protocol_input.setCurrentText(str(profile.get("protocol", "HTTP")))
            self.proxy_host_input.setText(str(profile.get("host", "")))
            self.proxy_port_input.setText(str(profile.get("port", "")))
            self.proxy_user_input.clear()
            self.proxy_password_input.clear()

        def delete_proxy_profile(self):
            row = self.proxy_profile_list.currentRow()
            if not 0 <= row < len(self.proxy_profiles):
                return
            self.proxy_profiles.pop(row)
            save_settings({"proxy_profiles": self.proxy_profiles})
            self.refresh_proxy_profiles()

        def _read_user_proxy_settings(self) -> dict:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            result = {"enabled": 0, "server": "", "override": "", "auto_config_url": ""}
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
                for registry_name, setting_name, default in (
                    ("ProxyEnable", "enabled", 0),
                    ("ProxyServer", "server", ""),
                    ("ProxyOverride", "override", ""),
                    ("AutoConfigURL", "auto_config_url", ""),
                ):
                    try:
                        result[setting_name] = winreg.QueryValueEx(key, registry_name)[0]
                    except FileNotFoundError:
                        result[setting_name] = default
            return result

        def _notify_user_proxy_changed(self):
            internet = ctypes.windll.Wininet
            internet.InternetSetOptionW(None, 39, None, 0)
            internet.InternetSetOptionW(None, 37, None, 0)

        def apply_selected_proxy(self):
            row = self.proxy_profile_list.currentRow()
            if not 0 <= row < len(self.proxy_profiles):
                QMessageBox.warning(self, "Proxy profile", "Save or select a proxy profile first.")
                return
            profile = self.proxy_profiles[row]
            if QMessageBox.question(
                self,
                "Apply current-user proxy",
                "This changes this Windows user's Internet Settings only. It does not configure WinHTTP, VPN/TAP adapters, or other users. Continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            ) != QMessageBox.Yes:
                return
            try:
                import winreg

                if self.proxy_user_input.text() or self.proxy_password_input.text():
                    QMessageBox.information(
                        self,
                        "Proxy credentials",
                        "Windows Internet Settings do not apply these credentials. They will not be saved or sent.",
                    )
                if not self.previous_user_proxy:
                    self.previous_user_proxy = self._read_user_proxy_settings()
                    save_settings({"proxy_previous_user_settings": self.previous_user_proxy})
                scheme = {"HTTP": "http", "HTTPS": "https", "SOCKS5": "socks"}[profile["protocol"]]
                proxy_server = f"{scheme}={profile['host']}:{profile['port']}"
                key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                    winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
                    winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, proxy_server)
                    winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, "<local>")
                    try:
                        winreg.DeleteValue(key, "AutoConfigURL")
                    except FileNotFoundError:
                        pass
                self._notify_user_proxy_changed()
                self.proxy_status_label.setText(f"Proxy status: active for this user ({profile['provider']})")
                self.proxy_data_label.setText("Data used: not measured")
                self.proxy_session_started = time.monotonic()
                self.proxy_ui_timer.start()
                try:
                    started = time.monotonic()
                    with socket.create_connection((profile["host"], int(profile["port"])), timeout=1.5):
                        ping_ms = (time.monotonic() - started) * 1000
                    self.proxy_ping_label.setText(f"TCP connect: {ping_ms:.0f} ms")
                except OSError:
                    self.proxy_ping_label.setText("TCP connect: unavailable")
                self._start_usage_session("Proxy", profile["provider"], f"{profile['protocol']} {profile['host']}:{profile['port']}")
            except Exception as exc:
                QMessageBox.warning(self, "Proxy apply failed", str(exc))

        def restore_user_proxy(self):
            if QMessageBox.question(
                self,
                "Restore previous proxy",
                "Restore this Windows user's proxy settings saved before the app changed them?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            ) != QMessageBox.Yes:
                return
            try:
                import winreg

                previous = self.previous_user_proxy
                if not previous:
                    raise RuntimeError("No previous proxy settings were saved by this app.")
                key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                    winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, int(previous.get("enabled", 0)))
                    for registry_name, setting_name in (("ProxyServer", "server"), ("ProxyOverride", "override"), ("AutoConfigURL", "auto_config_url")):
                        value = previous.get(setting_name, "")
                        if value:
                            winreg.SetValueEx(key, registry_name, 0, winreg.REG_SZ, str(value))
                        else:
                            try:
                                winreg.DeleteValue(key, registry_name)
                            except FileNotFoundError:
                                pass
                self._notify_user_proxy_changed()
                self.previous_user_proxy = None
                save_settings({"proxy_previous_user_settings": None})
                self.proxy_status_label.setText("Proxy status: previous user settings restored")
                self.proxy_ping_label.setText("Ping: not measured")
                self.proxy_session_started = None
                self.proxy_ui_timer.stop()
                self.proxy_timer_label.setText("Session: 00:00:00")
                self._finish_usage_session("Proxy", "Restored previous user settings")
            except Exception as exc:
                QMessageBox.warning(self, "Proxy restore failed", str(exc))

        def _save_usage_history(self):
            HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            HISTORY_FILE.write_text(json.dumps(self.usage_history[-1000:], indent=2, ensure_ascii=False), encoding="utf-8")
            self.refresh_usage_history()

        def update_proxy_session_display(self):
            if self.proxy_session_started is None:
                return
            seconds = int(time.monotonic() - self.proxy_session_started)
            self.proxy_timer_label.setText(f"Session: {seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}")

        def _start_usage_session(self, kind: str, provider: str, target: str):
            if kind in self.active_history_sessions:
                return
            started = datetime.now(timezone.utc)
            entry = {
                "type": kind,
                "provider": provider,
                "target": target,
                "started_at": started.isoformat(timespec="seconds"),
                "ended_at": "",
                "duration_seconds": 0,
                "data": "Not measured",
            }
            self.usage_history.append(entry)
            self.active_history_sessions[kind] = entry
            self._save_usage_history()

        def _finish_usage_session(self, kind: str, target: str = ""):
            entry = self.active_history_sessions.pop(kind, None)
            if not entry:
                return
            ended = datetime.now(timezone.utc)
            started = datetime.fromisoformat(entry["started_at"])
            entry["ended_at"] = ended.isoformat(timespec="seconds")
            entry["duration_seconds"] = max(0, int((ended - started).total_seconds()))
            if target:
                entry["target"] = target
            self._save_usage_history()

        def refresh_usage_history(self):
            if not hasattr(self, "history_table"):
                return
            entries = self.usage_history[-1000:]
            self.history_table.setRowCount(len(entries))
            for row, entry in enumerate(reversed(entries)):
                seconds = int(entry.get("duration_seconds", 0))
                duration = "Active" if not entry.get("ended_at") else f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
                values = (
                    f"{entry.get('type', '')} / {entry.get('provider', '')}",
                    str(entry.get("target", "")),
                    str(entry.get("started_at", "")),
                    duration,
                    str(entry.get("data", "Not measured")),
                )
                for column, value in enumerate(values):
                    self.history_table.setItem(row, column, QTableWidgetItem(value))

        def clear_usage_history(self):
            if QMessageBox.question(
                self,
                "Clear usage history",
                "Delete this app's local connection history?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            ) != QMessageBox.Yes:
                return
            self.usage_history = []
            self.active_history_sessions = {}
            HISTORY_FILE.unlink(missing_ok=True)
            self.refresh_usage_history()

        def export_usage_history(self):
            target, _ = QFileDialog.getSaveFileName(
                self,
                "Export usage history",
                str(Path.home() / "SalmanBossVPN-usage.csv"),
                "CSV files (*.csv)",
            )
            if not target:
                return
            try:
                with open(target, "w", newline="", encoding="utf-8-sig") as output:
                    writer = csv.writer(output)
                    writer.writerow(("Type", "Provider", "Target", "Started", "Ended", "Duration seconds", "Data"))
                    for entry in self.usage_history:
                        writer.writerow((entry.get("type", ""), entry.get("provider", ""), entry.get("target", ""), entry.get("started_at", ""), entry.get("ended_at", ""), entry.get("duration_seconds", 0), entry.get("data", "Not measured")))
            except Exception as exc:
                QMessageBox.warning(self, "Export failed", str(exc))

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    setup_dialog = LaunchSetupDialog()
    if setup_dialog.exec() != QDialog.Accepted:
        return 0

    language, user_role, entered_pin = setup_dialog.selections
    save_settings({"interface_language": language})
    if user_role == "admin":
        expected_pin = str(load_settings().get("admin_pin", DEFAULT_ADMIN_PIN))
        if entered_pin != expected_pin:
            QMessageBox.warning(None, "Wrong PIN", "The administrator PIN is incorrect.")
            return 2
        save_settings({"master_admin_pc": True})
    else:
        save_settings({"master_admin_pc": False})

    win = Window(user_role, language)
    win.show()
    return app.exec()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != "gui":
        sys.exit(cli())
    ensure_background_environment()
    hide_console_window()
    sys.exit(launch_gui())
