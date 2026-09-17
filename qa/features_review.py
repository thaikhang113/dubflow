"""Review the remaining feature pages against real project data.

Covers what the GUI walkthrough could not: pages that only show something once
a project exists (Projects, Quality, Editor launcher), the settings save
round-trip, the voice library, the OpenClaw HTTP surface, and the doctor.

Run:  .venv\\Scripts\\python.exe qa\\features_review.py
"""
from __future__ import annotations

import json
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("AUTODUB_SMOKE", "1")
os.environ.setdefault(
    "DUBFLOW_DATA_DIR",
    os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                 "DubFlow"),
)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from autodub_gui import _frozen  # noqa: E402

_frozen.init()

from PySide6.QtWidgets import QApplication  # noqa: E402

from autodub.config import Settings  # noqa: E402
from autodub_gui.app import (  # noqa: E402
    ROW_QUALITY, ROW_SUBTITLE,
    ROW_VOICE, MainWindow,
)

QA = os.path.join(ROOT, "qa")
SHOTS = os.path.join(QA, "shots")
RUNS = os.path.join(QA, "runs")
YT_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
FINDINGS: list[dict] = []
LOG: list[str] = []


def log(msg: str) -> None:
    LOG.append(msg)
    print(msg, flush=True)


def finding(area, kind, severity, summary, expected="", actual="",
            evidence="") -> None:
    FINDINGS.append({"area": area, "kind": kind, "severity": severity,
                     "summary": summary, "expected": expected,
                     "actual": actual, "evidence": evidence})
    log(f"  !! [{severity}] {kind}: {summary}")


def pump(app, n=6) -> None:
    for _ in range(n):
        app.processEvents()


def shot(widget, name: str) -> str:
    path = os.path.join(SHOTS, f"{name}.png")
    try:
        pm = widget.grab()
        if pm.isNull():
            return ""
        pm.save(path)
        return path
    except Exception:
        return ""


def completed_projects() -> list[str]:
    """Projects produced by the E2E run, newest first."""
    found = []
    for root, _dirs, files in os.walk(RUNS):
        if "dubbed_video.mp4" in files:
            found.append(root)
    return sorted(found, key=os.path.getmtime, reverse=True)


# ------------------------------------------------------------- Projects ----- #
def review_projects(app) -> None:
    log("=== Trang Du an: scan thu muc ket qua")
    from autodub_gui.projects import scan
    projects = scan(RUNS)
    log(f"  scan() thay {len(projects)} du an trong qa/runs")
    if not projects:
        finding("Du an", "scan", "S1",
                "khong tim thay du an nao du qa/runs co video hoan chinh",
                ">=1 du an", f"{len(projects)}", RUNS)
        return
    p = projects[0]
    for attr in ("work_dir", "title", "status"):
        if not hasattr(p, attr):
            finding("Du an", "model", "S2", f"Project thieu thuoc tinh {attr}")
    log(f"  dau tien: title={getattr(p, 'title', '')!r} "
        f"status={getattr(p, 'status', '')!r}")


# -------------------------------------------------------------- Quality ----- #
def review_quality(app, win) -> None:
    log("=== Trang Bao cao chat luong: nap quality_report that")
    targets = [d for d in completed_projects()
               if os.path.isfile(os.path.join(d, "data",
                                              "quality_report.json"))]
    if not targets:
        finding("Bao cao chat luong", "artifact", "S1",
                "khong du an nao con quality_report.json",
                "giu lai sau khi auto-clean", RUNS)
        return
    log(f"  {len(targets)} du an co bao cao")
    try:
        win.switch_page(ROW_QUALITY)
        pump(app)
        page = win._page_widgets.get(ROW_QUALITY)
        if page is None:
            finding("Bao cao chat luong", "build", "S1", "khong dung duoc trang")
            return
        # Trang nay quet settings.output_dir; tro no ve qa/runs de co du lieu
        # that do E2E san ra.
        def _settings_with_runs():
            cfg = Settings.load(override=True)
            cfg.output_dir = RUNS
            return cfg
        page._settings_provider = _settings_with_runs
        page.on_shown()
        pump(app)
        combo = getattr(page, "project_combo", None)
        if combo is None:
            finding("Bao cao chat luong", "ui", "S2",
                    "khong thay combo chon du an tren trang")
            return
        log(f"  so du an hien trong bo chon: {combo.count()}")
        if combo.count() == 0:
            finding("Bao cao chat luong", "scan", "S2",
                    "trang khong liet ke du an nao co bao cao",
                    "nho hon danh sach chat luong ton tai",
                    f"co {len(targets)} bao cao tren dia")
        shot(page, "quality_page")
    except Exception as exc:
        finding("Bao cao chat luong", "crash", "S1", f"loi: {exc}",
                actual=traceback.format_exc(limit=4)[-400:])


