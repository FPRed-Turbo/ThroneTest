"""Turns ``<data>/raw`` into a Markdown knowledge pack Claude can read.

Output goes to ``<data>/knowledge``. Every file is plain Markdown with game ids
resolved to names and raw stat numbers converted to the values the game shows
(e.g. ``debuff_taken_duration_modifier: -350`` -> ``Debuff Duration -3.5%``).
Upload the folder to a Claude.ai Project (Project knowledge) and start with
``00_START_HERE.md``.
"""

from __future__ import annotations

import html
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .datasets import BY_NAME, CLASS_COMBOS

GRADES = {0: "Misc", 11: "Common", 21: "Uncommon", 31: "Rare", 32: "Rare II", 41: "Epic",
          42: "Epic II", 43: "Epic III", 51: "Heroic", 61: "Artifact", 71: "Ancient"}

GEAR_GROUPS = {
    "weapons": ["sword", "sword2h", "dagger", "bow", "crossbow", "staff", "wand", "spear", "orb", "gauntlet"],
    "armor": ["head", "chest", "cloak", "hands", "legs", "feet"],
    "accessories": ["necklace", "bracelet", "ring", "belt", "earring", "brooch"],
    "artifacts-and-stones": ["attack", "defense", "life", "utility", "boonstone", "riftstone",
                             "talistone1", "talistone2", "talistone3", "talistone4", "gemstone1", "gemstone2",
                             "stellarite", "castle", "other"],
    "consumables": ["hp-recovery", "mana-recovery", "instant-recovery", "sharingfood"],
}

# Keys that are never useful to Claude (images, internal ids, bookkeeping).
NOISE_KEYS = {"icon", "language", "compoundId", "dbType", "db_type", "isDisabled", "auction_house_id",
              "auctionHouseId", "thumbnailUrl", "image", "userId", "userLiked", "imageUrl", "createdAt",
              "updatedAt", "tradeCategory", "maxStackCount", "isDestructable", "isStorable", "nodeNumber",
              "cacheBust", "order", "color"}

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[ \t]+")


