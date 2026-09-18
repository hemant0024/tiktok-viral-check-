# Scripts

Two different things get called a script in this project, and confusing them is
the single most expensive mistake available here. One is what the competitor
actually did. The other is what we would do instead. A brief that mixes them up
sends a creator off to shoot something nobody has ever seen work.

| | Where it comes from | What it is for |
|---|---|---|
| **Theirs** | `data/transcripts/`, produced by `tools/transcribe.py` or Apify | Knowing what actually happened in a video that took off |
| **Ours** | Written into the dashboard, picked per video | The thing we would shoot instead |

The dashboard keeps them apart on purpose. The column is called **Our idea**, not
Script. Open a row and their real script sits at the top with a green tag reading
**From the video**, ours sits underneath. A row with no transcript says so in
plain words and prints the command that would get one.

---

## Theirs: getting the real script

The radar has never stored what happens inside a video. It stores views, age,
engagement and the caption. That is enough to rank videos and useless for
rebuilding one.

### Free, on this machine

```bash
./tools/setup_transcribe.sh                              # once
python tools/transcribe.py --top 3                       # best three by score
python tools/transcribe.py --tier "BREAKING OUT" "DAY TWO"
python tools/transcribe.py --url https://www.tiktok.com/@someone/video/123
python tools/transcribe.py --all --model small
```

What it chains together:

```
yt-dlp            downloads the video
TikTok captions   used when the video has them, which skips transcription
faster-whisper    speech to text with timings when it does not
ffmpeg            finds the cuts, pulls one frame from each
tesseract         reads the text burned into those frames
```

On screen text matters as much as speech. On most of these videos the hook is
written across the first frame and never said out loud, so a transcript on its
own misses half the script.

Useful flags:

| Flag | What it does |
|---|---|
| `--model tiny\|base\|small\|medium` | Whisper size. `small` is the sweet spot on a laptop |
| `--translate` | English out, instead of the language spoken |
| `--no-ocr` | Skip reading the frames, roughly twice as fast |
| `--force` | Redo videos already done |
| `--force-whisper` | Transcribe even when TikTok supplies captions |

Output per video, in `data/transcripts/`:

```
7683950710215560480.json    segments, scenes, language, duration
7683950710215560480.md      the same thing as a readable script
```

**The catch.** This downloads straight from TikTok and most Indian ISPs block
TikTok, so from a normal connection in Delhi every video fails at the first step.
The tool catches that and says to turn a VPN on rather than printing a stack
trace. A machine outside India works too.

### Paid, through Apify

The scraper we already use has two switches we have never turned on:

```jsonc
{
  "downloadSubtitlesOptions": "TRANSCRIBE_ALL_VIDEOS",  // the words
  "aiVideoDescription": true                            // scene by scene, what is seen and heard
}
```

No VPN needed. Priced per video, on the free tier:

| | Videos | Cost |
|---|---|---|
| The BREAKING OUT one | 1 | $0.10 |
| The three worth copying | 3 | $0.25 |
| BREAKING OUT plus DAY TWO | 12 | $1.11 |
| Everything in the dashboard | 52 | $5.70 |

As of the 11 September run the account has $0.000923 left, so this route needs a
top up before it will run at all.

---

## Ours: the ideas in the dashboard

Fifty two written ideas, one assigned to each video, none repeated.

A **bit** is one whole idea that travels together: the hook, what the learner
does, what the cat says back, a second cat line, the line out, and the caption.
Hooks and punchlines used to be drawn from separate banks, which produced a
learner asking about their accent and a cat answering about ordering coffee. They
are one object now.

**How a video gets its idea**

1. **Angle** comes from the competitor's own caption where it gives one away.
   A caption mentioning moving countries picks a moving-countries idea; one with
   `jaja` or `ㅋㅋ` in it picks a comedy one. Failing that the angle comes from
   the shape below.
2. **Shape** comes from what the video did:
   - shares over 1% is **Passed along**, so the idea is one punchline, no demo
   - saves beating shares is **Filed to try later**, so the idea is a real demo
   - a high like rate on low views is **Held the people who saw it**, so the idea
     is fine and the account was too big
   - everything else is **Reach without reaction**, which is a warning
3. **Length and beat count** come from the video's own duration. Under 10 seconds
   gets four beats and a single punchline. Over 45 seconds gets a note telling
   the creator to cut it to 30, because nothing that long worked in the run.
4. **Assignment** runs over the whole set at once, best scoring video first, and
   never hands the same idea to two videos. It is computed from the full set, not
   the filtered view, so filtering and sorting never shuffle what a video has.

The spread is 14 comedy, 13 proof, 13 pain, 6 moving somewhere new, 6 progress.
The pain ones come straight from the audience notes in `config/product.yaml`:
freezing mid sentence, understanding everything and replying with nothing, the
accent embarrassment, years of study with no speaking.

**Rules every one of them follows**

- The cat gets the funny line. The product is the entertaining one.
- Never make the learner the joke. The cat is on their side. That is what gets a
  video sent to a friend rather than scrolled past.
- None of them promise fluency, or fluency in a number of days, or replacing a
  teacher, or certification, or job and visa outcomes. Those are the five claims
  the quality gate rejects and the five that get a language app reported.

---

## Getting it out of the dashboard

| Control | What you get |
|---|---|
| The **Our idea** column | Every hook, scannable down the page |
| Clicking one | The full script panel: their script if we have it, then ours, with Copy and Download |
| The document button in the top bar | Every idea on screen, written to one markdown file |
| CSV | The numbers, not the scripts |

A downloaded brief carries the reference link, what the video did in numbers,
what kind of video it was, the timed beats, the caption, how to shoot it, and the
never-say list. That is the thing to send a creator.

---

## Where everything lives

```
tools/transcribe.py          the local transcriber
tools/setup_transcribe.sh    its one time setup
data/transcripts/            what came out, JSON and markdown
src/ci/dashboard/page.html   the 52 ideas, the assignment, the script panel
src/ci/dashboard/api.py      transcript() and transcript_index()
config/product.yaml          the cat, the audience, the forbidden claims
tests/test_transcribe.py     parsing, OCR cleaning, and path safety
```
