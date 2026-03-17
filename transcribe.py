import os
import subprocess
import shutil
import sys
import datetime

# ─────────────────────────────────────────────
# CONFIGURATION — edit paths here if needed
# ─────────────────────────────────────────────

# os.path.expanduser resolves "~" to the current user's home directory
# This keeps paths portable across different machines/users
DESKTOP         = os.path.expanduser("~/Desktop")
INBOX           = os.path.expanduser("~/service_root/inbox")       # Staging area for incoming files
PROCESSING      = os.path.expanduser("~/service_root/processing")  # Active workspace during pipeline run
DELIVER         = os.path.expanduser("~/Desktop")                  # Final outputs delivered back to Desktop for easy upload
LOGS            = os.path.expanduser("~/service_root/logs")        # Persistent order log directory
MODELS_DIR      = os.path.expanduser("~/whisper_models")           # Local directory storing downloaded .bin model files

# whisper-cli is the compiled binary from whisper.cpp — installed via Homebrew (brew install whisper-cpp)
# whisper.cpp is a C++ port of OpenAI's Whisper, optimised to run on CPU without a GPU
WHISPER_BIN     = "/usr/local/bin/whisper-cli"

# Model options — each .bin file is a pre-trained Whisper model weight file
# Larger models = higher accuracy, longer processing time, more RAM
# medium is the default: best balance for typical client audio on a standard Mac
MODELS = {
    "1": ("medium", "ggml-medium.bin"),
    "2": ("small",  "ggml-small.bin"),
    "3": ("large",  "ggml-large-v3.bin"),
}

# Whisper requires uncompressed PCM audio — all other formats are converted to .wav first via ffmpeg
# These are the supported input container formats before conversion
SUPPORTED_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".aac", ".opus", ".ogg", ".mp4", ".mov", ".avi", ".mkv"}

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

# Consistent terminal output formatting for status messages throughout the pipeline
def flag(msg):
    print(f"\n▶  {msg}")

def success(msg):
    print(f"✅  {msg}")

def warn(msg):
    print(f"⚠️   {msg}")

def abort(msg):
    # Prints the error and exits with code 1 (standard non-zero exit = failure)
    print(f"\n❌  {msg}")
    sys.exit(1)

def ask(prompt, options=None):
    # Loops until the user provides valid input
    # If options=None, any input is accepted (used for free-text fields like filename or language code)
    while True:
        val = input(f"\n{prompt} ").strip()
        if options is None or val in options:
            return val
        print(f"   Please enter one of: {', '.join(options)}")

def versioned_path(base_path):
    # Prevents silent overwrites of existing output files
    # Appends _v2, _v3, _v4 if the base filename already exists at the destination
    # Caps at v4 to avoid uncontrolled file accumulation
    if not os.path.exists(base_path):
        return base_path
    root, ext = os.path.splitext(base_path)
    for v in range(2, 5):
        candidate = f"{root}_v{v}{ext}"
        if not os.path.exists(candidate):
            return candidate
    warn("v4 already exists — overwriting v4.")
    return f"{root}_v4{ext}"

