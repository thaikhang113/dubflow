"""Khoi phuc ba probe bi xoa trong smoke report cua app.py.

Khi doi chieu lint xoa comment `# noqa: F401`, nguoi ta xoa luon dong import ben
trong `try:` de lai `try: pass`. Ket qua: `except` khong bao gio chay, nen
`playwright_importable`, `multimedia_importable` va `new_modules_importable` in
ra `True` mai mai — ke ca khi ban dong khong chuyen duoc QtMultimedia. Do chinh
la cay cau CI dung chan san pham loi.

Chay:  python qa/restore_probes.py
"""
import io

PATH = "autodub_gui/app.py"

BLOCKS = [
    (
        "    try:\n        pass\n    except Exception:\n"
        "        checks[\"playwright_importable\"] = False\n",
        "    try:\n"
        "        # Dung ten module qua importlib: xoa dong nay la xoa luon phep thu.\n"
        "        __import__(\"playwright.sync_api\")\n"
        "    except Exception:\n"
        "        checks[\"playwright_importable\"] = False\n",
    ),
    (
        "    try:\n        pass\n    except Exception as e:\n"
        "        checks[\"multimedia_importable\"] = False\n"
        "        checks[\"multimedia_error\"] = str(e)\n",
        "    try:\n"
        "        __import__(\"PySide6.QtMultimedia\")\n"
        "        __import__(\"PySide6.QtMultimediaWidgets\")\n"
        "    except Exception as e:\n"
        "        checks[\"multimedia_importable\"] = False\n"
        "        checks[\"multimedia_error\"] = str(e)\n",
    ),
    (
        "    try:\n        pass\n    except Exception as e:\n"
        "        checks[\"new_modules_importable\"] = False\n"
        "        checks[\"new_modules_error\"] = str(e)\n",
        "    try:\n"
        "        for module in (\n"
        "            \"autodub.media.timing\",\n"
        "            \"autodub.providers.openai_compatible\",\n"
        "            \"autodub.speech.align\",\n"
        "            \"autodub.speech.tts.voices\",\n"
        "            \"autodub.text.ass_karaoke\",\n"
        "            \"autodub.text.subtitles\",\n"
        "        ):\n"
        "            __import__(module)\n"
        "    except Exception as e:\n"
        "        checks[\"new_modules_importable\"] = False\n"
        "        checks[\"new_modules_error\"] = str(e)\n",
    ),
]

c = io.open(PATH, encoding="utf-8").read()
for old, new in BLOCKS:
    hits = c.count(old)
    assert hits == 1, (hits, old[:60])
    c = c.replace(old, new, 1)
io.open(PATH, "w", encoding="utf-8", newline="").write(c)
print("restored 3 smoke probes")
