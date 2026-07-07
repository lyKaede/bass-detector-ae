# BassDetector 🎵

**Built for After Effects.** Detect the **bass hits / kicks** (20–250 Hz) in an audio or video file and turn them into **After Effects markers** with millisecond precision — so you can sync cuts, animations and effects to the beat automatically instead of scrubbing the timeline by hand.

It also exports a plain-text list of the timings, and works as a general video-editing beat/kick detector.

## Features

- Accepts **audio** (MP3, WAV, M4A, AAC, FLAC, OGG, OPUS, WMA, AIFF) and **video** (MP4, MOV, MKV, AVI, M4V, WEBM, WMV, FLV)
- Extracts/decodes audio with **ffmpeg** (bundled — nothing to install separately)
- Band-pass filter (20–250 Hz) + RMS energy envelope + adaptive peak detection
- **Drag & drop** a file into the window, or drop it onto the `.exe`, or pick it from a dialog
- **Progress bar** while analyzing
- Outputs a folder next to the file containing:
  - `NAME_bass.txt` — readable list (index, timecode, seconds, strength)
  - `NAME_AfterEffects.jsx` — After Effects script that adds a marker on every bass hit

Each hit has `time` (`MM:SS.mmm`), `seconds` (decimal) and `strength` (0–1, where 1 = the strongest bass in the track).

## Download

Grab the ready-to-run **`BassDetector.exe`** from the [Releases](../../releases) page. It is a standalone Windows executable — no Python or dependencies required.

> The executable is built automatically on a Windows runner by GitHub Actions (see `.github/workflows/build.yml`) and attached to each release.

## Usage

1. **Drag** an audio/video file into the window (or onto the `.exe`, or use *Select file*).
2. Click **Analyze bass**.
3. The results folder `NAME_bass/` appears next to your file.

Command line:

```
BassDetector.exe track.mp3 --cli
```

## After Effects integration

The generated `NAME_AfterEffects.jsx` adds a **marker** at each bass time:

1. In After Effects open your project and select/open the composition.
2. **File > Scripts > Run Script File...**
3. Choose `NAME_AfterEffects.jsx`.

Markers land on the composition timeline (AE CC 2017+); on older versions the script creates a `BASSI` null layer holding the markers. Each marker is numbered progressively (`1`, `2`, `3`, ...) in time order.

> Markers start at t=0. If your audio doesn't start at the very beginning of the comp, shift the markers / null layer to line them up.

## Build it yourself (Windows)

Requires **Python 3.9+** (tick *"Add python.exe to PATH"* during install).

```
build.bat
```

The script installs the dependencies and packages everything (ffmpeg + drag & drop included) into a single standalone `dist\BassDetector.exe`.

Or manually:

```
pip install -r requirements.txt
pyinstaller --noconfirm --onefile --windowed --name BassDetector ^
  --collect-all imageio_ffmpeg --collect-all tkinterdnd2 ^
  --collect-submodules scipy --hidden-import scipy._lib.messagestream ^
  bass_detector.py
```

## Tuning

In `bass_detector.py`, function `detect_bass`:
- `sensitivity` (default `1.5`) — lower = detect more (weaker) hits; higher = only strong hits.
- `min_gap_s` (default `0.16`) — minimum seconds between two hits.

## How it works

The audio is decoded to mono, band-pass filtered to 20–250 Hz (4th-order Butterworth, zero-phase), then a short-window RMS envelope is combined with its positive derivative to form an onset function. Peaks above an adaptive (median + MAD) threshold are picked with a minimum spacing, and low-energy filter-ringing artifacts are discarded. Strength is the per-peak low-band energy normalized to 0–1.

## License

MIT — see [LICENSE](LICENSE).