def run(cmd, step_name):
    # Executes a shell command as a list of arguments (safer than shell=True — avoids injection risks)
    # Prints the command for transparency, aborts on non-zero return code
    print(f"   $ {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        abort(f"Failed at: {step_name}. Check the command above.")
    return result

# ─────────────────────────────────────────────
# STEP 0 — STARTUP CHECKS
# ─────────────────────────────────────────────
flag("STEP 0 — Checking environment...")

# Validate that all required directories exist before touching any files
# Fail early rather than mid-pipeline to avoid partial processing states
for folder in [INBOX, PROCESSING, DELIVER, LOGS, MODELS_DIR]:
    if not os.path.isdir(folder):
        abort(f"Missing folder: {folder}\nRun: mkdir -p ~/service_root/{{inbox,processing,deliver,logs}} ~/whisper_models")

# Confirm whisper-cli binary is present at the expected Homebrew install path
if not os.path.isfile(WHISPER_BIN):
    abort(f"whisper-cli not found at {WHISPER_BIN}")

# shutil.which checks if ffmpeg is available on the system PATH (equivalent to running `which ffmpeg` in terminal)
# ffmpeg is installed via Homebrew: brew install ffmpeg
if not shutil.which("ffmpeg"):
    abort("ffmpeg not found. Run: brew install ffmpeg")

success("Environment OK.")

# ─────────────────────────────────────────────
# STEP 1 — LOCATE FILE
# ─────────────────────────────────────────────
flag("STEP 1 — File location")

resume_mode = False
existing_wav = os.path.join(PROCESSING, "audio.wav")

# Resume mode: if a previous run was interrupted after conversion but before transcription,
# the .wav file is still in the processing folder — skip re-conversion and pick up from there
if os.path.isfile(existing_wav):
    print(f"\n   Found existing audio.wav in processing folder.")
    choice = ask("Resume from existing processing file? (y/n) — 'n' to start fresh from Desktop:", ["y", "n"])
    if choice == "y":
        resume_mode = True
        # Stem is needed for output file naming — can't infer it from audio.wav alone
        original_stem = ask("Enter the original filename stem (without extension) for naming outputs\n  e.g. 'client_audio':")
        success(f"Resuming from processing/audio.wav — stem: '{original_stem}'")

if not resume_mode:
    raw_name = ask("Enter the filename on your Desktop (include extension, spaces OK):")
    src_path = os.path.join(DESKTOP, raw_name)

    if not os.path.isfile(src_path):
        abort(f"File not found on Desktop: {src_path}\nCheck the filename and try again.")

    # Validate file extension before attempting conversion
    ext = os.path.splitext(raw_name)[1].lower()
    if ext not in SUPPORTED_EXTS:
        abort(f"Unsupported file type: {ext}\nSupported: {', '.join(SUPPORTED_EXTS)}")

    # Strip extension to use as the base name for all output files
    original_stem = os.path.splitext(raw_name)[0]
    inbox_path = os.path.join(INBOX, raw_name)

    # Prompt for trim settings BEFORE moving the file
    # User may need to check the file on Desktop (e.g. in QuickTime) before specifying timestamps
    flag("STEP 2 — Trim settings (check your file on Desktop now if needed)")
    ss_flag = ask("Start audio from a specific time? (e.g. 00:00:05) or press Enter to skip:")
    to_flag = ask("End audio at a specific time?    (e.g. 00:00:30) or press Enter to skip:")

    # Copy original file to inbox — original stays on Desktop throughout
    # try/except handles Ctrl+C mid-operation to avoid leaving inbox copy stranded
    try:
        shutil.copy2(src_path, inbox_path)
        success(f"Copied '{raw_name}' → inbox/")

        flag("STEP 2 — Converting to 16kHz mono WAV...")
        wav_path = os.path.join(PROCESSING, "audio.wav")

        # ffmpeg conversion flags:
        # -y         → overwrite output file without prompting
        # -i         → input file path
        # -ss        → start timestamp (optional trim)
        # -to        → end timestamp (optional trim)
        # -ar 16000  → resample audio to 16,000 Hz (Whisper's required sample rate)
        # -ac 1      → downmix to mono (Whisper does not use stereo channels)
        ffmpeg_cmd = ["ffmpeg", "-y", "-i", inbox_path]
        if ss_flag:
            ffmpeg_cmd += ["-ss", ss_flag]
        if to_flag:
            ffmpeg_cmd += ["-to", to_flag]
        ffmpeg_cmd += ["-ar", "16000", "-ac", "1", wav_path]

        run(ffmpeg_cmd, "ffmpeg conversion")

        # Delete inbox copy once conversion is confirmed — processing/audio.wav is the working file
        os.remove(inbox_path)
        success("Converted to audio.wav — inbox file deleted.")

    except KeyboardInterrupt:
        # Original file was never moved — just clean up the inbox copy if it exists
        print("\n\n⚠️  Aborted.")
        if os.path.isfile(inbox_path):
            os.remove(inbox_path)
            print(f"✅  Inbox copy removed. Original file safe on Desktop.")
        sys.exit(0)

# ─────────────────────────────────────────────
# STEP 3 — CHOOSE MODEL
# ─────────────────────────────────────────────
flag("STEP 3 — Choose Whisper model")
print("   1) medium  (default — recommended)")
print("   2) small   (fast, less accurate)")
print("   3) large   (premium jobs only, slow on Mac)")
model_choice = ask("Choose model [1/2/3]:", ["1", "2", "3"])
model_name, model_file = MODELS[model_choice]
model_path = os.path.join(MODELS_DIR, model_file)

# Confirm the selected .bin file exists locally — models must be downloaded separately
# Large model is ~3GB, medium ~1.5GB — not bundled with whisper.cpp install
if not os.path.isfile(model_path):
    abort(f"Model file not found: {model_path}")
success(f"Model: {model_name} ({model_file})")

# ─────────────────────────────────────────────
# STEP 4 — TRANSLATION?
# ─────────────────────────────────────────────
flag("STEP 4 — Translation settings")

# Whisper supports two modes: transcription (preserves source language) and translation (outputs English)
# Translation is built into the model — no external API or second pass required
translate = ask("Translate to English? (y/n):", ["y", "n"]) == "y"

# Language auto-detection uses Whisper's internal classifier on the first 30 seconds of audio
# Specifying the language manually skips detection and improves accuracy for known-language files
lang_code = "auto"
lang_choice = ask("Language detection — auto or specify? (auto/specify):", ["auto", "specify"])
if lang_choice == "specify":
    # ISO 639-1 two-letter codes: ar = Arabic, es = Spanish, fr = French, hi = Hindi, etc.
    lang_code = ask("Enter ISO 639-1 language code (e.g. ar, es, fr, am, hi):")
success(f"Language: {lang_code} | Translate: {translate}")

# ─────────────────────────────────────────────
# STEP 5 — OUTPUT FORMAT
# ─────────────────────────────────────────────
flag("STEP 5 — Output format")
print("   1) txt   — plain transcript")
print("   2) srt   — transcript with timestamps")
print("   3) docx  — Word document")
print("   4) txt + srt")
print("   5) txt + docx")
fmt_choice = ask("Choose output format [1/2/3/4/5]:", ["1", "2", "3", "4", "5"])

# Map format choice to boolean flags — drives which output flags are passed to whisper-cli
# and which post-processing steps (pandoc) are triggered
want_txt  = fmt_choice in ["1", "4", "5"]
want_srt  = fmt_choice in ["2", "4"]
want_docx = fmt_choice in ["3", "5"]

fmt_label = []
if want_txt:  fmt_label.append("txt")
if want_srt:  fmt_label.append("srt")
if want_docx: fmt_label.append("docx")

# ─────────────────────────────────────────────
# CONFIRM BEFORE RUNNING
# ─────────────────────────────────────────────

# Summary printed before committing to a potentially long transcription run
# Gives the user a final check before whisper-cli starts (which can take several minutes)
print("\n" + "─"*50)
print("  READY TO PROCESS")
print(f"  File stem : {original_stem}")
print(f"  Model     : {model_name}")
print(f"  Language  : {lang_code}")
print(f"  Translate : {'Yes → English' if translate else 'No'}")
print(f"  Output    : {', '.join(fmt_label)}")
print("─"*50)

go = ask("Begin transcription now? (y/n):", ["y", "n"])
if go == "n":
    # Non-destructive pause — audio.wav stays in processing for later resume
    print("\n   Paused. audio.wav is saved in ~/service_root/processing/")
    print("   Re-run this script and choose 'resume' to continue.")
    sys.exit(0)

# ─────────────────────────────────────────────
# STEP 6 — RUN WHISPER
# ─────────────────────────────────────────────
flag("STEP 6 — Running Whisper...")

wav_path = os.path.join(PROCESSING, "audio.wav")
out_stem = os.path.join(PROCESSING, "output")  # whisper-cli appends .txt / .srt to this stem automatically

# whisper-cli flags:
# -m        → path to the model .bin file
# -f        → path to the input .wav file
# -l        → source language code ("auto" triggers Whisper's built-in language detection)
# -pp       → print progress to terminal during transcription
# --translate → enables Whisper's built-in translation to English (only works toward English)
# -otxt     → output plain text file
# -osrt     → output SRT subtitle file with timestamps
# -of       → output file path stem (extensions are appended automatically by whisper-cli)
whisper_cmd = [
    WHISPER_BIN,
    "-m", model_path,
    "-f", wav_path,
    "-l", lang_code,
    "-pp",
]

if translate:
    whisper_cmd.append("--translate")

if want_txt or want_docx:
    whisper_cmd.append("-otxt")   # .docx conversion requires .txt as an intermediate
if want_srt:
    whisper_cmd.append("-osrt")

whisper_cmd += ["-of", out_stem]

run(whisper_cmd, "Whisper transcription")
success("Whisper finished.")

# ─────────────────────────────────────────────
# STEP 7 — DOCX CONVERSION
# ─────────────────────────────────────────────
if want_docx:
    flag("STEP 7 — Converting to .docx with pandoc...")
    # pandoc is a universal document converter — installed via Homebrew: brew install pandoc
    # It converts the whisper-generated .txt into a properly formatted Word document
    if not shutil.which("pandoc"):
        warn("pandoc not installed — skipping docx. Install with: brew install pandoc")
        want_docx = False
    else:
        docx_src = out_stem + ".txt"
        docx_out = out_stem + ".docx"
        run(["pandoc", docx_src, "-o", docx_out], "pandoc docx conversion")
        success("docx created.")

# ─────────────────────────────────────────────
# STEP 8 — MOVE TO DELIVER WITH PROPER NAMES
# ─────────────────────────────────────────────
flag("STEP 8 — Moving deliverables to deliver folder...")

# Build a descriptive output filename from the original stem + processing metadata
# e.g. "client_audio_translated_en_ar.txt" or "client_audio_transcript.srt"
suffix = "_translated_en" if translate else "_transcript"
lang_tag = f"_{lang_code}" if lang_code != "auto" else ""
base_name = f"{original_stem}{suffix}{lang_tag}"

moved = []

if want_txt or want_docx:
    src = out_stem + ".txt"
    if os.path.isfile(src):
        dst = versioned_path(os.path.join(DELIVER, base_name + ".txt"))
        shutil.move(src, dst)
        moved.append(dst)

if want_srt:
    src = out_stem + ".srt"
    if os.path.isfile(src):
        dst = versioned_path(os.path.join(DELIVER, base_name + ".srt"))
        shutil.move(src, dst)
        moved.append(dst)

if want_docx:
    src = out_stem + ".docx"
    if os.path.isfile(src):
        dst = versioned_path(os.path.join(DELIVER, base_name + ".docx"))
        shutil.move(src, dst)
        moved.append(dst)

for f in moved:
    success(f"Deliver → {os.path.basename(f)}")

# ─────────────────────────────────────────────
# STEP 9 — LOG
# ─────────────────────────────────────────────
flag("STEP 9 — Logging order...")

# Appends a single timestamped line to orders.log for order tracking and audit trail
# Format: YYYY-MM-DD HH:MM | filename | model | language | translate flag | output formats
log_line = f"{original_stem} | model={model_name} | lang={lang_code} | translate={translate} | outputs={','.join(fmt_label)}"
log_path = os.path.join(LOGS, "orders.log")
with open(log_path, "a") as lf:
    lf.write(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} | {log_line}\n")
success("Logged to orders.log")

# ─────────────────────────────────────────────
# DONE
# ─────────────────────────────────────────────
print("\n" + "═"*50)
print("  PIPELINE COMPLETE")
print(f"  File complete for delivery")
for f in moved:
    print(f"  → {os.path.basename(f)}")
print("═"*50)

# Post-delivery cleanup reminder — audio.wav is retained for 7 days in case of client disputes
# Manual deletion is intentional: avoids accidental data loss before delivery is confirmed
print("\n  Deliver output files, then run cleanup after 7 days:")
print("  rm -f ~/service_root/processing/audio.wav")
print(f"  echo \"$(date) deleted {original_stem}\" >> ~/service_root/logs/deletions.log\n")