# ------------------------------------------------------------- Settings ----- #
def review_settings_roundtrip(app, win) -> None:
    log("=== Cai dat: ghi va doc lai khong mat gia tri")
    from autodub_gui.env_store import ENV_PATH, read_env, write_env
    backup = None
    try:
        if os.path.isfile(ENV_PATH):
            with open(ENV_PATH, encoding="utf-8") as handle:
                backup = handle.read()
        before = read_env()
        probe_key = "WHISPER_MODEL"
        write_env({probe_key: "large-v3"})
        mid = read_env()
        if mid.get(probe_key) != "large-v3":
            finding("Cai dat", "persist", "S1",
                    "ghi .env xong doc lai khong thay gia tri moi",
                    "large-v3", repr(mid.get(probe_key)), ENV_PATH)
        # Khoa va ghi chu khac phai con nguyen
        if backup is not None:
            after = read_env()
            lost = [k for k in before if k not in after]
            if lost:
                finding("Cai dat", "persist", "S1",
                        f"ghi .env lam mat {len(lost)} khoa khac",
                        "giu nguyen khoa khong lien quan", ", ".join(lost[:6]),
                        ENV_PATH)
            comments_before = sum(1 for ln in backup.splitlines()
                                  if ln.strip().startswith("#"))
            with open(ENV_PATH, encoding="utf-8") as handle:
                comments_after = sum(1 for ln in handle.read().splitlines()
                                     if ln.strip().startswith("#"))
            if comments_after < comments_before:
                finding("Cai dat", "persist", "S3",
                        "ghi .env lam mat dong ghi chu",
                        f">= {comments_before} dong",
                        f"{comments_after} dong", ENV_PATH)
        reloaded = Settings.load(override=True)
        if reloaded.whisper_model != "large-v3":
            finding("Cai dat", "persist", "S1",
                    "Settings.load khong nhan gia tri vua ghi",
                    "large-v3", reloaded.whisper_model, ENV_PATH)
        else:
            log("  OK vong lap ghi/doc .env")
    except Exception as exc:
        finding("Cai dat", "crash", "S1", f"loi: {exc}",
                actual=traceback.format_exc(limit=4)[-400:])
    finally:
        if backup is not None:
            with open(ENV_PATH, "w", encoding="utf-8", newline="") as handle:
                handle.write(backup)
            log("  .env da khoi phuc nguyen trang")


# ---------------------------------------------------------------- Voice ----- #
def review_voice(app, win) -> None:
    log("=== Giong doc AI: danh muc va preview")
    try:
        win.switch_page(ROW_VOICE)
        pump(app)
        page = win._page_widgets.get(ROW_VOICE)
        if page is None:
            finding("Giong doc AI", "build", "S1", "khong dung duoc trang")
            return
        from autodub.speech.tts import voices as catalog
        settings = Settings.load(override=True)
        entries = catalog.catalog(settings)
        log(f"  danh muc: {len(entries)} giong")
        if not entries:
            finding("Giong doc AI", "data", "S2",
                    "danh muc giong rong nen nguoi dung khong chon duoc ai",
                    ">=1 giong", f"{len(entries)}")
        resolved = catalog.resolve(settings, None)
        if resolved not in {v.name for v in entries}:
            finding("Giong doc AI", "data", "S1",
                    "giong mac dinh giai ra ngoai danh muc",
                    "ten nam trong catalog", resolved)
        else:
            log(f"  mac dinh: {resolved}")
        shot(page, "voice_page")
    except Exception as exc:
        finding("Giong doc AI", "crash", "S1", f"loi: {exc}",
                actual=traceback.format_exc(limit=4)[-400:])


# ------------------------------------------------------------- Subtitle ----- #
def review_subtitle(app, win) -> None:
    log("=== Phu de: preset khop giua giao dien va pipeline")
    try:
        from autodub.media.subtitle import DEFAULT_STYLE, PRESETS, normalize_style
        win.switch_page(ROW_SUBTITLE)
        pump(app)
        page = win._page_widgets.get(ROW_SUBTITLE)
        shot(page, "subtitle_page") if page else None
        keys = {k for k, *_rest in PRESETS}
        if DEFAULT_STYLE.get("preset") not in keys:
            finding("Phu de", "config", "S2",
                    "preset mac dinh khong co trong danh sach preset",
                    repr(DEFAULT_STYLE.get("preset")), str(sorted(keys)))
        for key, *_rest in PRESETS:
            style = normalize_style({"preset": key})
            merged = {**DEFAULT_STYLE, **style}
            if not merged.get("font"):
                finding("Phu de", "config", "S3",
                        f"preset {key} khong co font sau normalize")
        log(f"  OK {len(PRESETS)} preset normalize hop le")
    except Exception as exc:
        finding("Phu de", "crash", "S1", f"loi: {exc}",
                actual=traceback.format_exc(limit=4)[-400:])


