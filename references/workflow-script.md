# Video Podcast Maker — Workflow Phase 1: Scripting

> **When to load:** Load at workflow start, or when the user asks about research, topic definition, or narration script writing.
>
> **Covers:** Pre-workflow (optional design reference extraction) → Startup (load user preferences) → Steps 1-4 (topic → research → sections → script).
>
> **Next phase:** See `workflow-production.md` for Steps 5-11 (media, TTS, Remotion, render, BGM).

---

## Pre-workflow: Design Reference (Optional)

When the user provides a reference video/image with their video creation request:

1. Run extraction: `python3 scripts/learn_design.py <input>`
2. Read extracted frames using your agent's image/file inspection capability
3. Analyze against design-guide.md component vocabulary
4. Present design analysis report to user
5. User confirms/adjusts extracted attributes
6. Apply as session overrides for this video (do NOT save to library unless user asks)

---

## Startup: Load User Preferences

**Agent behavior:** Auto-execute before Step 1, no user interaction needed.

1. Resolve `SKILL_DIR` to the directory containing this skill's files
2. Check if `user_prefs.json` exists in `${SKILL_DIR}`
3. If not, copy from `${SKILL_DIR}/user_prefs.template.json`
3. Read preferences, **check version and migrate if needed**, then apply in subsequent steps

```bash
SKILL_DIR="${SKILL_DIR:-${CLAUDE_SKILL_DIR}}"
PREFS_FILE="$SKILL_DIR/user_prefs.json"
TEMPLATE_FILE="$SKILL_DIR/user_prefs.template.json"

if [ ! -f "$PREFS_FILE" ]; then
  cp "$TEMPLATE_FILE" "$PREFS_FILE"
  echo "✓ Created default preferences"
fi
```

### Preference Migration

After loading `user_prefs.json`, check the `version` field and migrate if outdated:

