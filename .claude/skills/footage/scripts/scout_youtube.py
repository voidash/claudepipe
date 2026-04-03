"""
YouTube Scout Pipeline — cheap screening before full clip downloads.

Downloads audio + storyboard sprites (~5MB per video), transcribes locally
with Whisper, and outputs timestamped moments for surgical extraction.

Usage:
    python3 scout_youtube.py <project_root> --query "search terms" [--max-results 10] [--lang ne]
    python3 scout_youtube.py <project_root> --video-id VIDEO_ID [--lang ne]
    python3 scout_youtube.py <project_root> --video-ids-file candidates.txt [--lang ne]

Output:
    <project_root>/tmp/scout/<video_id>/
        metadata.json       — yt-dlp dump
        audio.wav            — extracted audio
        storyboard.jpg       — sprite sheet
        transcript.json      — Whisper word-level timestamps
        frames/              — extracted storyboard frames (optional)
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

YT_DLP_FLAGS = ["--js-runtimes", "node", "--remote-components", "ejs:github"]


def run(cmd: list[str], capture: bool = True, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run a command, raise on failure."""
    result = subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        timeout=timeout,
    )
    return result


def search_videos(query: str, max_results: int = 10) -> list[dict]:
    """Search YouTube and return video metadata."""
    cmd = [
        "yt-dlp", *YT_DLP_FLAGS,
        "--dump-json", "--flat-playlist",
        f"ytsearch{max_results}:{query}",
    ]
    result = run(cmd, timeout=60)
    videos = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        try:
            data = json.loads(line)
            videos.append({
                "id": data.get("id", data.get("url", "")),
                "title": data.get("title", ""),
                "channel": data.get("channel", data.get("uploader", "")),
                "duration": data.get("duration"),
                "view_count": data.get("view_count"),
                "url": f"https://www.youtube.com/watch?v={data.get('id', data.get('url', ''))}",
            })
        except json.JSONDecodeError:
            continue
    return videos


def scout_video(video_id: str, scout_dir: Path, lang: str = "ne") -> dict:
    """Download audio + storyboard for a single video."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    vid_dir = scout_dir / video_id
    vid_dir.mkdir(parents=True, exist_ok=True)

    result = {"video_id": video_id, "dir": str(vid_dir), "steps": {}}

    # 1. Metadata
    meta_path = vid_dir / "metadata.json"
    if not meta_path.exists():
        cmd = ["yt-dlp", *YT_DLP_FLAGS, "--dump-json", "--skip-download", url]
        proc = run(cmd, timeout=30)
        if proc.returncode == 0 and proc.stdout.strip():
            meta_path.write_text(proc.stdout)
            result["steps"]["metadata"] = "ok"
        else:
            result["steps"]["metadata"] = f"failed: {proc.stderr[:200]}"
    else:
        result["steps"]["metadata"] = "cached"

    # 2. Audio extraction
    audio_path = vid_dir / "audio.wav"
    if not audio_path.exists():
        cmd = [
            "yt-dlp", *YT_DLP_FLAGS,
            "-f", "bestaudio",
            "-x", "--audio-format", "wav", "--audio-quality", "5",
            "-o", str(vid_dir / "audio.%(ext)s"),
            url,
        ]
        proc = run(cmd, timeout=300)
        # yt-dlp might output as .wav directly or need conversion
        if proc.returncode == 0:
            # Check for any audio file
            for ext in ["wav", "m4a", "opus", "webm"]:
                candidate = vid_dir / f"audio.{ext}"
                if candidate.exists() and candidate != audio_path:
                    # Convert to wav
                    subprocess.run(
                        ["ffmpeg", "-y", "-i", str(candidate), "-ar", "16000", "-ac", "1", str(audio_path)],
                        capture_output=True, timeout=120,
                    )
                    candidate.unlink()
                    break
            result["steps"]["audio"] = "ok" if audio_path.exists() else "conversion_failed"
        else:
            result["steps"]["audio"] = f"failed: {proc.stderr[:200]}"
    else:
        result["steps"]["audio"] = "cached"

    # 3. Storyboard sprites
    sb_path = vid_dir / "storyboard.jpg"
    if not sb_path.exists():
        # Try sb2 first (medium res), fall back to sb1, sb0
        for sb_fmt in ["sb2", "sb1", "sb0"]:
            cmd = [
                "yt-dlp", *YT_DLP_FLAGS,
                "-f", sb_fmt,
                "-o", str(vid_dir / "storyboard.%(ext)s"),
                url,
            ]
            proc = run(cmd, timeout=60)
            # Check if any storyboard file was created
            for f in vid_dir.glob("storyboard.*"):
                if f.suffix in [".jpg", ".jpeg", ".png", ".webp"]:
                    if f.name != "storyboard.jpg":
                        f.rename(sb_path)
                    result["steps"]["storyboard"] = f"ok ({sb_fmt})"
                    break
            if sb_path.exists():
                break
        if not sb_path.exists():
            result["steps"]["storyboard"] = "not_available"
    else:
        result["steps"]["storyboard"] = "cached"

    # 4. Transcription with Whisper
    transcript_path = vid_dir / "transcript.json"
    if not transcript_path.exists() and audio_path.exists():
        cmd = [
            "whisper", str(audio_path),
            "--model", "small",
            "--language", lang,
            "--output_format", "json",
            "--output_dir", str(vid_dir),
        ]
        proc = run(cmd, timeout=600)
        # Whisper outputs as audio.json
        whisper_out = vid_dir / "audio.json"
        if whisper_out.exists():
            whisper_out.rename(transcript_path)
            result["steps"]["transcript"] = "ok"
        else:
            result["steps"]["transcript"] = f"failed: {proc.stderr[:200]}"
    elif transcript_path.exists():
        result["steps"]["transcript"] = "cached"
    else:
        result["steps"]["transcript"] = "skipped (no audio)"

    return result


def extract_clip(video_id: str, start: str, end: str, output_path: str, max_height: int = 1080) -> dict:
    """Download a specific section of a video."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    cmd = [
        "yt-dlp", *YT_DLP_FLAGS,
        "-f", f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]",
        "--download-sections", f"*{start}-{end}",
        "-o", output_path,
        url,
    ]
    proc = run(cmd, timeout=120)

    result = {"video_id": video_id, "start": start, "end": end, "output": output_path}

    if proc.returncode == 0 and os.path.exists(output_path):
        # Verify with ffprobe
        probe = run([
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration:stream=width,height,codec_name",
            "-of", "json", output_path,
        ])
        if probe.returncode == 0:
            result["probe"] = json.loads(probe.stdout)
            result["status"] = "ok"
        else:
            result["status"] = "downloaded_but_probe_failed"
    else:
        result["status"] = f"failed: {proc.stderr[:200]}"

    return result


