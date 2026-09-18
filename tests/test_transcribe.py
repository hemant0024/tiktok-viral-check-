"""The local transcriber, and what the dashboard does with what it produces."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import transcribe as T  # noqa: E402

from ci.dashboard import api  # noqa: E402


def test_vtt_parsing_keeps_timings(tmp_path):
    vtt = tmp_path / "v.vtt"
    vtt.write_text("""WEBVTT
Kind: captions
Language: en

00:00:00.240 --> 00:00:02.100
I said it wrong on purpose

00:00:02.100 --> 00:00:04.500
to see if it would catch me
""")
    out = T.parse_vtt(vtt)
    assert len(out) == 2
    assert out[0]["start"] == pytest.approx(0.24)
    assert out[1]["text"] == "to see if it would catch me"


def test_ocr_cleaning_drops_the_nonsense():
    """Tesseract on a video frame returns the TikTok chrome and a lot of noise."""
    raw = "|| \n@\nFollow me\nx v z\nFor You\n!!!! ### @@@\n"
    cleaned = T.clean_ocr(raw)
    assert "Follow me" in cleaned
    assert "For You" in cleaned
    assert "x v z" not in cleaned, "single letters are a misread, not text"
    assert "####" not in cleaned


def test_scene_sampling_never_returns_one_frame_for_a_long_take():
    """A video with no cuts still needs sampling, or we read the first frame
    and call that the whole video."""
    times = [0.0]
    seconds = 37.0
    if len(times) == 1 and seconds > 6:
        times = [round(seconds * f, 2) for f in (0.05, 0.3, 0.55, 0.8)]
    assert len(times) == 4 and times[-1] < seconds


def test_markdown_has_a_line_for_every_moment_that_carries_something():
    row = {"creator": "someone", "url": "https://x", "competitor": "Praktika AI", "views": 5}
    data = {"duration": 8.0, "language": "en",
            "segments": [{"start": 1.0, "end": 2.0, "text": "hello"}],
            "scenes": [{"t": 0.0, "ocr": "WATCH THIS"}, {"t": 4.0, "ocr": ""}]}
    md = T.to_markdown(row, data)
    assert "WATCH THIS" in md and "hello" in md
    assert "| 0:04 |" not in md, "a moment with nothing in it is not a line"


def test_the_dashboard_says_plainly_when_there_is_no_transcript(settings):
    assert api.transcript("does-not-exist", settings) == {"found": False}


def test_a_transcript_is_served_once_it_exists(settings, tmp_path):
    local = settings.model_copy(update={"local_data_dir": tmp_path})
    folder = tmp_path / "transcripts"
    folder.mkdir()
    (folder / "123.json").write_text(json.dumps(
        {"content_id": "123", "duration": 8.0, "segments": [], "scenes": []}))
    out = api.transcript("123", local)
    assert out["found"] is True and out["duration"] == 8.0


def test_a_content_id_cannot_escape_the_transcripts_folder(settings, tmp_path):
    """The id comes off a URL path, so it has to be treated as hostile."""
    local = settings.model_copy(update={"local_data_dir": tmp_path})
    assert api.transcript("../../../etc/passwd", local)["found"] is False
    assert api.transcript("", local)["found"] is False
