#!/usr/bin/env python3
"""Turn a competitor video into an actual script, on this machine, for nothing.

Apify will sell us a transcript and a scene by scene description. It costs about
9 cents a video and needs credit on the account. Everything it does can be done
locally with tools that are already free:

    yt-dlp          gets the video file
    TikTok subs     some videos already carry captions, which skips the next step
    faster-whisper  speech to text with timings, runs on the laptop
    ffmpeg          finds the cuts and pulls a frame from each one
    tesseract       reads the text burned into those frames

What comes out is the real thing: what is said, when it is said, what is written
on screen, and where the cuts are. That is a script.

    python tools/transcribe.py --top 3
    python tools/transcribe.py --tier "BREAKING OUT" "DAY TWO"
    python tools/transcribe.py --url https://www.tiktok.com/@someone/video/123
    python tools/transcribe.py --all --model small

One warning before you run it. TikTok is blocked by most Indian ISPs, and this
downloads straight from TikTok, so from a connection in India every video fails
at the first step. Turn a VPN on, or run it from a machine outside India.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
RADAR = REPO / "data" / "RADAR.jsonl"
OUT = REPO / "data" / "transcripts"
CACHE = REPO / "data" / ".video-cache"

SCENE_THRESHOLD = 0.30      # ffmpeg scene score. Lower finds more cuts.
MIN_SCENE_GAP = 0.8         # seconds. TikTok cuts fast; below this it is noise.


# --------------------------------------------------------------------------
# the outside world
# --------------------------------------------------------------------------
def need(tool: str, install: str) -> None:
    if shutil.which(tool) is None:
        sys.exit(f"\n{tool} is not installed.\n  {install}\n")


def need_module(module: str, install: str) -> None:
    """Look for the package inside this interpreter, not on PATH.

    Running .venv/bin/python does not add .venv/bin to PATH, so a yt-dlp that is
    installed and working still looks missing to shutil.which.
    """
    import importlib.util
    if importlib.util.find_spec(module) is None:
        sys.exit(f"\n{module.replace('_', '-')} is not installed in this python.\n"
                 f"  {sys.executable} -m pip install {install}\n")


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def download(url: str, dest: Path) -> tuple[Path, Path | None]:
    """Fetch the video, and TikTok's own captions when it has them.

    Returns (video path, subtitle path or None). A video that already carries
    captions does not need transcribing, which is most of the runtime saved.
    """
    dest.mkdir(parents=True, exist_ok=True)
    stem = dest / "video"
    existing = list(dest.glob("video.mp4"))
    if not existing:
        result = run([
            sys.executable, "-m", "yt_dlp", url,
            "-f", "mp4",
            "-o", str(stem) + ".%(ext)s",
            "--write-subs", "--write-auto-subs", "--sub-format", "vtt",
            "--no-playlist", "--no-warnings", "--quiet",
        ])
        if result.returncode != 0:
            err = (result.stderr or "").strip()
            if any(w in err.lower() for w in ("resolve", "timed out", "connection", "unreachable")):
                raise RuntimeError(
                    "could not reach TikTok. Most Indian ISPs block it. "
                    "Turn a VPN on and run this again.")
            raise RuntimeError(err.splitlines()[-1] if err else "yt-dlp failed")
    video = next(iter(dest.glob("video.mp4")), None)
    if video is None:
        raise RuntimeError("yt-dlp finished but produced no mp4")
    subs = next(iter(dest.glob("video*.vtt")), None)
    return video, subs


def duration_of(video: Path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", str(video)]).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


# --------------------------------------------------------------------------
# what is said
# --------------------------------------------------------------------------
def parse_vtt(path: Path) -> list[dict[str, Any]]:
    """TikTok's own captions, which are already timed and cost nothing."""
    stamp = re.compile(r"(\d+):(\d+):([\d.]+)\s*-->\s*(\d+):(\d+):([\d.]+)")
    segments, current = [], None
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = stamp.search(line)
        if m:
            h1, m1, s1, h2, m2, s2 = m.groups()
            current = {"start": int(h1) * 3600 + int(m1) * 60 + float(s1),
                       "end": int(h2) * 3600 + int(m2) * 60 + float(s2),
                       "text": ""}
            segments.append(current)
        elif current is not None and line.strip() and not line.startswith(("WEBVTT", "Kind:", "Language:")):
            current["text"] = (current["text"] + " " + line.strip()).strip()
    return [s for s in segments if s["text"]]


