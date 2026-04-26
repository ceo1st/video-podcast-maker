#!/usr/bin/env python3
"""End-of-pipeline verification + auto-fix for a video project.

Checks that all expected files exist and meet specs, auto-fixes common
omissions (e.g. final_video.mp4 missing because Step 12 skipped subtitles
without aliasing), and prints a clean acceptance report.

Usage:
  python3 verify_output.py videos/<name>/
  python3 verify_output.py videos/<name>/ --strict     # fail on any warning
  python3 verify_output.py videos/<name>/ --no-fix     # report only, do not auto-fix
  python3 verify_output.py videos/<name>/ --format json  # machine-readable envelope

Exit codes:
  0 = all critical files present and valid
  1 = critical missing or invalid
  2 = warnings only (use --strict to treat as failure)
"""
from __future__ import annotations
import os
import sys
import json
import time
import argparse
import shutil
import subprocess
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cli_envelope  # noqa: E402


REQUIRED = [
    'podcast.txt',
    'podcast_audio.wav',
    'podcast_audio.srt',
    'timing.json',
    'output.mp4',
    'final_video.mp4',
    'publish_info.md',
    'thumbnail_remotion_16x9.png',
    'thumbnail_remotion_4x3.png',
]

OPTIONAL = [
    'video_with_bgm.mp4',
    'bgm.mp3',
    'topic_definition.md',
    'topic_research.md',
    'phonemes.json',
]

EXPECTED_RES = (3840, 2160)
THUMB_16x9 = (1920, 1080)
THUMB_4x3 = (1200, 900)


def ffprobe_video(path):
    """Return (width, height, duration, audio_codec) or None on failure."""
    try:
        out = subprocess.check_output([
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_streams', '-show_format', str(path)
        ]).decode()
        data = json.loads(out)
        v = next((s for s in data['streams'] if s['codec_type'] == 'video'), None)
        a = next((s for s in data['streams'] if s['codec_type'] == 'audio'), None)
        if not v:
            return None
        return {
            'width': int(v['width']),
            'height': int(v['height']),
            'duration': float(data['format']['duration']),
            'video_codec': v['codec_name'],
            'audio_codec': a['codec_name'] if a else None,
        }
    except (subprocess.CalledProcessError, KeyError, ValueError):
        return None


def png_size(path):
    """Return (width, height) by parsing PNG header. No external deps."""
    try:
        with open(path, 'rb') as f:
            header = f.read(24)
        if header[:8] != b'\x89PNG\r\n\x1a\n':
            return None
        return (
            int.from_bytes(header[16:20], 'big'),
            int.from_bytes(header[20:24], 'big'),
        )
    except OSError:
        return None


def auto_fix(video_dir):
    """Attempt to recover from known omissions. Returns list of fix descriptions."""
    fixes = []
    final_mp4 = video_dir / 'final_video.mp4'
    bgm_mp4 = video_dir / 'video_with_bgm.mp4'
    output_mp4 = video_dir / 'output.mp4'

    # 1) final_video.mp4 missing but video_with_bgm.mp4 exists → alias (subtitles skipped path)
    if not final_mp4.exists() and bgm_mp4.exists():
        shutil.copy2(bgm_mp4, final_mp4)
        fixes.append(f'Created final_video.mp4 from video_with_bgm.mp4 (subtitles skipped)')

    # 2) final_video.mp4 missing AND no BGM mix → fall back to output.mp4 (no BGM path)
    elif not final_mp4.exists() and output_mp4.exists():
        shutil.copy2(output_mp4, final_mp4)
        fixes.append(f'Created final_video.mp4 from output.mp4 (no BGM mix; consider running Step 11)')

    return fixes