def clean_text(value) -> str:
    text = str(value)
    text = re.sub(r"</(p|li|h\d|tr|div)>|<br\s*/?>", "\n", text)
    text = re.sub(r"<li[^>]*>", "- ", text)
    text = html.unescape(TAG_RE.sub("", text))
    lines = [WS_RE.sub(" ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def num(x) -> str:
    if isinstance(x, float):
        x = round(x, 3)
        if x.is_integer():
            x = int(x)
    return f"{x:,}" if isinstance(x, int) and abs(x) >= 10000 else str(x)


def load(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


class Context:
    def __init__(self, raw: Path):
        self.raw = raw
        self.stat_format = load(raw / "builder" / "stat-format.json", {})
        self.names: dict[str, str] = {}
        for f in (raw / "lists").glob("*.json"):
            for r in load(f, []):
                self.names.setdefault(r["id"], r.get("name", r["id"]))
        for name in ("equipment-items", "equipment-runes", "equipment-item-sets"):
            for k, v in (load(raw / "builder" / f"{name}.json", {}) or {}).items():
                self.names[k] = v.get("name", k)
                for skill in (v.get("itemPotential") or {}).get("skills") or []:
                    self.names.setdefault(skill["id"], skill.get("name", skill["id"]))
                for perk in v.get("availablePerks") or []:
                    passive = perk.get("passive") or {}
                    if passive.get("id"):
                        self.names.setdefault(passive["id"], f"{perk.get('name', '').strip()} ({passive.get('name', '')})")
        for name in ("builder-skill-sets", "builder-skill-traits"):
            for v in load(raw / "builder" / f"{name}.json", []) or []:
                self.names[v["id"]] = v.get("name", v["id"])

    def name(self, entity_id) -> str:
        return self.names.get(entity_id, str(entity_id)).strip()

    def stat_name(self, stat_id) -> str:
        if not isinstance(stat_id, str):
            return str(stat_id)
        fmt = self.stat_format.get(stat_id)
        return fmt["name"].strip() if fmt else stat_id

    def stat_value(self, stat_id: str, raw) -> str:
        if not isinstance(raw, (int, float)):
            return str(raw)
        fmt = self.stat_format.get(stat_id)
        if not fmt:
            return num(raw)
        value = raw * fmt.get("multiplier", 1)
        shown = fmt.get("valueFormat", "{0}").strip().replace("{0}", num(value))
        return shown if value < 0 or fmt.get("valueFormat", "").strip().endswith("s") else f"+{shown}"

    def stat(self, stat_id: str, raw) -> str:
        return f"{self.stat_name(stat_id)} {self.stat_value(stat_id, raw)}"

    def is_stat_map(self, d) -> bool:
        return isinstance(d, dict) and d and all(k in self.stat_format for k in d)

    def stats(self, d: dict | None, pick_last: bool = True) -> str:
        """Render {stat_id: value | [per-level values] | {weapon: value}}."""
        if not d:
            return ""
        parts = []
        for k, v in d.items():
            if isinstance(v, list) and v:
                parts.append(self.stat(k, v[-1]) + (f" (max of {len(v)} levels)" if len(v) > 1 else "")
                             if pick_last else f"{self.stat_name(k)} " + "/".join(self.stat_value(k, x) for x in v))
            elif isinstance(v, dict) and "tiers" in v:
                parts.append(f"{self.stat_name(k)} " + "/".join(self.stat_value(k, x) for x in v["tiers"])
                             + (f" (roll weight {v['probability']})" if v.get("probability") is not None else ""))
            elif isinstance(v, dict):
                parts.append(f"{self.stat_name(k)} (" + ", ".join(f"{w} {self.stat_value(k, x)}" for w, x in v.items()) + ")")
            else:
                parts.append(self.stat(k, v))
        return "; ".join(parts)

    # Generic fallback: YAML-ish rendering of any JSON with names/stats resolved.
    def render(self, obj, indent: int = 0, max_list: int = 60) -> list[str]:
        pad = "  " * indent
        out: list[str] = []
        if isinstance(obj, dict):
            if self.is_stat_map(obj):
                return [pad + self.stats(obj)]
            for k, v in obj.items():
                if k in NOISE_KEYS or v in (None, "", [], {}):
                    continue
                if isinstance(v, (dict, list)):
                    if isinstance(v, dict) and self.is_stat_map(v):
                        out.append(f"{pad}{k}: {self.stats(v)}")
                        continue
                    sub = self.render(v, indent + 1, max_list)
                    if sub:
                        out.append(f"{pad}{k}:")
                        out.extend(sub)
                else:
                    out.append(f"{pad}{k}: {self.scalar(k, v)}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                if i >= max_list:
                    out.append(f"{pad}- ... {len(obj) - max_list} more")
                    break
                sub = self.render(v, indent + 1, max_list)
                if not sub:
                    continue
                if isinstance(v, (dict, list)):
                    out.append(f"{pad}- {sub[0].strip()}")
                    out.extend(sub[1:])
                else:
                    out.append(f"{pad}- {sub[0].strip()}")
        else:
            out.append(pad + self.scalar("", obj))
        return out

    def scalar(self, key: str, v) -> str:
        if key in ("grade",) and isinstance(v, int):
            return GRADES.get(v, str(v))
        if key in ("stat_id", "statId") and isinstance(v, str):
            return self.stat_name(v)
        if isinstance(v, str):
            t = clean_text(v)
            return t.replace("\n", " / ")
        return num(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)


class Writer:
    """Collects Markdown sections and writes them, splitting files above ``max_bytes``."""

    def __init__(self, out: Path, max_bytes: int):
        self.out = out
        self.max_bytes = max_bytes
        self.written: list[Path] = []
        out.mkdir(parents=True, exist_ok=True)
        for old in out.glob("**/*.md"):
            old.unlink()

    def write(self, stem: str, title: str, intro: str, sections: list[str], folder: str = "core") -> None:
        if not sections:
            return
        parts, current, size = [], [], 0
        for s in sections:
            b = len(s.encode("utf-8"))
            if current and size + b > self.max_bytes:
                parts.append(current)
                current, size = [], 0
            current.append(s)
            size += b
        parts.append(current)
        for i, chunk in enumerate(parts, 1):
            suffix = f"_part{i}" if len(parts) > 1 else ""
            head = f"# {title}" + (f" (part {i} of {len(parts)})" if len(parts) > 1 else "")
            path = self.out / folder / f"{stem}{suffix}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(head + "\n\n" + intro.strip() + "\n\n" + "\n\n".join(chunk) + "\n", encoding="utf-8")
            self.written.append(path)


# --------------------------------------------------------------------------- sections

def stats_reference(ctx: Context) -> list[str]:
    rows = ["## Stat dictionary", "",
            "| Stat id | In-game name | Shown as | Raw-to-display multiplier | Lower is better |",
            "|---|---|---|---|---|"]
    for k, v in sorted(ctx.stat_format.items(), key=lambda kv: kv[1]["name"]):
        rows.append(f"| `{k}` | {v['name'].strip()} | {v.get('valueFormat', '{0}').strip()} | "
                    f"{v.get('multiplier', 1)} | {'yes' if v.get('invert') else ''} |")
    sections = ["\n".join(rows)]
    desc_lines = ["## What each stat does", ""]
    for k, v in sorted(ctx.stat_format.items(), key=lambda kv: kv[1]["name"]):
        desc = clean_text(v.get("tooltipDescription", "")).replace("\n", " ")
        if desc and not desc.isdigit():
            desc_lines.append(f"- **{v['name'].strip()}** (`{k}`): {desc}")
    sections.append("\n".join(desc_lines))

    attrs = load(ctx.raw / "builder" / "attribute-stats.json", {}) or {}
    names = {"str": "Strength", "dex": "Dexterity", "int": "Wisdom", "per": "Perception", "con": "Fortitude"}
    for attr, levels in attrs.items():
        lines = [f"## Attribute: {ctx.stat_name(attr) if attr in ctx.stat_format else names.get(attr, attr)} (`{attr}`)",
                 "", "Total bonuses granted at each point value (only rows where something changes are listed).", ""]
        prev = None
        for lvl in sorted(levels, key=int):
            cur = levels[lvl]
            if cur != prev:
                lines.append(f"- **{lvl} points:** {ctx.stats(cur)}")
            prev = cur
        sections.append("\n".join(lines))

    mastery = load(ctx.raw / "builder" / "weapon-mastery-levels.json", []) or []
    if mastery:
        sections.append("## Weapon mastery level thresholds\n\n" + "\n".join(
            f"- Level {m['level']}: {num(m['pointThreshold'])} points" for m in mastery))
    return sections


def item_sources(ctx: Context, detail: dict) -> list[str]:
    lines = []
    for key, label in (("itemDroppedFromNpcs", "Dropped by"), ("itemIsOutputOfRecipes", "Crafted via"),
                       ("itemIsContainedInItems", "Found in"), ("itemIsOutputOfLitographs", "From lithograph"),
                       ("itemIsDroppedFromResources", "Gathered from")):
        entries = detail.get(key) or []
        names = []
        for e in entries:
            n = e.get("name") if isinstance(e, dict) else None
            if n and n not in names:
                names.append(clean_text(n))
        if names:
            more = f" (+{len(names) - 12} more)" if len(names) > 12 else ""
            lines.append(f"- {label}: " + ", ".join(names[:12]) + more)
    return lines


def gear_card(ctx: Context, item: dict, detail: dict | None, sets: dict) -> str:
    st = item.get("itemStats") or {}
    lines = [f"### {item['name'].strip()}",
             f"- id `{item['id']}` | {GRADES.get(item.get('grade'), item.get('grade'))} | "
             f"slot/type: {item.get('equipmentType')} | required level {item.get('requiredLevel', 1)}"]
    if item.get("setId"):
        lines.append(f"- Set: {sets.get(item['setId'], {}).get('name', item['setId'])} (`{item['setId']}`)")
    main = st.get("main") or {}
    if main:
        top = max(main, key=int)
        m = main[top] or {}
        bits = []
        for hand in ("mainhand", "offhand"):
            h = m.get(hand)
            if h:
                bits.append(f"{hand} damage {h.get('min')}–{h.get('max')}")
        if m.get("armor"):
            bits.append(ctx.stats(m["armor"]))
        if m.get("shield"):
            bits.append("shield: " + (ctx.stats(m["shield"]) if isinstance(m["shield"], dict) else str(m["shield"])))
        if m.get("extra"):
            bits.append(ctx.stats(m["extra"]))
        label = f"at enchant step {top}" if len(main) > 1 or top != "0" else ""
        lines.append(f"- Base stats {label}: " + "; ".join(b for b in bits if b))
    extra = st.get("extra") or {}
    if extra:
        top = max(extra, key=int)
        lines.append(f"- Bonus stats: {ctx.stats(extra[top])}")
    if st.get("traits"):
        lines.append(f"- Trait options (value at max trait level): {ctx.stats(st['traits'])}")
    if st.get("uniqueTraits"):
        lines.append(f"- Unique trait options: {ctx.stats(st['uniqueTraits'])}")
    if st.get("resonance"):
        res = st["resonance"]
        lines.append("- Resonance options (value per tier 1-4): "
                     + (ctx.stats(res) if ctx.is_stat_map(res) else json.dumps(res)))
    if st.get("artifact"):
        lines.append("- Artifact effects:\n" + "\n".join("  " + l for l in ctx.render(st["artifact"])))
    seen_pools = {}
    for g in (1, 2, 3):
        pool = st.get(f"random_stat_group_{g}")
        if not pool:
            continue
        opts = ", ".join(f"{ctx.stat_name(p['stat_id'])} {ctx.stat_value(p['stat_id'], p['levels'][-1] if p.get('levels') else p.get('base_value'))}"
                         for p in pool)
        if opts in seen_pools:
            lines.append(f"- Random (heroic) effect {g}: same options as effect {seen_pools[opts]}")
        else:
            seen_pools[opts] = g
            lines.append(f"- Random (heroic) effect {g} options (one rolls; max value): {opts}")
    pot = item.get("itemPotential") or {}
    if pot.get("stats"):
        lines.append("- Potential stat options: " + ", ".join(ctx.stat(p["stat_id"], p["value"]) for p in pot["stats"]))
    if pot.get("skills"):
        lines.append(f"- Potential skill options: {len(pot['skills'])} skill-enchant potentials "
                     "(see potential abilities file)")
    for perk in item.get("availablePerks") or []:
        passive = perk.get("passive") or {}
        lines.append(f"- Skill Core option: **{perk.get('name', '').strip()}** — {passive.get('name', '')}: "
                     f"{clean_text(passive.get('text', '')).replace(chr(10), ' ')}")
    if detail:
        if detail.get("description"):
            lines.append(f"- Description: {clean_text(detail['description']).replace(chr(10), ' ')}")
        lines += item_sources(ctx, detail)
    return "\n".join(lines)


def gear_files(ctx: Context, w: Writer, min_grade: int) -> None:
    items = load(ctx.raw / "builder" / "equipment-items.json", {}) or {}
    sets = load(ctx.raw / "builder" / "equipment-item-sets.json", {}) or {}
    by_type = defaultdict(list)
    for it in items.values():
        if it.get("grade", 0) >= min_grade or it.get("equipmentType") in GEAR_GROUPS["consumables"]:
            by_type[it.get("equipmentType")].append(it)
    placed = set()
    for group, types in GEAR_GROUPS.items():
        for t in types:
            placed.add(t)
            rows = sorted(by_type.get(t, []), key=lambda i: (-i.get("grade", 0), i["name"]))
            if not rows:
                continue
            cards = [gear_card(ctx, i, load(ctx.raw / "details" / "items" / f"{i['id']}.json"), sets) for i in rows]
            w.write(f"gear_{group}_{t}", f"Gear — {group} — {t}",
                    f"{len(rows)} items of type `{t}` (grade {GRADES.get(min_grade)} and above), best grade first. "
                    "Values are what the game displays. Base stats are shown at the highest enchant step listed "
                    "by questlog; trait/unique-trait values are at max trait level.", cards)
    leftovers = [i for t, rows in by_type.items() if t not in placed for i in rows]
    if leftovers:
        w.write("gear_other", "Gear — other", "Equipment of types not grouped elsewhere.",
                [gear_card(ctx, i, None, sets) for i in leftovers])

    set_cards = []
    for s in sorted(sets.values(), key=lambda s: (-s.get("grade", 0), s["name"])):
        lines = [f"### {s['name'].strip()} (`{s['id']}`) — {GRADES.get(s.get('grade'), s.get('grade'))}",
                 "- Pieces: " + ", ".join(f"{p['name'].strip()} ({p.get('sub_category')})"
                                          for p in s.get("itemSetMadeOfItems", []))]
        for b in s.get("itemSetBonus", []):
            eff = []
            for bs in b.get("bonus_stat") or []:
                if isinstance(bs, dict) and "stat_id" in bs:
                    eff.append(ctx.stat(bs["stat_id"], bs.get("value")))
                elif isinstance(bs, dict):
                    eff.append(ctx.stats(bs))
            for p in b.get("bonus_passive") or []:
                eff.append(f"{p.get('name', '').strip()}: {clean_text(p.get('text', '')).replace(chr(10), ' ')}")
            lines.append(f"- **{b.get('set_count')}-piece:** " + "; ".join(e for e in eff if e))
        set_cards.append("\n".join(lines))
    w.write("gear_item_sets", "Item set bonuses", f"{len(set_cards)} equipment sets and their bonuses.", set_cards)


def rune_file(ctx: Context, w: Writer) -> None:
    runes = load(ctx.raw / "builder" / "equipment-runes.json", {}) or {}
    syn = load(ctx.raw / "builder" / "rune-synergies.json", {}) or {}
    cards = []
    for r in sorted(runes.values(), key=lambda r: (r["name"], -r.get("grade", 0))):
        st = r.get("itemStats") or {}
        lines = [f"### {r['name'].strip()} — {GRADES.get(r.get('grade'), r.get('grade'))} (`{r['id']}`)"]
        for g in (1, 2, 3):
            pool = st.get(f"random_stat_group_{g}")
            if pool:
                opts = [f"{ctx.stat_name(p['stat_id'])} {ctx.stat_value(p['stat_id'], p['levels'][-1])} "
                        f"at max level {p.get('max_level')} ({p.get('probability')}% roll)" for p in pool]
                lines.append(f"- Stat pool {g}: " + ", ".join(opts))
        cards.append("\n".join(lines))
    syn_lines = ["## Rune synergies", "",
                 "Socketing runes whose types match a combination (in order) grants the synergy bonus."]
    for s in sorted(syn.values(), key=lambda s: (s.get("equipmentCategory", ""), -s.get("grade", 0))):
        syn_lines.append(f"- **{s.get('equipmentCategory')}** {GRADES.get(s.get('grade'))} — "
                         f"{' → '.join(s.get('combination', []))}: {ctx.stats(s.get('stats'))}")
    w.write("runes", "Runes and rune synergies",
            "Rune stat pools with values at max rune level, then synergy bonuses.", ["\n".join(syn_lines)] + cards)


def skill_files(ctx: Context, w: Writer) -> None:
    skills = load(ctx.raw / "builder" / "builder-skill-sets.json", []) or []
    traits = load(ctx.raw / "builder" / "builder-skill-traits.json", []) or []
    traits_by_skill = defaultdict(list)
    for t in traits:
        traits_by_skill[t.get("skillSetId")].append(t)
    by_weapon = defaultdict(list)
    for s in skills:
        by_weapon[s.get("mainCategory")].append(s)
    for weapon, rows in sorted(by_weapon.items(), key=lambda kv: str(kv[0])):
        cards = []
        for s in sorted(rows, key=lambda s: (s.get("skillType", ""), s["name"])):
            detail = load(ctx.raw / "details" / "skill-sets" / f"{s['id']}.json") or {}
            levels = s.get("skillSetLevels") or []
            dlevels = detail.get("skillSetLevels") or []
            lines = [f"### {s['name'].strip()} (`{s['id']}`)",
                     f"- Type: {s.get('skillType')} | category: {s.get('enchantCategory')} | "
                     f"grade: {GRADES.get(s.get('grade'), s.get('grade'))}"
                     + (f" | unlock level {detail['unlockLevel']}" if detail.get("unlockLevel") else "")]
            if dlevels:
                first, last = dlevels[0], dlevels[-1]
                if last.get("cooldown") is not None:
                    lines.append(f"- Cooldown {first.get('cooldown')}s → {last.get('cooldown')}s at max level; "
                                 f"mana {first.get('manaCost')} → {last.get('manaCost')}")
            if levels:
                lines.append(f"- Level 1: {clean_text(levels[0].get('description', '')).replace(chr(10), ' ')}")
                if len(levels) > 1:
                    lines.append(f"- Max level {levels[-1].get('skill_level')}: "
                                 f"{clean_text(levels[-1].get('description', '')).replace(chr(10), ' ')}")
            for t in traits_by_skill.get(s["id"], []):
                tl = t.get("skillTraitLevels") or [{}]
                lines.append(f"  - Specialization **{t.get('rawName') or t['name']}** (`{t['id']}`, "
                             f"{t.get('points')} pts, unlock lvl {t.get('unlockLevel')}): "
                             f"{clean_text(tl[-1].get('description') or tl[-1].get('effect', '')).replace(chr(10), ' ')}")
            cards.append("\n".join(lines))
        w.write(f"skills_{weapon}", f"Skills — {weapon}",
                f"All {len(rows)} {weapon} skills (active and passive) with level-1 and max-level effects and every "
                "skill specialization (trait) option.", cards)


def mastery_files(ctx: Context, w: Writer) -> None:
    rows = load(ctx.raw / "lists" / "weapon-specializations.json", []) or []
    by_weapon = defaultdict(list)
    for r in rows:
        d = load(ctx.raw / "details" / "weapon-specializations" / f"{re.sub(r'[^A-Za-z0-9._-]', '_', r['id'])}.json") or r
        by_weapon[d.get("mainCategory")].append(d)
    for weapon, nodes in sorted(by_weapon.items(), key=lambda kv: str(kv[0])):
        cards = []
        for d in sorted(nodes, key=lambda d: (str(d.get("subCategory")), -d.get("grade", 0), d.get("name", ""))):
            lines = [f"### {clean_text(d.get('name', d['id']))} (`{d['id']}`)",
                     f"- Tree: {d.get('subCategory')} | {GRADES.get(d.get('grade'), d.get('grade'))} | "
                     f"type: {d.get('specializationType')}"
                     + (" | only while this weapon is active" if d.get("weaponActivatedOnly") else "")]
            if d.get("description"):
                lines.append(f"- {clean_text(d['description']).replace(chr(10), ' ')}")
            stats = d.get("stats") or []
            if stats:
                lines.append(f"- Level 1: {ctx.stats(stats[0])}")
                if len(stats) > 1:
                    lines.append(f"- Level {len(stats)} (max): {ctx.stats(stats[-1])}")
            passives = d.get("passives") or []
            if passives:
                lines.append(f"- Level 1 effect: {clean_text(passives[0]).replace(chr(10), ' ')}")
                if len(passives) > 1:
                    lines.append(f"- Level {len(passives)} (max) effect: {clean_text(passives[-1]).replace(chr(10), ' ')}")
            cards.append("\n".join(lines))
        w.write(f"weapon_mastery_{weapon}", f"Weapon mastery (specialization) — {weapon}",
                f"All {len(cards)} {weapon} weapon mastery nodes grouped by tree, with level-1 and max-level effects.",
                cards)


def potential_file(ctx: Context, w: Writer) -> None:
    rows = load(ctx.raw / "lists" / "potential-abilities.json", []) or []
    cards = []
    for r in sorted(rows, key=lambda r: (str(r.get("subCategory")), str(r.get("mainCategory")), r.get("name", ""))):
        d = load(ctx.raw / "details" / "potential-abilities" / f"{re.sub(r'[^A-Za-z0-9._-]', '_', r['id'])}.json") or r
        lines = [f"### {clean_text(d.get('name', r['id']))} (`{r['id']}`)",
                 f"- Kind: {d.get('kind')} | gear: {', '.join(d.get('gearTypes') or [d.get('mainCategory', '')])} | "
                 f"weapon: {', '.join(d.get('weapons') or [str(d.get('subCategory'))])}"]
        if d.get("description"):
            lines.append(f"- {clean_text(d['description']).replace(chr(10), ' ')}")
        rolled = d.get("rolledBy") or []
        if rolled:
            names = sorted({f"{x.get('name', '').strip()} ({GRADES.get(x.get('grade'), x.get('grade'))})"
                            for x in rolled if isinstance(x, dict)})
            lines.append(f"- Can roll on {len(rolled)} items, e.g. " + ", ".join(names[:12])
                         + (f" (+{len(names) - 12} more)" if len(names) > 12 else ""))
        cards.append("\n".join(lines))
    w.write("potential_abilities", "Potential abilities",
            "Potential abilities that can roll on gear (mostly +1 skill level for a specific skill).", cards)


def generic_dataset(ctx: Context, w: Writer, name: str, title: str, intro: str, prefix: str = "db",
                    folder: str = "extra") -> None:
    rows = load(ctx.raw / "lists" / f"{name}.json", []) or []
    if not rows:
        return
    cards = []
    for r in sorted(rows, key=lambda r: (str(r.get("mainCategory")), str(r.get("subCategory")), str(r.get("name")))):
        detail = load(ctx.raw / "details" / name / f"{re.sub(r'[^A-Za-z0-9._-]', '_', r['id'])}.json")
        rec = detail or r
        body = ctx.render({k: v for k, v in rec.items() if k not in ("id", "name")})
        cards.append(f"### {clean_text(rec.get('name', r['id']))} (`{r['id']}`)\n" + "\n".join(body))
    w.write(f"{prefix}_{name}", title, intro, cards, folder)


def community_files(ctx: Context, w: Writer, max_builds: int = 4) -> None:
    base = ctx.raw / "community"
    index = load(base / "index.json", {}) or {}
    if not index:
        return
    skill_builds = {int(p.stem): load(p) for p in (base / "skill-builds").glob("*.json")}
    spec_builds = {int(p.stem): load(p) for p in (base / "specializations").glob("*.json")}
    summary = ["## Popularity overview", "",
               "| Weapon combo | Role (questlog) | Builds with ≥ min likes | Most-liked build (likes) |",
               "|---|---|---|---|"]
    for combo, role in CLASS_COMBOS.items():
        entries = index.get(combo, [])
        top = max(entries, key=lambda e: e["likeCount"], default=None)
        summary.append(f"| {combo} | {role} | {len(entries)} | "
                       + (f"{top['characterName']} ({top['likeCount']})" if top else "–") + " |")
    w.write("community_00_overview", "Community builds — overview",
            "How many well-liked public questlog builds exist per weapon combination.", ["\n".join(summary)],
            "community")

    for combo, entries in index.items():
        cards = []
        for e in sorted(entries, key=lambda e: -e["likeCount"]):
            char = load(base / "characters" / f"{re.sub(r'[^A-Za-z0-9._-]', '_', e['url'])}.json")
            if not char:
                continue
            c = char["character"]
            lines = [f"## {clean_text(c['name'])}",
                     f"- Author: {e.get('author')} | likes: {c.get('likeCount')} (last 30 days: {e.get('likesLast30Days')}) | "
                     f"level {c.get('level')} | tags: {', '.join(c.get('tags') or [])} | updated {str(c.get('updatedAt'))[:10]}",
                     f"- Link: https://questlog.gg/throne-and-liberty/en/character-builder/{c['url']}"]
            if c.get("desc"):
                desc = clean_text(c["desc"])
                lines.append("- Author's notes:\n" + "\n".join("  > " + l for l in desc.splitlines()[:80]))
            folders = {f["id"]: f["name"] for f in (char.get("folders") or [])}
            builds = sorted(char.get("builds", []),
                            key=lambda b: (b.get("id") != e.get("buildId"), b.get("order") or 0))
            if max_builds and len(builds) > max_builds:
                lines.append(f"- Showing the featured build and {max_builds - 1} more of {len(builds)} gear sets "
                             f"(others: {', '.join(clean_text(b.get('name', '')) for b in builds[max_builds:])[:600]})")
                builds = builds[:max_builds]
            for b in builds:
                lines.append(build_block(ctx, b, folders, skill_builds, spec_builds))
            cards.append("\n".join(lines))
        w.write(f"community_{combo}", f"Community builds — {combo} ({CLASS_COMBOS.get(combo, '')})",
                f"The most popular public questlog.gg character builds for {combo}, most-liked first. Each build lists "
                "attributes, every gear slot (item, traits, runes, potential, resonance), skill loadout with chosen "
                "specializations, and weapon mastery nodes.", cards, "community")


SLOT_ORDER = ["main_hand", "off_hand", "head", "chest", "cloak", "hands", "legs", "feet", "necklace", "bracelet",
              "ring1", "ring2", "belt", "earring1", "earring2", "brooch"]


def build_block(ctx: Context, b: dict, folders: dict, skill_builds: dict, spec_builds: dict) -> str:
    lines = [f"### Build: {clean_text(b.get('name', ''))}"
             + (f" [folder: {folders[b['folderId']]}]" if b.get("folderId") in folders else "")]
    if b.get("note"):
        lines.append(f"- Note: {clean_text(b['note']).replace(chr(10), ' ')}")
    if b.get("attributes"):
        lines.append("- Attribute points: " + ", ".join(f"{ctx.stat_name(k)} {v}" for k, v in b["attributes"].items()
                                                       if isinstance(v, (int, float)) and v))
    eq = b.get("equipment") or {}
    slots = sorted(eq, key=lambda s: SLOT_ORDER.index(s) if s in SLOT_ORDER else 99)
    for slot in slots:
        g = eq[slot]
        if not isinstance(g, dict) or not g.get("id"):
            continue
        g = {k: v for k, v in g.items() if v not in (None, "", {}, [])}
        bits = [f"**{ctx.name(g['id'])}**"]
        if isinstance(g.get("traits"), dict):
            bits.append("traits: " + ctx.stats(g["traits"]))
        if isinstance(g.get("uniqueTraits"), dict):
            bits.append("unique: " + ctx.stats(g["uniqueTraits"]))
        if isinstance(g.get("heroic"), list):
            g["heroic"] = dict(enumerate(g["heroic"]))
        if g.get("heroic"):
            heroic = [ctx.stat_name(v) for v in g["heroic"].values() if v]
            if heroic:
                bits.append("heroic: " + ", ".join(heroic))
        if isinstance(g.get("runes"), dict):
            bits.append("runes: " + ", ".join(f"{ctx.name(r.get('runeId'))} → {ctx.stat_name(r.get('statId'))} (lvl {r.get('lvl')})"
                                             for r in g["runes"].values() if isinstance(r, dict) and r.get("runeId")))
        if g.get("potential"):
            bits.append("potential: " + (ctx.stat_name(g["potential"]) if g["potential"] in ctx.stat_format
                                         else ctx.name(g["potential"])))
        if g.get("resonance"):
            bits.append("resonance: " + ctx.stat_name(g["resonance"]) + (f" tier {g['resonanceTier']}" if g.get("resonanceTier") else ""))
        if g.get("perk"):
            bits.append("skill core: " + ctx.name(g["perk"]))
        lines.append(f"- {slot}: " + " | ".join(bits))
    sb = skill_builds.get(b.get("skillBuildId"))
    if sb:
        lines.append(f"- Skill build \"{clean_text(sb.get('name', ''))}\" ({sb.get('mainHand')}/{sb.get('offHand')}):")
        for kind in ("active", "passive"):
            for s in sorted(sb.get(kind) or [], key=lambda s: s.get("order", 0)):
                tr = ", ".join(ctx.name(t) for t in s.get("traits") or [] if t)
                lines.append(f"  - {kind}: {ctx.name(s.get('skillId'))} lvl {s.get('lvl')}" + (f" — {tr}" if tr else ""))
    spec = spec_builds.get(b.get("weaponSpecializationBuildId"))
    if spec and spec.get("specialization"):
        lines.append("- Weapon mastery nodes: " + ", ".join(f"{ctx.name(n['id'])} {n.get('lvl')}"
                                                          for n in spec["specialization"]
                                                          if isinstance(n, dict) and n.get("id")))
    return "\n".join(lines)


def content_blocks(block, out: list[str]) -> None:
    if isinstance(block, list):
        for b in block:
            content_blocks(b, out)
        return
    if not isinstance(block, dict):
        return
    props = block.get("props") or {}
    if props.get("title"):
        out.append(f"#### {clean_text(props['title'])}")
    for key in ("text", "content", "caption", "description"):
        if isinstance(props.get(key), str) and props[key].strip():
            out.append(clean_text(props[key]))
    for key in ("buildId", "characterBuildId", "skillBuildId"):
        if props.get(key):
            out.append(f"(embedded {key} {props[key]})")
    for v in props.values():
        if isinstance(v, (list, dict)):
            content_blocks(v, out)


def content_files(ctx: Context, w: Writer) -> None:
    for category, title in (("guide", "Guides"), ("build_guide", "Build guides"), ("patch_note", "Patch notes")):
        files = sorted((ctx.raw / "content" / category).glob("*.json"))
        docs = [load(f) for f in files]
        docs = sorted([d for d in docs if d], key=lambda d: d.get("createdAt", ""), reverse=True)
        cards = []
        for d in docs:
            body: list[str] = []
            content_blocks(d.get("content"), body)
            author = d.get("author") or {}
            cards.append(f"## {clean_text(d.get('title', ''))}\n"
                         f"- Published {str(d.get('createdAt'))[:10]}, updated {str(d.get('updatedAt'))[:10]}"
                         f"{', by ' + author['name'] if author.get('name') else ''}\n"
                         f"- {clean_text(d.get('description', ''))}\n\n" + "\n\n".join(body))
        w.write(f"content_{category}", f"questlog.gg {title} (Throne and Liberty)",
                f"{len(cards)} {title.lower()}, newest first.", cards)


def start_here(ctx: Context, w: Writer, manifest: dict) -> None:
    files = "\n".join(f"- `{p.relative_to(w.out)}` ({p.stat().st_size // 1024} KB)" for p in sorted(w.written))
    text = f"""# Throne and Liberty knowledge pack (from questlog.gg)

Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} from https://questlog.gg/throne-and-liberty
(questlog data language: {manifest.get('language', 'en')}). This is community-maintained game data; check the
generation date against the latest patch notes before trusting numbers for very recent content.

## Which files to use

- `core/` — the game data needed to design builds (stats, gear, sets, runes, skills, weapon mastery,
  potentials, guides, patch notes). **Upload this folder to the Claude Project first.**
- `community/` — the most-liked public player builds for every weapon combination. Upload the overview
  plus the files for the weapon combos you play (or all of them if the Project has room).
- `extra/` — the rest of questlog's databases (NPCs, contracts, achievements, codex, recipes, items index…).
  Add these only if you also want Claude to answer general game questions and the Project has room.

## How this data is organized

- `stats_reference.md` — every stat id, its in-game name, unit and meaning; attribute point breakpoints
  (Strength, Dexterity, Wisdom, Perception, Fortitude).
- `gear_*` — all equipment (weapons, armor, accessories, artifacts/stones) with base stats, bonus stats,
  trait options, unique traits, heroic/random stat pools, potentials, skill cores and where to get them.
- `gear_item_sets.md` — set bonuses.
- `runes.md` — rune stat pools and rune synergies.
- `skills_<weapon>.md` — every skill per weapon, level-1 and max-level effects, cooldowns and every
  skill specialization choice.
- `weapon_mastery_<weapon>.md` — every weapon mastery node with level-1 and max-level effects.
- `potential_abilities.md` — skill-level potentials that can roll on gear.
- `community/community_*.md` — the most-liked public player builds per weapon combination, with full gear,
  runes, traits, skill loadouts, specializations and weapon mastery nodes (with author notes).
- `content_guide.md`, `content_patch_note.md` — questlog guides and patch notes.
- `extra/db_*.md` — every other questlog database (dungeons, bosses/NPCs, achievements, codex, contracts,
  polymorphs, lithographs, recipes, full item index…).

## Conventions

- Grades: {', '.join(f'{k} = {v}' for k, v in GRADES.items())}.
- Stats are shown as the game displays them (raw values have already been multiplied, see the stat dictionary).
  "Lower is better" stats (e.g. Debuff Duration, Attack Speed in seconds) are marked in the dictionary.
- Heavy Attack Chance = `double_attack`, Critical Hit Chance = `critical_attack`, Endurance = `critical_defense`,
  Heavy Attack Evasion = `double_defense`, Hit Chance = `accuracy`, Evasion = `evasion`, Cooldown Speed =
  `skill_cooldown_modifier` (check `stats_reference.md` for the exact names used by the game).
- Weapon combos are written `mainhand-offhand` using questlog weapon ids: sword (Sword & Shield), sword2h
  (Greatsword), dagger, bow (Longbow), crossbow, staff, wand (Wand & Tome), spear, orb, gauntlet.

## How to use it to design a strong build

1. Pick the weapon combo and goal (PvE boss, PvE farm, PvP small-scale, large-scale, tank, healer).
2. Read `community/community_<combo>.md` to see what the best-liked builds do and why (author notes).
3. Use `skills_<weapon>.md` for both weapons to pick actives, passives and specializations that synergise.
4. Pick gear from `gear_*` and `gear_item_sets.md`: prioritise the stats the skills scale with, then
   choose traits, runes (+ synergies from `runes.md`), potentials and attribute points
   (breakpoints in `stats_reference.md`).
5. Cross-check against `content_patch_note.md` for recent balance changes.
6. When quoting numbers, cite the file/item they came from.

## Files in this pack

{files}

## Collection summary

```
{json.dumps({k: v for k, v in manifest.items() if k in ('datasets', 'builder', 'content', 'community')}, indent=1)[:6000]}
```
"""
    path = w.out / "00_START_HERE.md"
    path.write_text(text, encoding="utf-8")
    w.written.insert(0, path)


def export(data_dir: str, max_file_kb: int = 900, min_grade: int = 31, max_builds: int = 4) -> list[Path]:
    raw = Path(data_dir) / "raw"
    if not raw.exists():
        raise SystemExit(f"{raw} not found — run `python -m questlog_tl scrape` first")
    ctx = Context(raw)
    w = Writer(Path(data_dir) / "knowledge", max_file_kb * 1024)
    w.write("stats_reference", "Stats, attributes and weapon mastery levels",
            "Reference for reading every other file in this pack.", stats_reference(ctx))
    gear_files(ctx, w, min_grade)
    rune_file(ctx, w)
    skill_files(ctx, w)
    mastery_files(ctx, w)
    potential_file(ctx, w)
    for name, title, intro, folder in (
        ("polymorphs", "Polymorphs (morph appearances)", "Morph appearances and their effects.", "extra"),
        ("litographs", "Lithographs", "Lithographs (craft/unlock recipes for gear).", "extra"),
    ):
        generic_dataset(ctx, w, name, title, intro, folder=folder)
    community_files(ctx, w, max_builds)
    content_files(ctx, w)
    done = {"weapon-specializations", "potential-abilities", "polymorphs", "litographs", "item-sets", "skill-traits",
            "skill-sets"}
    for name in BY_NAME:
        if name in done or name == "items":
            continue
        generic_dataset(ctx, w, name, f"Database — {name}", f"questlog.gg {name} database.")
    items_other_categories(ctx, w)
    start_here(ctx, w, load(raw / "manifest.json", {}) or {})
    return w.written


def items_other_categories(ctx: Context, w: Writer) -> None:
    """Non-equipment items as a compact index (name, grade, category)."""
    rows = load(ctx.raw / "lists" / "items.json", []) or []
    by_cat = defaultdict(list)
    for r in rows:
        by_cat[(r.get("mainCategory") or "uncategorized", r.get("subCategory") or "-")].append(r)
    sections = []
    for (main, sub), items in sorted(by_cat.items()):
        lines = [f"## {main} / {sub} ({len(items)})"]
        for r in sorted(items, key=lambda r: (-r.get("grade", 0), r.get("name", ""))):
            stats = ", ".join(ctx.stat_name(s) for s in r.get("statKeys") or [])
            lines.append(f"- {clean_text(r.get('name', ''))} (`{r['id']}`, {GRADES.get(r.get('grade'), r.get('grade'))})"
                         + (f" — stats: {stats}" if stats else ""))
        sections.append("\n".join(lines))
    w.write("db_items_index", "Item index (all items)",
            "Every item in the questlog database grouped by category. Full equipment details are in the gear_* files.",
            sections, "extra")