| From | To | Migration |
|------|----|-----------|
| `1.0` | `1.1` | Add top-level `topic_patterns`, `style_profiles`, `design_references`, `learning_history` |
| `1.1` | `1.2` | Convert `tts.voice` (string) → `tts.voices` (per-backend object, preserving user's voice for azure/edge); Add `bgm` preferences (volume, track, tracks library) |
| `1.2` | `1.3` | Add `platform: "bilibili"`, `language: "zh-CN"`, `cta`, `subtitle` fields; expand `progressBar` from boolean to `{ enabled: <old_value>, height: 6, fontSize: 18, activeColor: "auto", position: "bottom" }`; add `content.chapters: true` |

**Migration rules:**
- Preserve all existing user values — never overwrite what the user has customized
- Only add missing fields with defaults from `user_prefs.template.json`
- When migrating `tts.voice` → `tts.voices`: use the old voice value for `azure` and `edge`, use defaults for `doubao` and `cosyvoice`
- v1.3 → v1.4: No structural changes. Platform enum now accepts `"xiaohongshu"`. Update `version` to `"1.4"`.
- v1.4 → v1.5: No structural changes. Platform enum now accepts `"douyin"`. Update `version` to `"1.5"`.
- v1.5 → v1.6: No structural changes. Platform enum now accepts `"weixin-channels"`. Update `version` to `"1.6"`.
- After migration, update `version` to `"1.6"` and save the file
- Print: `"✓ Migrated preferences from v{old} to v1.6"`

4. At Step 1 start, inform user of active preferences (if customized):

```
"Based on your preferences:
 - Platform: [platform] | Language: [language]
 - TTS: [tts.backend] / [tts.voices[backend]]
 - Speech rate: [tts.rate]
 - BGM: [bgm.track] at volume [bgm.volume]
 - Subtitles: [enabled/disabled] | CTA: [cta.type]

Say 'set platform youtube' or 'set language en-US' to change.
Say 'show preferences' to see all details."
```

---

## Step 1: Define Topic Direction

**Auto mode:** Infer all decisions from the user's topic description. Use sensible defaults (audience: general, style: educational intro, tone: professional-casual, duration: medium 3-7min). Save directly to `videos/{name}/topic_definition.md`.

**Interactive mode:** Confirm each item (use `brainstorming` skill if available, otherwise ask directly):
1. **Target audience**: developers / general / students / professionals
2. **Video style**: educational intro / deep analysis / news brief / hands-on tutorial
3. **Content scope**: background / technical principles / usage / comparison
4. **Tone**: serious / casual / fast-paced
5. **Duration**: short (1-3min) / medium (3-7min) / long (7-15min)

Save to `videos/{name}/topic_definition.md`

---

## Step 2: Research Topic

Use your agent's web search and fetch capabilities. Save to `videos/{name}/topic_research.md`.

---

## Step 3: Design Video Sections

Design 5-7 sections:
- Hero/Intro (15-25s)
- Core concepts (30-45s each)
- Demo/Examples (30-60s)
- Comparison/Analysis (30-45s)
- Summary (20-30s)

### Content Density Selection

Assign each section a density tier:

| Tier | Items | Best For |
|------|-------|----------|
| **Impact** | 1 | Hook, hero, CTA, brand moment — largest text |
| **Standard** | 2-3 | Features, comparison, demo |
| **Compact** | 4-6 | Feature grid, ecosystem |
| **Dense** | 6+ | Data tables, detailed comparisons — smallest text |

### Topic Type Detection

> **Planned feature.** Currently, topic-specific styles are applied manually via `user_prefs.json` under `topic_patterns`. Auto-detection from keywords is not yet implemented.

### Title Position

**Auto mode:** Use `top-center` (default).
**Interactive mode:** Ask user: top-center (recommended) / top-left / full-center.

**Rule:** Keep title position consistent within a single video.

---

## Step 4: Write Narration Script

**Preference application:** Adjust script style from `user_prefs.content`:
- `tone: professional` → formal language
- `tone: casual` → conversational, interjections ok
- `verbosity: concise` → 50-80 chars per paragraph
- `verbosity: detailed` → 100-150 chars per paragraph
- `heroOpening` (if set) → use as fixed hero opening line
- `outroClosing` (if set) → use as fixed outro closing line

Create `videos/{name}/podcast.txt` with section markers:

```text
[SECTION:hero]
{heroOpening}（话题引入）...

[SECTION:features]
它有以下功能...

[SECTION:demo]
让我演示一下...

[SECTION:summary]
总结一下，xxx是目前最xxx的xxx。

[SECTION:references]
本期视频参考了官方文档和技术博客。

[SECTION:outro]
{outroClosing}
```

**Numbers MUST use Chinese pronunciation** for correct TTS:

| Type | Wrong | Correct |
|------|-------|---------|
| Integer | 29, 3999 | 二十九，三千九百九十九 |
| Decimal | 1.2, 3.5 | 一点二，三点五 |
| Percentage | 15%, -10% | 百分之十五，负百分之十 |
| Date | 2025-01-15 | 二零二五年一月十五日 |
| Large number | 6144 | 六千一百四十四 |
| English units | 128GB | 一百二十八G |

**Section notes**:
- **hero**: MUST start with `content.heroOpening` if set in user_prefs, followed by the topic hook
- **summary**: Pure content summary, no interaction prompts
- **references** (optional): One sentence about sources
- **outro**: MUST use `content.outroClosing` if set in user_prefs. Fallback: platform-specific CTA
- Empty `[SECTION:xxx]` = silent section

### Script Template Selection

Copy the script template based on `language`:
- `zh-CN` → `${SKILL_DIR}/templates/podcast_zh.txt`
- `en-US` → `${SKILL_DIR}/templates/podcast_en.txt`

### Outro Text by Platform + Language

| Platform | zh-CN | en-US |
|----------|-------|-------|
| bilibili | "一键三连！评论区留言，下期再见！" | "Like, coin, and favorite! Leave a comment, see you next time!" |
| youtube | "点赞订阅转发！评论区留言，下期再见！" | "Like, subscribe, and share! Leave a comment, see you next time!" |
| xiaohongshu | "点赞收藏加关注，评论区见！" | "Like, save & follow! See you in comments!" |
| douyin | "点赞关注，评论区见！" | "Like & follow! See you in comments!" |
| weixin-channels | "点赞关注，转发给朋友！" | "Like, follow & share with friends!" |

### Duration Estimation (Dry Run)

After writing `podcast.txt`, automatically run:

```bash
python3 ${SKILL_DIR}/scripts/generate_tts.py --input videos/{name}/podcast.txt --output-dir videos/{name} --dry-run
```

Report estimated duration. If >12min or <3min, suggest adjustments.
