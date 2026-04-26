#!/usr/bin/env python3
"""Audit alignment between kinetic-typography beats in a Remotion .tsx file
and the actual narration timing recorded in podcast_audio.srt.

Why this exists
---------------
Beat scheduling in kinetic-typography videos works best when each beat's
`startSec` is sourced from the SRT timestamps (where the narrator actually
says the corresponding words). Estimating with relative weights — even good
ones — drifts by 2-5 seconds per section, which is enough to make the visible
text lag the audio by a full punch line.

This script reads the beat data from your video component, joins it with the
SRT, and prints a side-by-side report showing what's on screen vs what the
narrator is saying at each beat. Flags any beat where the time gap to the
nearest matching SRT entry exceeds a threshold.

Usage
-----
  python3 audit_beat_sync.py <video.tsx> <timing.json> [<podcast_audio.srt>]

If the SRT path is omitted, it's resolved from the timing.json directory.

Beat data format expected in the .tsx file:
  - Top-level const arrays named like  HERO_BEATS / ENTRY_CHEAP_BEATS / ...
  - Each beat is a JS object literal with  startSec: <number>, lines: [...]
  - Section ↔ beat-array mapping comes from SECTION_CONFIG (a top-level const
    object literal), with `name` matching the section name in timing.json.

If your video uses different conventions, adapt the regexes near the top.
"""
from __future__ import annotations
import sys
import re
import json
import os


# Regex helpers -------------------------------------------------------------

# Match: const HERO_BEATS: Beat[] = [ ... ]
_BEATS_CONST = re.compile(
    r'const\s+([A-Z][A-Z0-9_]*_BEATS)\s*[:=][^=]*=\s*\[(.*?)\n\]\s*$',
    re.DOTALL | re.MULTILINE)

# Match a single beat object: { ... startSec: 1.23 ... lines: [ ... ] ... }
_BEAT_OBJECT = re.compile(
    r'\{\s*([^{}]*?startSec\s*:\s*[\d.]+[^{}]*?lines\s*:\s*\[[^\]]*?\][^{}]*?)\}',
    re.DOTALL)

# Match SECTION_CONFIG mapping: { hero: { beats: HERO_BEATS, ... }, ... }
_SECTION_CONFIG = re.compile(
    r'const\s+SECTION_CONFIG[^=]*=\s*\{(.*?)\n\}\s*$',
    re.DOTALL | re.MULTILINE)

_CONFIG_ENTRY = re.compile(
    r'(\w+)\s*:\s*\{\s*beats\s*:\s*([A-Z][A-Z0-9_]*_BEATS)',
    re.DOTALL)


def parse_beats(tsx_text: str):
    """Return {name: BEATS_NAME} and {BEATS_NAME: [(startSec, summary), ...]}."""
    name_to_beats = {}
    beats_arrays = {}

    for m in _BEATS_CONST.finditer(tsx_text):
        beats_name = m.group(1)
        body = m.group(2)
        items = []
        for bm in _BEAT_OBJECT.finditer(body):
            obj_body = bm.group(1)
            start = re.search(r'startSec\s*:\s*([\d.]+)', obj_body)
            if not start:
                continue
            start_sec = float(start.group(1))
            # Extract human-readable summary of beat lines
            lines = re.findall(r"t\s*:\s*['\"](.*?)['\"]", obj_body)
            summary = ' / '.join(lines)
            items.append((start_sec, summary))
        beats_arrays[beats_name] = items

    cm = _SECTION_CONFIG.search(tsx_text)
    if cm:
        for em in _CONFIG_ENTRY.finditer(cm.group(1)):
            name_to_beats[em.group(1)] = em.group(2)

    return name_to_beats, beats_arrays


# SRT helpers ---------------------------------------------------------------

_SRT_BLOCK = re.compile(
    r'\d+\n(\d+:\d+:\d+),(\d+)\s*-->\s*(\d+:\d+:\d+),(\d+)\n(.+?)(?=\n\n|\Z)',
    re.DOTALL)


