"""Synthesize speech with the ElevenLabs text-to-speech API for custom-audio renders.

Standard library only, so any Python runs it:

    python scripts/synthesize_elevenlabs.py --list-voices
    python scripts/synthesize_elevenlabs.py --voice VOICE_ID --text "Hello ..." --output speech.wav

The API key comes from ELEVENLABS_API_KEY or, if unset, the file
~/.config/elevenlabs/api_key, or else an env-style ~/.elevenlabs/env
(ELEVENLABS_API_KEY=..., or its only *KEY=... line). Keep it chmod 600 and
out of Git. Requests
``pcm_16000`` output and writes 16 kHz mono 16-bit PCM, the format
``extract_deepspeech.py`` expects, and prints a JSON summary. The text is sent
to ElevenLabs.
"""

import argparse
import json
import os
import urllib.error
import urllib.request
import wave
from pathlib import Path

API = "https://api.elevenlabs.io/v1"
KEY_FILE = Path("~/.config/elevenlabs/api_key").expanduser()
RATE = 16000


ENV_FILE = Path("~/.elevenlabs/env").expanduser()


def parse_env_key(text):
    """API key from env-file text: ELEVENLABS_API_KEY, else the only *KEY= entry, else None."""
    entries = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" in line and not line.startswith("#"):
            name, value = line.split("=", 1)
            entries[name.strip()] = value.strip().strip("'\"")
    if entries.get("ELEVENLABS_API_KEY"):
        return entries["ELEVENLABS_API_KEY"]
    keys = [value for name, value in entries.items() if name.upper().endswith("KEY") and value]
    return keys[0] if len(keys) == 1 else None


def read_api_key(environ=os.environ, key_file=KEY_FILE, env_file=ENV_FILE):
    """Return the API key from the environment, the key file or the env file, or None."""
    key = environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key and key_file.is_file():
        key = key_file.read_text().strip()
    if not key and env_file.is_file():
        key = parse_env_key(env_file.read_text()) or ""
    return key or None


def write_wav(pcm, path, rate=RATE):
    """Write raw little-endian 16-bit mono PCM bytes as a WAV file; returns seconds."""
    if len(pcm) % 2:
        pcm = pcm[:-1]
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm)
    return len(pcm) / 2 / rate


def request(key, url, body=None):
    data = None if body is None else json.dumps(body).encode()
    headers = {"xi-api-key": key, "Content-Type": "application/json"}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=120) as response:
            return response.read()
    except urllib.error.HTTPError as error:  # the body says why (invalid key, missing permission, quota)
        raise SystemExit(f"ElevenLabs HTTP {error.code} for {url.split('?')[0]}: {error.read().decode(errors='replace')[:500]}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list-voices", action="store_true")
    parser.add_argument("--voice", help="ElevenLabs voice ID")
    parser.add_argument("--text")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model", default="eleven_multilingual_v2")
    args = parser.parse_args()
    key = read_api_key()
    if not key:
        parser.error(f"set ELEVENLABS_API_KEY or put the key in {KEY_FILE} or {ENV_FILE}")
    if args.list_voices:
        for voice in json.loads(request(key, f"{API}/voices"))["voices"]:
            labels = voice.get("labels") or {}
            print(json.dumps({"voice_id": voice["voice_id"], "name": voice["name"],
                              "category": voice.get("category"), **labels}))
        return
    if not (args.voice and args.text and args.output):
        parser.error("--voice, --text and --output are required")
    pcm = request(key, f"{API}/text-to-speech/{args.voice}?output_format=pcm_{RATE}",
                  {"text": args.text, "model_id": args.model})
    seconds = write_wav(pcm, args.output)
    print(json.dumps({"voice": args.voice, "model": args.model, "text": args.text,
                      "output": str(args.output), "seconds": round(seconds, 3)}))


if __name__ == "__main__":
    main()