def verify(video_dir, strict=False, do_auto_fix=True):
    """Run all checks. Returns (exit_code, result_dict).

    Prints a human-readable report on stdout. Caller wraps stdout with a
    stderr redirect when emitting a JSON envelope so the report becomes
    diagnostic chatter and only the envelope reaches the agent.

    The returned dict captures every structured fact an agent or
    orchestrator needs to decide "publish or fix":
      video_dir, strict, auto_fix_enabled,
      required_files: {present, missing},
      optional_files_present,
      fixes_applied,
      final_video: {...} | None,
      thumbnails: {filename: {present, size, expected, ok}},
      audio_timing: {wav_duration, timing_duration, drift_seconds, sections_count, ok} | None,
      publish_info: {promo_present, sections_present, sections_missing} | None,
      warnings, errors
    """
    print(f"\n{'='*70}")
    print(f"Verifying: {video_dir}")
    print('='*70)

    result = {
        'video_dir': str(video_dir),
        'strict': strict,
        'auto_fix_enabled': do_auto_fix,
        'required_files': {'present': [], 'missing': []},
        'optional_files_present': [],
        'fixes_applied': [],
        'final_video': None,
        'thumbnails': {},
        'audio_timing': None,
        'publish_info': None,
        'warnings': [],
        'errors': [],
    }

    if not video_dir.is_dir():
        print(f"✗ Directory not found: {video_dir}")
        result['errors'].append(f"Directory not found: {video_dir}")
        return 1, result

    # Auto-fix first so subsequent checks see the patched state
    if do_auto_fix:
        fixes = auto_fix(video_dir)
        result['fixes_applied'] = fixes
        if fixes:
            print("\n--- Auto-fix applied ---")
            for f in fixes:
                print(f"  ⚙ {f}")
    else:
        print("\n--- Auto-fix skipped (--no-fix) ---")

    print("\n--- Required files ---")
    for fname in REQUIRED:
        p = video_dir / fname
        if p.exists():
            size = p.stat().st_size
            size_str = f"{size/1024/1024:.1f} MB" if size > 1024*1024 else f"{size/1024:.1f} KB"
            print(f"  ✓ {fname:<35} {size_str}")
            result['required_files']['present'].append(fname)
        else:
            print(f"  ✗ {fname:<35} MISSING")
            result['required_files']['missing'].append(fname)

    print("\n--- Optional files ---")
    for fname in OPTIONAL:
        p = video_dir / fname
        if p.exists():
            print(f"  ✓ {fname}")
            result['optional_files_present'].append(fname)

    warnings = []
    errors = list(result['required_files']['missing'])

    # Final video specs
    print("\n--- Final video (final_video.mp4) ---")
    final_mp4 = video_dir / 'final_video.mp4'
    if final_mp4.exists():
        info = ffprobe_video(final_mp4)
        if info:
            res_ok = (info['width'], info['height']) == EXPECTED_RES
            res_marker = '✓' if res_ok else '✗'
            print(f"  {res_marker} Resolution: {info['width']}x{info['height']} (expected 3840x2160)")
            if not res_ok:
                errors.append(f"Resolution {info['width']}x{info['height']} != 4K")
            print(f"  ✓ Duration: {info['duration']:.1f}s ({info['duration']/60:.1f} min)")
            print(f"  ✓ Video codec: {info['video_codec']}")
            print(f"  {'✓' if info['audio_codec'] else '✗'} Audio codec: {info['audio_codec'] or 'NONE'}")
            if not info['audio_codec']:
                errors.append("final_video.mp4 has no audio track")
            result['final_video'] = {
                'width': info['width'],
                'height': info['height'],
                'duration_seconds': round(info['duration'], 2),
                'video_codec': info['video_codec'],
                'audio_codec': info['audio_codec'],
                'resolution_ok': res_ok,
            }
        else:
            errors.append("ffprobe failed on final_video.mp4")
            print("  ✗ ffprobe failed")

    # Thumbnail specs
    print("\n--- Thumbnails ---")
    for fname, expected in [('thumbnail_remotion_16x9.png', THUMB_16x9),
                              ('thumbnail_remotion_4x3.png', THUMB_4x3)]:
        p = video_dir / fname
        thumb_record = {'present': False, 'size': None, 'expected': list(expected), 'ok': False}
        if p.exists():
            thumb_record['present'] = True
            sz = png_size(p)
            if sz == expected:
                print(f"  ✓ {fname}: {sz[0]}x{sz[1]}")
                thumb_record['size'] = list(sz)
                thumb_record['ok'] = True
            elif sz:
                print(f"  ⚠ {fname}: {sz[0]}x{sz[1]} (expected {expected[0]}x{expected[1]})")
                warnings.append(f"{fname} size {sz[0]}x{sz[1]} != {expected}")
                thumb_record['size'] = list(sz)
            else:
                print(f"  ✗ {fname}: cannot read PNG header")
                errors.append(f"{fname} unreadable")
        result['thumbnails'][fname] = thumb_record

    # Audio/timing alignment
    print("\n--- Audio / timing alignment ---")
    wav = video_dir / 'podcast_audio.wav'
    timing_path = video_dir / 'timing.json'
    if wav.exists() and timing_path.exists():
        wav_info = ffprobe_video(wav)
        try:
            with open(timing_path) as f:
                timing = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  ✗ timing.json unreadable: {e}")
            errors.append(f"timing.json unreadable: {e}")
            timing = None
        if wav_info and timing is not None:
            wav_dur = wav_info['duration']
            timing_dur = timing.get('total_duration', 0)
            drift = wav_dur - timing_dur
            drift_ok = abs(drift) < 0.5
            if drift_ok:
                print(f"  ✓ WAV {wav_dur:.2f}s ≈ timing.json {timing_dur:.2f}s (drift {drift:+.2f}s)")
            else:
                print(f"  ⚠ WAV {wav_dur:.2f}s vs timing.json {timing_dur:.2f}s (drift {drift:+.2f}s)")
                warnings.append(f"Audio/timing drift {drift:+.2f}s — last sections may truncate")
            sec_count = len(timing.get('sections', []))
            print(f"  ✓ {sec_count} sections registered in timing.json")
            result['audio_timing'] = {
                'wav_duration': round(wav_dur, 2),
                'timing_duration': round(timing_dur, 2),
                'drift_seconds': round(drift, 2),
                'sections_count': sec_count,
                'ok': drift_ok,
            }

    # Publish info sanity
    print("\n--- publish_info.md ---")
    pub = video_dir / 'publish_info.md'
    if pub.exists():
        text = pub.read_text(encoding='utf-8')
        promo = 'github.com/Agents365-ai/video-podcast-maker'
        promo_present = promo in text
        if promo_present:
            print(f"  ✓ Promo line present")
        else:
            print(f"  ⚠ Promo line missing — first description line should reference {promo}")
            warnings.append("publish_info.md missing required promo line")
        sections_required = ('## 标题', '## 标签', '## 简介', '## 章节')
        sections_present = []
        sections_missing = []
        for required_section in sections_required:
            if required_section in text:
                print(f"  ✓ {required_section}")
                sections_present.append(required_section)
            else:
                print(f"  ⚠ {required_section} section missing")
                warnings.append(f"publish_info.md missing {required_section}")
                sections_missing.append(required_section)
        result['publish_info'] = {
            'promo_present': promo_present,
            'sections_present': sections_present,
            'sections_missing': sections_missing,
        }

    result['warnings'] = warnings
    result['errors'] = errors

    # Summary
    print(f"\n{'='*70}")
    if errors:
        print(f"❌ FAILED  {len(errors)} critical issue(s):")
        for e in errors:
            print(f"   - {e}")
        return 1, result
    elif warnings and strict:
        print(f"⚠️  WARNINGS (--strict):  {len(warnings)} issue(s):")
        for w in warnings:
            print(f"   - {w}")
        return 1, result
    elif warnings:
        print(f"✓ ACCEPTED with {len(warnings)} warning(s):")
        for w in warnings:
            print(f"   - {w}")
        print(f"\nReady to publish.")
        return 2, result
    else:
        print(f"✅ ACCEPTED  All required files present and meet specs.")
        print(f"\nReady to publish.")
        return 0, result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('video_dir', help='Path to videos/<name>/')
    parser.add_argument('--strict', action='store_true', help='Fail on any warning')
    parser.add_argument('--no-fix', dest='auto_fix', action='store_false',
                        help='Skip the auto-fix step (preview only). Without this flag, '
                             'verify will create final_video.mp4 from video_with_bgm.mp4 '
                             'or output.mp4 if missing.')
    cli_envelope.add_format_arg(parser)
    args = parser.parse_args()

    started_at = time.time()
    json_mode = cli_envelope.use_json(args)
    if json_mode:
        # Route the prose report off stdout so the JSON envelope is the only
        # payload an agent parses. cli_envelope captured the real stdout at
        # import time, so emit_* still reaches it.
        sys.stdout = sys.stderr
    try:
        try:
            exit_code, result = verify(
                Path(args.video_dir),
                strict=args.strict,
                do_auto_fix=args.auto_fix,
            )
        except Exception as exc:
            # Catch-all: convert unexpected exceptions to a structured envelope
            # in JSON mode so an agent never sees an empty stdout + traceback.
            # In prose mode re-raise so the user gets the full traceback.
            if not json_mode:
                raise
            sys.stdout = sys.__stdout__
            sys.exit(cli_envelope.emit_error(
                args, "internal_error", f"{type(exc).__name__}: {exc}",
                extra={"video_dir": str(args.video_dir)},
                started_at=started_at,
            ))
    finally:
        sys.stdout = sys.__stdout__

    if not cli_envelope.use_json(args):
        sys.exit(exit_code)

    if exit_code in (0, 2):
        # 0 = clean; 2 = warnings only, still publishable. Both emit success.
        # exit_code is preserved out-of-band so existing shell consumers
        # documented in workflow-publish.md keep working.
        sys.exit(cli_envelope.emit_success(
            args, result, started_at=started_at, exit_code=exit_code,
        ))

    # exit_code == 1: critical missing/invalid, OR warnings under --strict
    if result['errors']:
        message = f"{len(result['errors'])} critical issue(s) in {result['video_dir']}"
    else:
        message = f"{len(result['warnings'])} warning(s) treated as errors (--strict)"
    sys.exit(cli_envelope.emit_error(
        args, "validation_failed", message,
        extra={
            'video_dir': result['video_dir'],
            'missing_required': result['required_files']['missing'],
            'errors': result['errors'],
            'warnings': result['warnings'],
            'fixes_applied': result['fixes_applied'],
            'strict': result['strict'],
            'final_video': result['final_video'],
            'thumbnails': result['thumbnails'],
            'audio_timing': result['audio_timing'],
            'publish_info': result['publish_info'],
        },
        started_at=started_at,
    ))


if __name__ == '__main__':
    main()