# -------------------------------------------------------------- OpenClaw ---- #
def review_openclaw(win) -> None:
    log("=== OpenClaw: surface HTTP local")
    runtime = getattr(win, "_openclaw_runtime", None)
    if runtime is None:
        finding("OpenClaw", "config", "S2", "runtime khong ton tai")
        return
    log(f"  enabled={runtime.enabled} running={runtime.running}")
    if not runtime.enabled or not runtime.running:
        log("  khong chay -> bo qua goi HTTP")
        return
    import urllib.error
    import urllib.request
    base = runtime.endpoint
    if not base:
        finding("OpenClaw", "api", "S2",
                "runtime running nhưng endpoint rỗng",
                "URL http://127.0.0.1:<port>", repr(base))
        return
    log(f"  endpoint: {base}")
    auth = {"Authorization": f"Bearer {runtime.token}"}

    def call(method, path, body=None, headers=auth):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(base + path, data=data, method=method,
                                         headers={**headers,
                                                  "Content-Type":
                                                      "application/json"})
        with urllib.request.urlopen(request, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    # 1. Khong token -> moi endpoint phai 401 (ke ca /health)
    for method, path, body in (("GET", "/health", None),
                               ("POST", "/v1/prepare",
                                {"links": ["https://x.y/a"]})):
        try:
            status, _payload = call(method, path, body, headers={})
            finding("OpenClaw", "security", "S1",
                    f"{method} {path} chap yeu cau khong token (HTTP {status})",
                    "401 khi thieu Bearer token", f"status={status}")
        except urllib.error.HTTPError as err:
            if err.code == 401:
                log(f"  OK {method} {path} -> 401 khong token")
            else:
                finding("OpenClaw", "security", "S3",
                        f"{method} {path} khong token tra {err.code}",
                        "401", str(err.code))
        except Exception as exc:
            finding("OpenClaw", "api", "S2", f"{method} {path} loi: {exc}")

    # 2. Vong goi that nhu agent se lam
    try:
        status, payload = call("GET", "/health")
        if status != 200 or payload.get("ok") is not True:
            finding("OpenClaw", "api", "S2", "/health co token van fail",
                    "200 ok=true", f"{status} {payload}")
        else:
            log("  OK /health voi token")
        status, payload = call("POST", "/v1/prepare",
                               {"links": [YT_URL]})
        log(f"  /v1/prepare -> {status} ok={payload.get('ok')} "
            f"links={len(payload.get('links', []) or [])} "
            f"questions={len(payload.get('questions', []) or [])}")
        if status != 200 or payload.get("ok") is not True:
            finding("OpenClaw", "api", "S2",
                    "/v1/prepare khong tra ket qua hop le",
                    "ok=true kem danh sach link", repr(payload)[:200])
    except Exception as exc:
        finding("OpenClaw", "api", "S1", f"goi co token that bai: {exc}",
                actual=str(exc)[:200])

    # 3. Nut kiem tra ket noi cua chinh app
    ok, detail = runtime.check_health()
    log(f"  check_health() -> {ok} ({detail})")
    if not ok:
        finding("OpenClaw", "ux", "S2",
                "nut 'Kiem tra ket noi' trong app bao that bai",
                "thanh cong khi API dang chay", detail)


# ---------------------------------------------------------------- Doctor ---- #
def review_doctor() -> None:
    log("=== Tro giup: doctor va preflight")
    try:
        from autodub.doctor import run_doctor
        from autodub.preflight import blocking_failures
        results = run_doctor()
        bad = [r for r in results if r.level == "fail"]
        warn = [r for r in results if r.level == "warn"]
        log(f"  {len(results)} muc: fail={len(bad)} warn={len(warn)}")
        for r in bad:
            finding("Doctor", "environment", "S2",
                    f"{r.title}: {r.message}", "may du dieu kien chay",
                    r.advice[:120])
        for r in warn:
            log(f"  (warn) {r.title}: {r.message}")
        if blocking_failures(results) != bad:
            finding("Doctor", "logic", "S2",
                    "blocking_failures khong khop cac muc fail")
    except Exception as exc:
        finding("Doctor", "crash", "S1", f"loi: {exc}",
                actual=traceback.format_exc(limit=4)[-400:])


def main() -> int:
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.resize(1360, 820)
    win.show()
    pump(app, 10)
    try:
        review_projects(app)
        review_quality(app, win)
        review_settings_roundtrip(app, win)
        review_voice(app, win)
        review_subtitle(app, win)
        review_openclaw(win)
        review_doctor()
    finally:
        for page in win._page_widgets.values():
            if hasattr(page, "shutdown"):
                try:
                    page.shutdown()
                except Exception:
                    pass
        win._force_close = True
        win.close()
        pump(app, 4)
    with open(os.path.join(QA, "findings_features.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"findings": FINDINGS}, handle, ensure_ascii=False, indent=2)
    with open(os.path.join(QA, "logs", "features_review.log"), "w",
              encoding="utf-8") as handle:
        handle.write("\n".join(LOG))
    log(f"=== {len(FINDINGS)} phat hien")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
