# ThroneTest — Throne and Liberty build data for Claude

A small Python app that collects **all Throne and Liberty data from [questlog.gg](https://questlog.gg/throne-and-liberty)**
and turns it into a **knowledge pack** (Markdown files) that you can upload to a Claude.ai Project.
Claude can then read the game data and use it to design and review strong builds.

Only the Throne and Liberty part of questlog.gg is collected. No other games are touched.

## What it collects

| Source on questlog.gg | What you get |
|---|---|
| 25 databases (items, item sets, skills, skill traits, weapon mastery, potentials, lithographs, polymorphs, amitoi, achievements, codex, contracts, recipes, cooking, dungeons, guild/solo dungeons, towers, events, NPCs/bosses, occupations, resources) | every entry, plus the full record for build-relevant entries |
| Character/skill builder data | all equipment with stats, traits, heroic effects, potentials, resonance and skill cores; runes and rune synergies; attribute point bonuses; all skills and specializations |
| Stat dictionary | in-game names, units and scaling for 287 stats |
| Community builds | the most-liked public character builds for each of the 45 weapon combinations, with gear, runes, traits, skill loadouts and weapon mastery nodes |
| Guides and patch notes | questlog's guides and patch notes, including the full text |

questlog.gg's search stops at 1,000 results per query, so the scraper splits big lists (items, NPCs,
contracts, achievements) by grade, date added and category until it has every entry.

## Quick start

You need Python 3.10 or newer. Nothing else needs installing (the app only uses the standard library).

```bash
# 1. Download everything (roughly 30–40 minutes at the default polite rate)
python -m questlog_tl scrape

# 2. Build the Claude knowledge pack
python -m questlog_tl export

# or both in one go
python -m questlog_tl all
```

The results go in `data/`:

```
data/raw/          raw JSON exactly as questlog.gg returns it (~100 MB)
data/knowledge/
  00_START_HERE.md  what is in the pack and how Claude should use it
  core/             build data: stats, gear, sets, runes, skills, mastery, potentials, guides, patch notes
  community/        most-liked public builds for each of the 45 weapon combos
  extra/            every other database (NPCs, contracts, achievements, codex, recipes, item index…)
```

If a run is interrupted, run the same command again. Records you already have are skipped.
Add `--refresh` to download them again, for example after a game patch.

### Useful options

```bash
python -m questlog_tl scrape --details all          # full record for every entity (~30k requests)
python -m questlog_tl scrape --datasets items skill-sets
python -m questlog_tl scrape --build-pages 3 --min-likes 5   # more community builds per combo
python -m questlog_tl scrape --no-community
python -m questlog_tl scrape --delay 0.5 --workers 2        # be gentler on the site
python -m questlog_tl export --min-grade 41                 # only Epic+ gear in the gear files
python -m questlog_tl export --max-builds 2                 # fewer gear sets per community build
python -m questlog_tl --help
```

## Using it with Claude.ai

1. On claude.ai, create a **Project**, for example "Throne and Liberty builds".
2. Open **Project knowledge** and upload `data/knowledge/00_START_HERE.md` and every file in
   `data/knowledge/core/`. Then add `community/community_00_overview.md` and the `community/` files for
   the weapon combos you play. Add files from `extra/` only if you also want general game answers.
3. Paste this into the Project's **custom instructions**:

   > You are a Throne and Liberty theorycrafter. Use the uploaded questlog.gg knowledge pack as the source of
   > truth for items, stats, skills, specializations, runes, set bonuses and community builds. Start from
   > 00_START_HERE.md. When you recommend a build, give the weapon combo, attribute points, every gear slot
   > (item, traits, runes, potential, resonance), skills with specializations and weapon mastery nodes, and
   > explain why each choice fits the goal. Say which file each number comes from, and point out anything
   > that recent patch notes may have changed.

4. Ask things like:
   - "Build me a PvE boss DPS Staff/Wand with Heroic gear. What should I trait on each piece?"
   - "Compare the three most-liked Sword/Dagger tank builds. What do they agree on?"
   - "I have these items: … What's the best upgrade path for small-scale PvP?"

Refresh the data after each game patch: run `python -m questlog_tl all` again, then replace the files in
the Project.

## Running the tests

```bash
python -m unittest discover -s tests
```

## Notes

- Requests are throttled (4 per second by default, with retries and backoff) and identify themselves with a
  descriptive User-Agent. Please keep the defaults or go slower.
- The data belongs to questlog.gg and its community. The knowledge pack is for your personal use with
  Claude, so please don't republish it. `data/` is git-ignored so it never ends up in this public repository.
- questlog.gg has no official API. If the site changes its internal endpoints, the scraper may need updating.
  They are listed in `questlog_tl/datasets.py`.
