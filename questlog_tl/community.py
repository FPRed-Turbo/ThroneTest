"""Community content: questlog guides, patch notes and top-rated public player builds.

Layout::

    raw/content/<category>/<slug>.json      guide / patch note (full body)
    raw/community/characters/<url>.json     public character build (all gear sets)
    raw/community/skill-builds/<id>.json    skill build referenced by a character build
    raw/community/specializations/<id>.json weapon-mastery build referenced by a character build
    raw/community/index.json                which builds were picked for which weapon combo
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .client import ApiError, QuestlogClient
from .datasets import CLASS_COMBOS, CONTENT_CATEGORIES, CORE_BASE_URL, TL_GAME_ID
from .scraper import log, safe_filename, write_json


def scrape_content(out: Path, min_interval: float, refresh: bool) -> dict:
    core = QuestlogClient(base_url=CORE_BASE_URL, min_interval=min_interval)
    summary = {}
    for category in CONTENT_CATEGORIES:
        entries, page, page_count = [], 1, 1
        while page <= page_count:
            data = core.call("content.getPublishedContentList",
                             {"category": category, "page": page, "gameId": TL_GAME_ID})
            page_count = data.get("pageCount", 1)
            entries += data.get("pageData", [])
            page += 1
        for e in entries:
            path = out / "content" / category / f"{safe_filename(e['slug'])}.json"
            if path.exists() and not refresh:
                continue
            try:
                write_json(path, core.call("content.getPublishedContent",
                                           {"slug": e["slug"], "category": category, "gameId": TL_GAME_ID}))
            except ApiError as err:
                log(f"  ! {err}")
        summary[category] = len(entries)
        log(f"  content/{category}: {len(entries)}")
    return summary


def scrape_builds(out: Path, min_interval: float, refresh: bool, pages_per_combo: int = 1,
                  min_likes: int = 3, workers: int = 4) -> dict:
    """Most popular public builds for every weapon combo, plus their skill & mastery builds."""
    client = QuestlogClient(min_interval=min_interval)
    base = out / "community"
    index: dict[str, list[dict]] = {}
    for combo, role in CLASS_COMBOS.items():
        main, off = combo.split("-")
        picked = []
        for page in range(1, pages_per_combo + 1):
            data = client.call("characterBuilder.searchCharacters",
                               {"page": page, "tags": [], "sort": "popular",
                                "mainHandWeapon": main, "offHandWeapon": off})
            picked += [r for r in data.get("pageData", []) if r.get("likeCount", 0) >= min_likes]
            if page >= data.get("pageCount", 1):
                break
        index[combo] = [{"url": r["url"], "characterName": r["characterName"], "buildName": r["buildName"],
                         "likeCount": r["likeCount"], "likesLast30Days": r.get("likesLast30Days"),
                         "tags": r.get("tags", []), "weaponTypes": r.get("weaponTypes"), "role": role,
                         "author": (r.get("user") or {}).get("name"), "updatedAt": r.get("updatedAt")}
                        for r in picked]
        log(f"  builds/{combo}: {len(picked)} public builds with >= {min_likes} likes")

    def get_character(url: str):
        path = base / "characters" / f"{safe_filename(url)}.json"
        if path.exists() and not refresh:
            return
        data = client.call("characterBuilder.getCharacter", {"slug": url})
        if data.get("status") == "ACCESSIBLE":
            write_json(path, data)

    urls = sorted({b["url"] for builds in index.values() for b in builds})
    log(f"  fetching {len(urls)} character builds")
    _run(workers, get_character, urls)

    # Skill builds and weapon-mastery builds referenced by the gear sets.
    skill_ids, spec_ids = set(), set()
    for f in (base / "characters").glob("*.json"):
        for b in json.loads(f.read_text(encoding="utf-8")).get("builds", []):
            if b.get("skillBuildId"):
                skill_ids.add(b["skillBuildId"])
            if b.get("weaponSpecializationBuildId"):
                spec_ids.add(b["weaponSpecializationBuildId"])

    def fetcher(proc: str, folder: str):
        def fetch(build_id: int):
            path = base / folder / f"{build_id}.json"
            if path.exists() and not refresh:
                return
            data = client.call(proc, {"id": build_id})
            if data:
                write_json(path, data)
        return fetch

    log(f"  fetching {len(skill_ids)} skill builds, {len(spec_ids)} weapon-mastery builds")
    _run(workers, fetcher("skillBuilder.getSkillBuildByIdForContent", "skill-builds"), sorted(skill_ids))
    _run(workers, fetcher("weaponSpecialization.getWeaponSpecializationById", "specializations"),
         sorted(spec_ids))
    write_json(base / "index.json", index)
    return {"characters": len(urls), "skill_builds": len(skill_ids), "specializations": len(spec_ids)}


def _run(workers, fn, args):
    hidden = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for fut in [pool.submit(fn, a) for a in args]:
            try:
                fut.result()
            except ApiError as e:
                if "HTTP 404" in str(e) or "HTTP 403" in str(e):
                    hidden += 1  # the author made this part of the build private
                else:
                    log(f"  ! {e}")
    if hidden:
        log(f"  ({hidden} private or deleted entries skipped)")