def parse_srt(srt_text: str):
    """Return list of (start_sec, end_sec, text) tuples."""
    out = []
    for m in _SRT_BLOCK.finditer(srt_text):
        h, mn, s = m.group(1).split(':')
        ms = m.group(2)
        start = int(h) * 3600 + int(mn) * 60 + int(s) + int(ms) / 1000.0
        h2, mn2, s2 = m.group(3).split(':')
        end = int(h2) * 3600 + int(mn2) * 60 + int(s2) + int(m.group(4)) / 1000.0
        text = m.group(5).strip().replace('\n', ' ')
        out.append((start, end, text))
    return out


def srt_at(subs, sec, window=0.5):
    """Return the SRT text active at given seconds (with small lookback window)."""
    cur = ''
    for st, en, txt in subs:
        if st <= sec + window:
            cur = txt
        else:
            break
    return cur


def srt_overlap(subs, range_start, range_end):
    """Return all SRT entries overlapping the given range, as concatenated text."""
    parts = []
    for st, en, txt in subs:
        if en <= range_start or st >= range_end:
            continue
        parts.append(txt)
    return ' / '.join(parts)


# Main ----------------------------------------------------------------------

def audit(tsx_path, timing_path, srt_path, drift_warn=1.5):
    tsx_text = open(tsx_path, 'r', encoding='utf-8').read()
    timing = json.loads(open(timing_path, 'r', encoding='utf-8').read())
    srt_text = open(srt_path, 'r', encoding='utf-8').read()
    subs = parse_srt(srt_text)

    name_to_beats, beats_arrays = parse_beats(tsx_text)

    if not name_to_beats:
        print("No SECTION_CONFIG entries with `beats:` found in", tsx_path, file=sys.stderr)
        sys.exit(1)

    # Header
    print(f"\nAudit: {os.path.basename(tsx_path)}")
    print(f"  timing.json: {timing['total_duration']:.2f}s, {len(timing['sections'])} sections")
    print(f"  SRT: {len(subs)} subtitle entries")
    print('=' * 100)

    issues = 0
    for sec in timing['sections']:
        name = sec['name']
        beats_name = name_to_beats.get(name)
        if not beats_name:
            print(f"\n[{name}] no beats array mapped (skipped)")
            continue
        items = beats_arrays.get(beats_name, [])
        if not items:
            print(f"\n[{name}] beats array '{beats_name}' empty or unparseable")
            continue
        sec_start = sec['start_time']
        sec_end = sec['start_time'] + sec['duration']
        print(f"\n[{name}]  {sec_start:.2f}-{sec_end:.2f}s  ({len(items)} beats)")
        print(f"  {'BEAT-START':>10}  {'SHOWN':<32}  {'NARRATION (overlap)':<60}")
        items_sorted = sorted(items, key=lambda x: x[0])
        for i, (start_sec, shown) in enumerate(items_sorted):
            abs_start = sec_start + start_sec
            next_start = sec_start + items_sorted[i + 1][0] if i + 1 < len(items_sorted) else sec_end
            narration = srt_overlap(subs, abs_start, next_start)
            shown_short = shown[:30] + '..' if len(shown) > 32 else shown
            narr_short = narration[:58] + '..' if len(narration) > 60 else narration
            flag = ''
            # Heuristic warning: beat starts too far from any SRT entry start
            nearest = min((abs(s - abs_start) for s, _, _ in subs), default=99)
            if nearest > drift_warn:
                flag = f' ⚠ drift {nearest:.1f}s'
                issues += 1
            print(f"  {abs_start:6.2f}s+0  {shown_short:<32}  {narr_short:<60}{flag}")

    print('\n' + '=' * 100)
    if issues:
        print(f"⚠️  {issues} beats more than {drift_warn}s away from nearest SRT boundary.")
        print("   Consider adjusting their startSec to match a nearby SRT entry start.")
    else:
        print("✅ All beats land within {:.1f}s of an SRT boundary.".format(drift_warn))
    return issues


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    tsx = sys.argv[1]
    timing = sys.argv[2]
    srt = sys.argv[3] if len(sys.argv) > 3 else os.path.join(os.path.dirname(timing), 'podcast_audio.srt')
    if not all(os.path.exists(p) for p in (tsx, timing, srt)):
        for p in (tsx, timing, srt):
            if not os.path.exists(p):
                print(f"Not found: {p}", file=sys.stderr)
        sys.exit(1)
    issues = audit(tsx, timing, srt)
    sys.exit(1 if issues else 0)


if __name__ == '__main__':
    main()