def verify_clip_frames(clip_path: str, output_dir: str, num_frames: int = 3) -> list[str]:
    """Extract frames from a downloaded clip for visual verification."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    frames = []

    # Get duration
    probe = run([
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "csv=p=0", clip_path,
    ])
    if probe.returncode != 0:
        return frames

    duration = float(probe.stdout.strip())
    timestamps = [duration * i / (num_frames + 1) for i in range(1, num_frames + 1)]

    for i, ts in enumerate(timestamps):
        frame_path = os.path.join(output_dir, f"verify_{i}.jpg")
        run([
            "ffmpeg", "-y", "-ss", str(ts),
            "-i", clip_path,
            "-frames:v", "1", "-q:v", "2",
            frame_path,
        ], timeout=10)
        if os.path.exists(frame_path):
            frames.append(frame_path)

    return frames


def main():
    parser = argparse.ArgumentParser(description="YouTube Scout Pipeline")
    parser.add_argument("project_root", help="Project root directory")
    parser.add_argument("--query", help="Search query")
    parser.add_argument("--video-id", help="Single video ID to scout")
    parser.add_argument("--video-ids-file", help="File with video IDs (one per line)")
    parser.add_argument("--max-results", type=int, default=10, help="Max search results")
    parser.add_argument("--lang", default="ne", help="Language for transcription")
    args = parser.parse_args()

    project_root = Path(args.project_root)
    scout_dir = project_root / "tmp" / "scout"
    scout_dir.mkdir(parents=True, exist_ok=True)

    video_ids = []

    if args.query:
        print(f"Searching: {args.query}")
        videos = search_videos(args.query, args.max_results)
        print(f"Found {len(videos)} videos:")
        for v in videos:
            print(f"  {v['id']} — {v['title']} ({v['duration']}s, {v['view_count']} views)")
        video_ids = [v["id"] for v in videos]

        # Save search results
        search_path = scout_dir / "search_results.json"
        with open(search_path, "w") as f:
            json.dump(videos, f, indent=2)

    elif args.video_id:
        video_ids = [args.video_id]

    elif args.video_ids_file:
        with open(args.video_ids_file) as f:
            video_ids = [line.strip() for line in f if line.strip()]

    if not video_ids:
        print("No videos to scout. Use --query, --video-id, or --video-ids-file")
        sys.exit(1)

    print(f"\nScouting {len(video_ids)} videos...")
    results = []
    for vid_id in video_ids:
        print(f"\n--- Scouting {vid_id} ---")
        result = scout_video(vid_id, scout_dir, lang=args.lang)
        results.append(result)
        for step, status in result["steps"].items():
            print(f"  {step}: {status}")

    # Save scout results
    results_path = scout_dir / "scout_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nScout complete. Results at {results_path}")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
