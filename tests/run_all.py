"""Bütün testlər bir əmrlə. API açarı və internet lazım deyil — OpenAI / ElevenLabs saxta cavablarla əvəz olunur.

    python tests/run_all.py
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("OPENAI_API_KEY", "test")

from backend import studio  # noqa: E402


def fixtures(d: Path) -> tuple[Path, Path]:
    ff = studio.ffmpeg_bin()
    beep, video = d / "beep.mp3", d / "talk.mp4"
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=220:d=1.2", str(beep)], check=True)
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=gray:s=320x240:d=12",
                    "-f", "lavfi", "-i", "sine=f=180:d=12", "-c:v", "libx264", "-c:a", "aac", "-shortest",
                    str(video)], check=True)
    return beep, video


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        beep, video = fixtures(tmp)
        env = {**os.environ, "DATA_DIR": str(tmp / "data"), "N8N_EVENT_WEBHOOK": ""}
        suites = [
            ("Backend: seqmentlər, LCEL, API, lüğət", ["tests/test_backend.py"]),
            ("Panel: bütün Streamlit səhifələri", ["tests/test_ui.py"]),
            ("Video studiya: altyazılı və dublyajlı MP4", ["tests/test_studio.py", str(beep), str(video)]),
            ("Dialoq: danışanlar, səs tonu, səs paylanması", ["tests/test_dialog.py", str(beep)]),
        ]
        failed = 0
        for name, args in suites:
            t = time.time()
            r = subprocess.run([sys.executable, *args], cwd=ROOT, env=env, capture_output=True, text=True)
            ok = r.returncode == 0
            failed += not ok
            print(f"{'✓' if ok else '✗'} {name}  ({time.time() - t:.1f} san)")
            if not ok:
                print("   " + "\n   ".join((r.stdout + r.stderr).strip().splitlines()[-12:]))
        print(f"\n{len(suites) - failed}/{len(suites)} test dəsti keçdi.")
        return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
