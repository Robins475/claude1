#!/usr/bin/env python3
"""
Expressive voiceover with Chatterbox TTS (MIT licence, runs offline on CPU).

Clones the timbre of a reference clip (assets/voice_ref.wav = the Kokoro
"am_fenrir" voice) and speaks with a natural, hyped-up delivery.

Runs in its own venv because Chatterbox pins torch:
    python3 -m venv .venv-tts
    .venv-tts/bin/pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cpu
    .venv-tts/bin/pip install chatterbox-tts

Usage: tts_chatterbox.py jobs.json      # [[text, out_wav], ...]  (one model load for all)
"""
import json, os, sys
import torch, torchaudio as ta
from chatterbox.tts import ChatterboxTTS

REF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "voice_ref.wav")
TONES = {  # exaggeration, cfg_weight
    "natural": (0.5, 0.5),
    "expressive": (0.7, 0.35),
    "hype": (0.9, 0.3),
}

jobs = json.load(open(sys.argv[1]))
tone = os.environ.get("TONE", "hype")
ex, cfg = TONES[tone]
model = ChatterboxTTS.from_pretrained(device="cuda" if torch.cuda.is_available() else "cpu")
for text, out in jobs:
    torch.manual_seed(7)
    wav = model.generate(text, audio_prompt_path=REF, exaggeration=ex, cfg_weight=cfg, temperature=0.8)
    ta.save(out, wav, model.sr)
    print(f"{out}: {wav.shape[1] / model.sr:.1f}s", flush=True)
