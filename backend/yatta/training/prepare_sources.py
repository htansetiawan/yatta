"""Studio: normalize one or more uploaded recordings to 512x512 at 25 fps and join them (no GPU).

Reads a sources JSON ({"sources": [{"path", "sha256", "video_filter"}]}) and writes an identity
directory with video.mp4, aud.wav, ori_imgs/ and preparation.json. Copied from
experiments/005-henry-avatar-v3/prepare.py (same normalization and join rules).
"""

import argparse
import datetime
import hashlib
import json
import subprocess
from pathlib import Path

FPS = 25
RATE = 16000


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def count_frames(video):
    output = subprocess.check_output(
        ["ffprobe", "-v", "error", "-count_packets", "-select_streams", "v:0",
         "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(video)],
        text=True,
    )
    return int(output.strip())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    config = json.loads(args.sources.read_text())
    for source in config["sources"]:
        if sha256(Path(source["path"])) != source["sha256"]:
            parser.error(f"{source['path']} differs from the inspected recording")
    output.mkdir(parents=True, exist_ok=False)
    segments_dir = output / "segments"
    segments_dir.mkdir()
    commands = []

    def run(arguments):
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-n"] + arguments
        commands.append(command)
        subprocess.run(command, check=True)

    segments = []
    for index, source in enumerate(config["sources"]):
        video = segments_dir / f"{index}.mp4"
        run(["-threads", "4", "-i", source["path"], "-map", "0:v:0", "-an", "-vf", source["video_filter"],
             "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p", "-threads", "4", str(video)])
        frames = count_frames(video)
        # Pad or trim the audio to exactly frames / FPS so later segments stay aligned after the join.
        # Resample inside the filter chain first: atrim counts samples at the rate it receives.
        audio = segments_dir / f"{index}.wav"
        samples = frames * RATE // FPS
        run(["-i", source["path"], "-vn", "-ac", "1",
             "-af", f"aresample={RATE},apad,atrim=end_sample={samples}", "-ar", str(RATE), "-c:a", "pcm_s16le", str(audio)])
        written = float(subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(audio)], text=True))
        if abs(written - samples / RATE) > 0.01:
            raise SystemExit(f"{audio}: {written} s of audio, expected {samples / RATE} s")
        segments.append({"source": source["path"], "frames": frames, "first_frame": sum(s["frames"] for s in segments)})

    lists = {}
    for kind in ("mp4", "wav"):
        lists[kind] = segments_dir / f"{kind}.txt"
        lists[kind].write_text("".join(f"file '{segments_dir / f'{i}.{kind}'}'\n" for i in range(len(segments))))
    joined = segments_dir / "joined.mp4"
    run(["-f", "concat", "-safe", "0", "-i", str(lists["mp4"]), "-c", "copy", str(joined)])
    run(["-f", "concat", "-safe", "0", "-i", str(lists["wav"]), "-c", "copy", str(output / "aud.wav")])
    video = output / "video.mp4"
    run(["-i", str(joined), "-i", str(output / "aud.wav"), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
         "-c:a", "aac", "-movflags", "+faststart", str(video)])
    frames = output / "ori_imgs"
    frames.mkdir()
    run(["-i", str(video), "-q:v", "1", "-start_number", "0", str(frames / "%d.jpg")])
    probe = json.loads(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video)], text=True))
    manifest = {
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "configuration": config,
        "segments": segments,
        "commands": commands,
        "video_sha256": sha256(video),
        "audio_sha256": sha256(output / "aud.wav"),
        "frame_count": len(list(frames.glob("*.jpg"))),
        "probe": probe,
        "status": "normalized; landmarks, parsing, tracking, AU45 and DeepSpeech still required",
    }
    (output / "preparation.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(output), "segments": segments, "frame_count": manifest["frame_count"]}, indent=2))


if __name__ == "__main__":
    main()