def whisper(video: Path, model: str, translate: bool) -> tuple[list[dict], str]:
    """Speech to text, locally. Handles every language in the competitor set."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("\nfaster-whisper is not installed.\n"
                 "  pip install faster-whisper\n")
    wav = video.with_suffix(".wav")
    if not wav.exists():
        run(["ffmpeg", "-y", "-i", str(video), "-ac", "1", "-ar", "16000",
             "-vn", str(wav)])
    size = model
    engine = WhisperModel(size, device="auto", compute_type="int8")
    segments, info = engine.transcribe(
        str(wav), task="translate" if translate else "transcribe",
        vad_filter=True, word_timestamps=False)
    out = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
           for s in segments if s.text.strip()]
    return out, getattr(info, "language", "") or ""


# --------------------------------------------------------------------------
# what is on screen
# --------------------------------------------------------------------------
def scene_times(video: Path, seconds: float) -> list[float]:
    """Where the cuts are. Always includes the first frame."""
    result = run(["ffmpeg", "-i", str(video), "-filter:v",
                  f"select='gt(scene,{SCENE_THRESHOLD})',showinfo",
                  "-f", "null", "-"])
    times = [0.0]
    for m in re.finditer(r"pts_time:([\d.]+)", result.stderr or ""):
        t = float(m.group(1))
        if t - times[-1] >= MIN_SCENE_GAP:
            times.append(round(t, 2))
    # A video with no detected cut is one long take. Sample it anyway, or we
    # would read the on-screen text of the first frame and nothing else.
    if len(times) == 1 and seconds > 6:
        times = [round(t, 2) for t in
                 (seconds * f for f in (0.05, 0.3, 0.55, 0.8))]
    return times


def read_frames(video: Path, times: list[float], workdir: Path) -> list[dict[str, Any]]:
    """Pull one frame per cut and read the text burned into it.

    On-screen text carries the hook on most of these videos, and it is often not
    spoken out loud at all, so a transcript alone misses half the script.
    """
    if shutil.which("tesseract") is None:
        return [{"t": t, "ocr": ""} for t in times]
    workdir.mkdir(parents=True, exist_ok=True)
    scenes = []
    for i, t in enumerate(times):
        frame = workdir / f"f{i:02d}.png"
        if not frame.exists():
            run(["ffmpeg", "-y", "-ss", str(t), "-i", str(video),
                 "-frames:v", "1", "-q:v", "2", str(frame)])
        text = ""
        if frame.exists():
            text = run(["tesseract", str(frame), "stdout", "--psm", "6"]).stdout
        scenes.append({"t": t, "ocr": clean_ocr(text)})
    return scenes


def clean_ocr(raw: str) -> str:
    """Tesseract on a video frame produces a lot of confident nonsense."""
    lines = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if len(line) < 3:
            continue
        letters = sum(c.isalpha() for c in line)
        if letters < len(line) * 0.55:      # mostly symbols, it misread the UI
            continue
        if re.fullmatch(r"[A-Za-z]{1,2}( [A-Za-z]{1,2})*", line):
            continue
        lines.append(line)
    return " / ".join(dict.fromkeys(lines))[:300]


# --------------------------------------------------------------------------
# putting it together
# --------------------------------------------------------------------------
def clock(t: float) -> str:
    t = max(0, int(round(t)))
    return f"{t // 60}:{t % 60:02d}"


def to_markdown(row: dict, data: dict) -> str:
    L = [f"# {row.get('creator') and '@' + row['creator'] or 'video'} · what is actually in it",
         "",
         f"{row.get('url','')}",
         "",
         f"{row.get('competitor','')} · {data['duration']:.0f}s · "
         f"{int(row.get('views') or 0):,} views · language {data.get('language') or 'unknown'}",
         "", "| Time | On screen | Said |", "|---|---|---|"]
    marks = sorted({round(s["t"], 1) for s in data["scenes"]}
                   | {round(s["start"], 1) for s in data["segments"]})
    for t in marks:
        on = next((s["ocr"] for s in data["scenes"] if abs(s["t"] - t) < 0.25), "")
        said = " ".join(s["text"] for s in data["segments"]
                        if abs(s["start"] - t) < 0.25)
        if not on and not said:
            continue
        L.append(f"| {clock(t)} | {on.replace('|','/')} | {said.replace('|','/')} |")
    L += ["", "## Every word, in order", ""]
    L += [f"**{clock(s['start'])}** {s['text']}" for s in data["segments"]] or ["(no speech found)"]
    return "\n".join(L) + "\n"


def transcribe_one(row: dict, args) -> dict[str, Any]:
    url = row.get("url") or ""
    cid = str(row.get("content_id") or re.sub(r"\D", "", url)[-19:] or "unknown")
    out_json = OUT / f"{cid}.json"
    if out_json.exists() and not args.force:
        print(f"  have it already: {cid}")
        return json.loads(out_json.read_text())

    work = CACHE / cid
    print(f"  downloading @{row.get('creator','')} ...", flush=True)
    video, subs = download(url, work)
    seconds = duration_of(video)

    if subs and not args.force_whisper:
        print("  using TikTok's own captions")
        segments, language = parse_vtt(subs), "from captions"
    else:
        print(f"  transcribing with whisper ({args.model}) ...", flush=True)
        segments, language = whisper(video, args.model, args.translate)

    scenes = [] if args.no_ocr else read_frames(video, scene_times(video, seconds), work / "frames")

    data = {"content_id": cid, "url": url, "creator": row.get("creator"),
            "competitor": row.get("competitor"), "duration": round(seconds, 2),
            "language": language, "segments": segments, "scenes": scenes,
            "source": "local"}
    OUT.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    (OUT / f"{cid}.md").write_text(to_markdown(row, data), encoding="utf-8")
    print(f"  wrote {out_json.relative_to(REPO)} "
          f"({len(segments)} lines said, {len(scenes)} scenes)")
    return data


def load_rows() -> list[dict]:
    if not RADAR.exists():
        sys.exit("data/RADAR.jsonl is empty. Collect and score something first.")
    return [json.loads(l) for l in RADAR.read_text().splitlines() if l.strip()]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", action="append", help="a TikTok URL. Repeatable.")
    ap.add_argument("--top", type=int, help="the N best scoring videos in the radar")
    ap.add_argument("--tier", nargs="*", help='e.g. --tier "BREAKING OUT" "DAY TWO"')
    ap.add_argument("--all", action="store_true", help="every video in the radar")
    ap.add_argument("--model", default="small",
                    help="whisper size: tiny, base, small, medium. small is the sweet spot")
    ap.add_argument("--translate", action="store_true",
                    help="translate into English instead of transcribing as spoken")
    ap.add_argument("--no-ocr", action="store_true", help="skip reading on-screen text")
    ap.add_argument("--force", action="store_true", help="redo ones already done")
    ap.add_argument("--force-whisper", action="store_true",
                    help="transcribe even when TikTok supplies captions")
    args = ap.parse_args()

    need_module("yt_dlp", "yt-dlp")
    need("ffmpeg", "brew install ffmpeg")

    if args.url:
        rows = [{"url": u} for u in args.url]
    else:
        rows = load_rows()
        if args.tier:
            wanted = {t.upper() for t in args.tier}
            rows = [r for r in rows if str(r.get("takeoff_tier", "")).upper() in wanted]
        if args.top:
            rows = sorted(rows, key=lambda r: -(r.get("radar_score") or 0))[:args.top]
        elif not args.tier and not args.all:
            ap.error("pick one of --url, --top, --tier or --all")

    print(f"\n{len(rows)} video{'' if len(rows) == 1 else 's'} to do\n")
    done = failed = 0
    for i, row in enumerate(rows, 1):
        print(f"[{i}/{len(rows)}] {row.get('url','')}")
        try:
            transcribe_one(row, args)
            done += 1
        except Exception as exc:                      # noqa: BLE001
            print(f"  FAILED: {exc}")
            failed += 1
    print(f"\n{done} done, {failed} failed. Written to {OUT.relative_to(REPO)}/")
    if done:
        print("Open the dashboard and the real script is on the row, "
              "next to the idea we wrote.")


if __name__ == "__main__":
    main()
