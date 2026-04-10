# Whisper Transcription & Translation Pipeline

Automated audio/video transcription and translation pipeline built in Python. Eliminates manual transcription bottlenecks. Input goes in, clean transcript comes out. No API costs, no data leaving your machine.

---

## Demo

[![Whisper Pipeline Demo](https://img.youtube.com/vi/PV9WkTwdiyU/0.jpg)](https://youtu.be/PV9WkTwdiyU)

*Spanish speech → English SRT output in under 30 seconds*

---

## Architecture

```text
Input File
  ↓
ffmpeg preprocessing
  ↓
whisper.cpp inference
  ↓
optional pandoc conversion
  ↓
versioned delivery + logging
```

---

## The Problem

Manual transcription is slow, expensive, and breaks down entirely when the source language isn't English. Cloud-based transcription APIs charge per minute and require uploading sensitive audio to third-party servers.

This pipeline runs entirely locally using [whisper.cpp](https://github.com/ggerganov/whisper.cpp) — OpenAI's Whisper model compiled for CPU — with no API dependency and no data leaving your machine.

---

## What It Does

- Accepts any common audio or video format (`.mp3`, `.wav`, `.m4a`, `.mp4`, `.mov`, and more)
- Converts input to the format required by Whisper via ffmpeg
- Supports optional audio trimming before processing
- Transcribes in the source language or translates directly to English
- Outputs `.txt`, `.srt` (timestamped), or `.docx`
- Delivers named, versioned output files directly to Desktop
- Logs every job automatically for order tracking

Supports over 99 languages. For a full list of supported language codes, see the [OpenAI Whisper GitHub repository](https://github.com/openai/whisper/blob/main/whisper/tokenizer.py).

---

## Tech Stack

| Tool | Role |
|------|------|
| Python 3 | Pipeline orchestration and file management |
| [whisper.cpp](https://github.com/ggerganov/whisper.cpp) | Local speech recognition (CPU-optimised) |
| ffmpeg | Audio conversion and optional trimming |
| pandoc | `.txt` → `.docx` conversion |

All dependencies installed via [Homebrew](https://brew.sh/).

---

## Models

| Option | Model | Use Case |
|--------|-------|----------|
| 1 | medium (default) | Best balance of speed and accuracy |
| 2 | small | Fast processing, lower accuracy |
| 3 | large-v3 | Highest accuracy, slow on CPU |

Model files are not included — download from the [whisper.cpp releases](https://github.com/ggerganov/whisper.cpp) and place in `~/whisper_models/`.

---

## Setup

**Prerequisites**
```bash
brew install whisper-cpp ffmpeg pandoc
```

**Download Whisper Models**

Download the required model files from the whisper.cpp releases page, then save them locally in the folder below:

```text
~/whisper_models/
├── ggml-medium.bin
├── ggml-small.bin
└── ggml-large-v3.bin
```

Model files are not included in this repository due to size.

**Required folder structure**
```bash
mkdir -p ~/service_root/{inbox,processing,logs} ~/whisper_models
```

---

## Usage

```bash
python3 transcribe.py
```

The script walks you through each step interactively:

1. Locate your input file on Desktop
2. Optional trim (start/end timestamps)
3. Choose model
4. Set language (auto-detect or specify ISO 639-1 code)
5. Enable translation to English (optional)
6. Choose output format
7. Confirm and run

Output is delivered to Desktop with a descriptive filename, e.g.:
```
speech_translated_en_es.srt
interview_transcript.txt
```

---

## Output Example

```
1
00:00:00,000 --> 00:00:04,000
This is the first segment of the translated transcript.

2
00:00:04,000 --> 00:00:08,500
Each segment is timestamped and ready for use.
```

---

## Notes

- Original input file is never deleted — the pipeline works on a copy
- Interrupted runs can be resumed from the processing folder
- Output files are versioned (`_v2`, `_v3`) to prevent overwrites
- Every job is logged to `~/service_root/logs/orders.log`
