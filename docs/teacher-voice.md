# Teacher voice (Steven A. Starphase) — setup on phillmyeol

Everything runs on **phillmyeol** next to Ollama. The GPU worker calls a
local GPT-SoVITS server and writes finished MP3s into Postgres; nothing new
is exposed to the network. Until this is done, the Teacher tab works in
reading mode automatically.

## 1. Prerequisites

```powershell
winget install Gyan.FFmpeg        # audio encode/probe (worker uses ffmpeg/ffprobe)
```

## 2. Install GPT-SoVITS v2

```powershell
git clone https://github.com/RVC-Boss/GPT-SoVITS C:\GPT-SoVITS
cd C:\GPT-SoVITS
# use its own environment — do NOT share the manabi worker's uv env
conda create -n gptsovits python=3.10 -y
conda activate gptsovits
pip install -r requirements.txt
# download pretrained v2 weights per the repo README (GPT-SoVITS-v2 bundle)
```

## 3. Reference clips (you supply these)

The clone is only as good as the reference. Spec:

- **1–2 minutes total** of Steven A. Starphase (J. Michael Tatum) from the
  Blood Blockade Battlefront EN dub — dialogue only, calm delivery scenes.
- Clean audio: no music/SFX underneath. Use **UVR5** (bundled in GPT-SoVITS
  WebUI, "UVR5" tab) to strip background if needed.
- From the cleaned audio, cut ONE **3–10 second** clip with a complete,
  clearly spoken sentence → save as `C:\manabi-voices\steven_ref.wav`
  (44.1kHz wav). Write down its **exact transcript** word for word.
- Keep the rest of the cleaned audio for optional fine-tuning.

**Optional fine-tune (better likeness, ~10–30 min on the 5090):** run the
GPT-SoVITS WebUI training pipeline (slice → ASR → SoVITS train → GPT train)
on the full 1–2 min set, then point the api server at the trained weights.
Zero-shot with just the reference clip is already good; fine-tuning closes
most of the remaining gap.

## 4. Serve the TTS API (localhost only)

```powershell
conda activate gptsovits
python api_v2.py -a 127.0.0.1 -p 9880
```

As a service:

```powershell
nssm install ManabiTTS "C:\path\to\conda-env\python.exe" "C:\GPT-SoVITS\api_v2.py -a 127.0.0.1 -p 9880"
nssm set ManabiTTS AppDirectory "C:\GPT-SoVITS"
nssm start ManabiTTS
```

## 5. Worker .env (on the machine running `manabi_ai.worker`)

```ini
TTS_URL=http://127.0.0.1:9880
TTS_VOICE=steven
TTS_REF_AUDIO=C:\manabi-voices\steven_ref.wav
TTS_REF_TEXT=the exact transcript of the reference clip
```

Restart the worker. Its heartbeat now advertises `tts: true` → the Teacher
tab switches from reading mode to voiced lectures, chat replies get a
"Play as Steven" button, and new lectures auto-queue audio synthesis.

## 6. Database grants (if the worker uses the manabi_gpu role)

After migrations 0015/0016, re-grant on the new tables:

```sql
GRANT SELECT, INSERT, UPDATE, DELETE ON lecture_audio, speech_clips,
  lecture_checkpoint_results TO manabi_gpu;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO manabi_gpu;
```

## 7. VRAM notes

SoVITS ≈ 4 GB. gpt-oss:20b (13 GB) + SoVITS fits easily; qwen3.5:27b
(17 GB) + SoVITS ≈ 21 GB also fits. Generation and synthesis run as
sequential queue jobs, so contention is brief. If an OOM ever appears,
check `nvidia-smi`, lower Ollama keep_alive, or restart ManabiTTS.

Personal-use note: the cloned voice is for your own single-user studying.
