# -*- coding: utf-8 -*-
"""
BassDetector - Detect bass hits (kicks) in an audio/video file and export their timings.

- Accepts AUDIO (mp3, wav, m4a, aac, flac, ogg, opus, wma) and VIDEO (mp4, mov, ...)
- Decodes the audio using ffmpeg (bundled via imageio-ffmpeg)
- Band-pass filters the low frequencies (20-250 Hz) and detects peaks (kick / strong bass)
- Exports a TXT list and an After Effects .jsx script that drops MARKERS on each hit
- tkinter GUI with in-window drag & drop (via tkinterdnd2) and a progress bar
"""

import os
import sys
import queue
import wave
import tempfile
import threading
import subprocess

import numpy as np
from scipy.signal import butter, sosfiltfilt, find_peaks


# Accepted extensions
AUDIO_EXT = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aiff", ".alac")
VIDEO_EXT = (".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm", ".wmv", ".flv")


# ----------------------------------------------------------------------------
# ffmpeg (bundled via imageio-ffmpeg)
# ----------------------------------------------------------------------------

def get_ffmpeg_exe():
    """Return the path to the bundled ffmpeg executable."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"  # fallback: ffmpeg on the system PATH


# ----------------------------------------------------------------------------
# Audio decode -> mono 16-bit PCM WAV
# ----------------------------------------------------------------------------

def extract_audio(media_path, target_sr=22050, progress=None):
    """Decode the audio track (from an audio or video file) into a temporary mono WAV."""
    if progress:
        progress("Reading and decoding audio...", 5)

    ffmpeg = get_ffmpeg_exe()
    tmp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp_wav.close()

    cmd = [
        ffmpeg, "-y",
        "-i", media_path,
        "-vn",                       # ignore any video stream
        "-ac", "1",                  # mono
        "-ar", str(target_sr),       # sample rate
        "-acodec", "pcm_s16le",      # 16-bit PCM WAV
        tmp_wav.name,
    ]
    creationflags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW on Windows
    proc = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creationflags
    )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="ignore")[-600:]
        raise RuntimeError("ffmpeg could not read the audio:\n" + err)

    return tmp_wav.name


def read_wav_mono(wav_path):
    """Read a 16-bit mono PCM WAV. Returns (float32 samples in [-1,1], sample_rate)."""
    with wave.open(wav_path, "rb") as wf:
        sr = wf.getframerate()
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    if sampwidth != 2:
        raise RuntimeError("Unsupported WAV format (16-bit expected).")

    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if n_channels > 1:
        data = data.reshape(-1, n_channels).mean(axis=1)
    return data, sr


# ----------------------------------------------------------------------------
# Bass detection
# ----------------------------------------------------------------------------

def bandpass_lowfreq(samples, sr, low=20.0, high=250.0):
    """Band-pass filter to isolate the low frequencies (20-250 Hz)."""
    nyq = sr / 2.0
    high = min(high, nyq - 1.0)
    low = max(low, 1.0)
    sos = butter(4, [low / nyq, high / nyq], btype="band", output="sos")
    return sosfiltfilt(sos, samples)


def detect_bass(samples, sr, sensitivity=1.5, min_gap_s=0.16, progress=None):
    """
    Detect strong-bass moments.

    Returns a list of dicts: {seconds, time, strength}
    - seconds: time in seconds (float, millisecond precise)
    - time: "MM:SS.mmm" string
    - strength: 0-1 normalized strength
    """
    if progress:
        progress("Low-frequency filtering (20-250 Hz)...", 40)

    low = bandpass_lowfreq(samples, sr)

    hop = max(1, int(sr * 0.010))       # 10 ms
    win = max(hop, int(sr * 0.025))     # 25 ms

    if progress:
        progress("Computing the energy envelope...", 60)

    n = len(low)
    n_frames = 1 + (n - win) // hop if n > win else 1
    env = np.empty(n_frames, dtype=np.float32)
    sq = low.astype(np.float64) ** 2
    csum = np.concatenate(([0.0], np.cumsum(sq)))
    for i in range(n_frames):
        start = i * hop
        end = min(start + win, n)
        env[i] = np.sqrt((csum[end] - csum[start]) / max(1, end - start))

    times = (np.arange(n_frames) * hop + win / 2.0) / sr

    if env.max() <= 0:
        return []

    diff = np.diff(env, prepend=env[0])
    onset = np.clip(diff, 0, None)
    detect = env * 0.4 + onset * 0.6

    if progress:
        progress("Detecting kicks...", 80)

    med = np.median(detect)
    mad = np.median(np.abs(detect - med)) + 1e-9
    threshold = med + sensitivity * mad
    distance = max(1, int(min_gap_s / (hop / sr)))

    peaks, _ = find_peaks(detect, height=threshold, distance=distance)
    if len(peaks) == 0:
        return []

    # Drop low-energy artifacts (filter ringing / decay tails)
    peak_energy_all = env[peaks]
    keep = peak_energy_all >= 0.08 * peak_energy_all.max()
    peaks = peaks[keep]
    if len(peaks) == 0:
        return []

    peak_energy = env[peaks]
    emin, emax = peak_energy.min(), peak_energy.max()
    if emax > emin:
        strength = (peak_energy - emin) / (emax - emin)
    else:
        strength = np.ones_like(peak_energy)

    results = []
    for idx, s in zip(peaks, strength):
        t = float(times[idx])
        results.append({
            "seconds": round(t, 3),
            "time": format_time(t),
            "strength": round(float(s), 3),
        })
    return results


def format_time(seconds):
    """Format seconds as MM:SS.mmm (millisecond precise)."""
    m = int(seconds // 60)
    s = seconds - m * 60
    return "{:02d}:{:06.3f}".format(m, s)


# ----------------------------------------------------------------------------
# Exporting results
# ----------------------------------------------------------------------------

def export_results(media_path, bassi):
    folder = os.path.dirname(media_path)
    stem = os.path.splitext(os.path.basename(media_path))[0]
    out_dir = os.path.join(folder, stem + "_bass")
    os.makedirs(out_dir, exist_ok=True)

    out_txt = os.path.join(out_dir, stem + "_bass.txt")
    out_jsx = os.path.join(out_dir, stem + "_AfterEffects.jsx")

    with open(out_txt, "w", encoding="utf-8") as f:
        f.write("BASS HITS - {}\n".format(os.path.basename(media_path)))
        f.write("Total: {} hits\n".format(len(bassi)))
        f.write("=" * 40 + "\n")
        f.write("{:<4}  {:<12}  {:>10}  {:>8}\n".format("#", "TIME", "SECONDS", "STRENGTH"))
        f.write("-" * 40 + "\n")
        for i, b in enumerate(bassi, 1):
            f.write("{:<4}  {:<12}  {:>10.3f}  {:>8.2f}\n".format(
                i, b["time"], b["seconds"], b["strength"]))

    write_ae_jsx(out_jsx, media_path, bassi)

    return out_dir, out_txt, out_jsx


def write_ae_jsx(out_jsx, media_path, bassi):
    """Generate an After Effects script that adds MARKERS at each bass time."""
    items = ",\n".join(
        "        {{t: {:.3f}, s: {:.3f}}}".format(b["seconds"], b["strength"])
        for b in bassi
    )
    name = os.path.basename(media_path).replace("\\", "/").replace('"', '\\"')

    jsx = '''// =====================================================================
// BassDetector -> After Effects : bass MARKERS
// Source: %s
// USAGE:
//   1. Open your project and select/open the target composition.
//   2. File > Scripts > Run Script File...
//   3. Pick this file. Markers are added to the timeline.
// Markers assume the audio starts at t=0 in the comp.
// =====================================================================
{
    var bassi = [
%s
    ];

    app.beginUndoGroup("BassDetector - bass markers");

    var comp = app.project.activeItem;
    if (!(comp && comp instanceof CompItem)) {
        for (var i = 1; i <= app.project.numItems; i++) {
            if (app.project.item(i) instanceof CompItem) { comp = app.project.item(i); break; }
        }
    }

    if (!(comp && comp instanceof CompItem)) {
        alert("BassDetector: open or select a composition before running the script.");
    } else {
        var added = 0;

        // Try COMPOSITION markers (AE CC 2017+), otherwise fall back to a null layer.
        var useComp = false;
        try { if (comp.markerProperty) { useComp = true; } } catch (e) { useComp = false; }

        if (useComp) {
            for (var j = 0; j < bassi.length; j++) {
                var mv = new MarkerValue(String(j + 1));
                comp.markerProperty.setValueAtTime(bassi[j].t, mv);
                added++;
            }
        } else {
            var nl = comp.layers.addNull();
            nl.name = "BASSI";
            nl.guideLayer = true;
            var mp = nl.property("Marker");
            for (var k = 0; k < bassi.length; k++) {
                var mv2 = new MarkerValue(String(k + 1));
                mp.setValueAtTime(bassi[k].t, mv2);
                added++;
            }
        }

        alert("BassDetector: added " + added + " markers to comp \\"" + comp.name + "\\".");
    }

    app.endUndoGroup();
}
''' % (name, items)

    with open(out_jsx, "w", encoding="utf-8") as f:
        f.write(jsx)


# ----------------------------------------------------------------------------
# Full pipeline
# ----------------------------------------------------------------------------

def analyze_media(media_path, progress=None, sensitivity=1.5):
    if progress:
        progress("Starting analysis...", 1)
    wav = extract_audio(media_path, progress=progress)
    try:
        samples, sr = read_wav_mono(wav)
        if progress:
            progress("Audio loaded ({:.1f}s)".format(len(samples) / sr), 30)
        bassi = detect_bass(samples, sr, sensitivity=sensitivity, progress=progress)
    finally:
        try:
            os.remove(wav)
        except OSError:
            pass
    if progress:
        progress("Exporting files...", 95)
    files = export_results(media_path, bassi)
    if progress:
        progress("Done: {} bass hits".format(len(bassi)), 100)
    return bassi, files


# ----------------------------------------------------------------------------
# Console mode: BassDetector.exe track.mp3 --cli
# ----------------------------------------------------------------------------

def run_cli(media_path):
    def cli_progress(msg, pct):
        sys.stdout.write("\r[{:3d}%] {:<50}".format(int(pct), msg))
        sys.stdout.flush()
    print("Analyzing:", media_path)
    bassi, (out_dir, out_txt, out_jsx) = analyze_media(media_path, progress=cli_progress)
    print()
    print("Bass hits:", len(bassi))
    print("Folder:", out_dir)
    print("  ->", os.path.basename(out_txt))
    print("  ->", os.path.basename(out_jsx))


# ----------------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------------

def _clean_dnd_path(data):
    """Extract a clean file path from a tkinterdnd2 drag&drop event."""
    data = data.strip()
    if data.startswith("{") and "}" in data:
        return data[1:data.index("}")]
    return data.split()[0] if data else ""


def run_gui(initial_file=None):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    dnd_ok = False
    try:
        from tkinterdnd2 import TkinterDnD, DND_FILES
        root = TkinterDnD.Tk()
        dnd_ok = True
    except Exception:
        root = tk.Tk()

    root.title("BassDetector - Detect the bass")
    root.geometry("580x400")
    root.configure(bg="#1e1e2e")

    state = {"file": initial_file, "running": False}
    ui_queue = queue.Queue()

    tk.Label(root, text="BassDetector", font=("Segoe UI", 20, "bold"),
             bg="#1e1e2e", fg="#89b4fa").pack(pady=(18, 2))
    tk.Label(root, text="Detect the kicks / bass (20-250 Hz) in audio or video",
             font=("Segoe UI", 10), bg="#1e1e2e", fg="#cdd6f4").pack()

    drop_text = ("Drag your file here  (MP3, WAV, MP4, ...)"
                 if dnd_ok else "Select a file  (MP3, WAV, MP4, ...)")
    drop = tk.Label(root, text=drop_text, font=("Segoe UI", 11),
                    bg="#313244", fg="#f9e2af", height=4, relief="ridge", bd=2)
    drop.pack(fill="x", padx=30, pady=(16, 6))

    file_var = tk.StringVar(value="No file selected")
    tk.Label(root, textvariable=file_var, font=("Segoe UI", 9), bg="#1e1e2e",
             fg="#bac2de", wraplength=520, justify="center").pack(pady=(0, 4))

    def set_file(path):
        if path:
            state["file"] = path
            file_var.set(path)
            drop.config(text="Ready: " + os.path.basename(path), fg="#a6e3a1")

    def choose_file():
        types = "*" + " *".join(e[1:] for e in (AUDIO_EXT + VIDEO_EXT))
        path = filedialog.askopenfilename(
            title="Select an audio or video file",
            filetypes=[("Audio/Video", types), ("All files", "*.*")],
        )
        if path:
            set_file(path)

    if dnd_ok:
        def on_drop(event):
            set_file(_clean_dnd_path(event.data))
        drop.drop_target_register(DND_FILES)
        drop.dnd_bind("<<Drop>>", on_drop)
        root.drop_target_register(DND_FILES)
        root.dnd_bind("<<Drop>>", on_drop)
    drop.bind("<Button-1>", lambda e: choose_file())

    tk.Button(root, text="Select file", command=choose_file,
              font=("Segoe UI", 11, "bold"), bg="#89b4fa", fg="#1e1e2e",
              activebackground="#b4befe", relief="flat", padx=14, pady=6).pack(pady=2)

    prog = ttk.Progressbar(root, length=500, mode="determinate", maximum=100)
    prog.pack(pady=(16, 4))
    status_var = tk.StringVar(value="Ready.")
    tk.Label(root, textvariable=status_var, font=("Segoe UI", 9),
             bg="#1e1e2e", fg="#a6e3a1").pack()

    def progress_cb(msg, pct):
        ui_queue.put(("progress", msg, pct))

    def worker(path):
        try:
            bassi, files = analyze_media(path, progress=progress_cb)
            ui_queue.put(("done", bassi, files))
        except Exception as e:
            ui_queue.put(("error", str(e), None))

    def start():
        if state["running"]:
            return
        if not state["file"]:
            messagebox.showwarning("Warning", "Drag or select a file first.")
            return
        state["running"] = True
        run_btn.config(state="disabled", text="Analyzing...")
        threading.Thread(target=worker, args=(state["file"],), daemon=True).start()

    run_btn = tk.Button(root, text="Analyze bass", command=start,
                        font=("Segoe UI", 12, "bold"), bg="#a6e3a1", fg="#1e1e2e",
                        activebackground="#94e2d5", relief="flat", padx=20, pady=8)
    run_btn.pack(pady=14)

    def poll():
        try:
            while True:
                item = ui_queue.get_nowait()
                kind = item[0]
                if kind == "progress":
                    _, msg, pct = item
                    prog["value"] = pct
                    status_var.set(msg)
                elif kind == "done":
                    _, bassi, files = item
                    out_dir, out_txt, out_jsx = files
                    prog["value"] = 100
                    status_var.set("Done: {} bass hits".format(len(bassi)))
                    state["running"] = False
                    run_btn.config(state="normal", text="Analyze bass")
                    messagebox.showinfo(
                        "Done!",
                        "Detected {} bass hits.\n\nSaved in folder:\n{}\n\n- {}\n- {}".format(
                            len(bassi), out_dir,
                            os.path.basename(out_txt), os.path.basename(out_jsx)))
                elif kind == "error":
                    _, err, _ = item
                    state["running"] = False
                    run_btn.config(state="normal", text="Analyze bass")
                    status_var.set("Error.")
                    messagebox.showerror("Error", err)
        except queue.Empty:
            pass
        root.after(100, poll)

    if initial_file:
        set_file(initial_file)

    root.after(100, poll)
    root.mainloop()


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    no_gui = "--cli" in sys.argv or "--nogui" in sys.argv

    if args and no_gui:
        run_cli(args[0])
    elif args:
        run_gui(initial_file=args[0])
    else:
        run_gui()


if __name__ == "__main__":
    main()
