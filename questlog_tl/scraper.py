"""Downloads questlog.gg Throne and Liberty data into ``<out>/raw``.

Layout::

    raw/lists/<dataset>.json          every list row (all pages merged)
    raw/details/<dataset>/<id>.json   full record for each entity
    raw/builder/<name>.json           character/skill builder datasets
    raw/manifest.json                 what was fetched and when

Already-downloaded detail files are skipped, so an interrupted run can be
resumed by running the same command again (use ``--refresh`` to re-fetch).
"""

from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from .client import ApiError, QuestlogClient
from .datasets import BUILD_ITEM_CATEGORIES, BUILDER_DATASETS, DATABASES, REFERENCE_DATASETS, Dataset


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def safe_filename(entity_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", entity_id)


PAGE_SIZE = 40
MAX_PAGES = 25          # the search backend never returns more than 1000 hits per query
MULTISELECT_FACETS = {"statKeys", "traitKeys"}


def _pages(client, ds, params, page_count, first):
    rows = list(first.get("pageData", []))
    for page in range(2, min(page_count, MAX_PAGES) + 1):
        rows.extend(client.call(ds.list_proc, {**params, "page": page}).get("pageData", []))
    return rows


def _fetch_partition(client, ds, params, rows_by_id, label):
    """Fetch every row matching ``params``, splitting the query when it hits the 1000-row cap."""
    first = client.call(ds.list_proc, {**params, "page": 1})
    page_count = first.get("pageCount", 1)
    if page_count <= MAX_PAGES:
        for r in _pages(client, ds, params, page_count, first):
            rows_by_id[r["id"]] = r
        log(f"  {ds.name}{label}: {page_count} page(s), {len(rows_by_id)} rows so far")
        return

    # Too many hits: split on a facet (grade, date added, ...) we have not filtered on yet.
    facets = params.get("facets", {})
    for key, dist in (first.get("facetDistribution") or {}).items():
        if key in facets or key in MULTISELECT_FACETS or not isinstance(dist, dict) or len(dist) < 2:
            continue
        for value in dist:
            v = int(value) if value.lstrip("-").isdigit() else value
            _fetch_partition(client, ds, {**params, "facets": {**facets, key: v}},
                             rows_by_id, f"{label}[{key}={value}]")
        return

    # No facet left: split on the categories seen when reading the list from both ends.
    edge_rows = []
    for sort_type in ("asc", "desc"):
        sorted_params = {**params, "sortBy": "name", "sortType": sort_type}
        first_sorted = client.call(ds.list_proc, {**sorted_params, "page": 1})
        edge_rows += _pages(client, ds, sorted_params, page_count, first_sorted)
    for r in edge_rows:
        rows_by_id[r["id"]] = r
    for level in ("mainCategory", "subCategory"):
        if level in params:
            continue
        values = {r.get(level) for r in edge_rows} - {None}
        if len(values) > 1:
            for v in sorted(values):
                _fetch_partition(client, ds, {**params, level: v}, rows_by_id, f"{label}[{level}={v}]")
            return
        if len(values) == 1:
            params = {**params, level: values.pop()}
    if page_count > 2 * MAX_PAGES:
        log(f"  ! {ds.name}{label}: ~{page_count * PAGE_SIZE} hits but the site only serves "
            f"2x{MAX_PAGES * PAGE_SIZE} (name A-Z and Z-A); some rows in this slice may be missing")


def fetch_list(client: QuestlogClient, ds: Dataset, language: str) -> list[dict]:
    rows_by_id: dict[str, dict] = {}
    _fetch_partition(client, ds, {"language": language}, rows_by_id, "")
    return list(rows_by_id.values())


def wants_detail(ds: Dataset, row: dict, detail_mode: str) -> bool:
    if detail_mode == "none":
        return False
    if detail_mode == "all":
        return True
    if not ds.build_relevant:
        return False
    if ds.name == "items":
        return row.get("mainCategory") in BUILD_ITEM_CATEGORIES
    return True


def fetch_details(client: QuestlogClient, ds: Dataset, rows: list[dict], out: Path,
                  language: str, workers: int, refresh: bool) -> tuple[int, list[str]]:
    target = out / "details" / ds.name
    todo = [r["id"] for r in rows
            if refresh or not (target / f"{safe_filename(r['id'])}.json").exists()]
    if not todo:
        return 0, []
    log(f"  {ds.name}: fetching {len(todo)} detail records")
    failed: list[str] = []
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(client.call, ds.detail_proc, {"id": i, "language": language}): i for i in todo}
        for fut in as_completed(futures):
            entity_id = futures[fut]
            try:
                write_json(target / f"{safe_filename(entity_id)}.json", fut.result())
                done += 1
            except ApiError as e:
                failed.append(entity_id)
                log(f"    ! {e}")
            if (done + len(failed)) % 200 == 0:
                log(f"    {done + len(failed)}/{len(todo)}")
    return done, failed


def scrape(out_dir: str, language: str = "en", datasets: list[str] | None = None,
           detail_mode: str = "build", workers: int = 4, min_interval: float = 0.25,
           refresh: bool = False, include_builder: bool = True, include_community: bool = True,
           build_pages: int = 1, min_likes: int = 3) -> dict:
    out = Path(out_dir) / "raw"
    client = QuestlogClient(min_interval=min_interval)
    selected = [d for d in DATABASES if datasets is None or d.name in datasets]
    manifest = {"source": "https://questlog.gg/throne-and-liberty", "language": language,
                "started": datetime.now(timezone.utc).isoformat(), "datasets": {}, "builder": {}}

    if include_builder:
        log("Builder datasets")
        for name, proc in {**BUILDER_DATASETS, **REFERENCE_DATASETS}.items():
            try:
                data = client.call(proc, {"language": language})
                write_json(out / "builder" / f"{name}.json", data)
                manifest["builder"][name] = len(data)
                log(f"  {name}: {len(data)} entries")
            except ApiError as e:
                manifest["builder"][name] = f"error: {e}"
                log(f"  ! {e}")

    for ds in selected:
        log(f"Dataset {ds.name}")
        try:
            rows = fetch_list(client, ds, language)
        except ApiError as e:
            manifest["datasets"][ds.name] = {"error": str(e)}
            log(f"  ! {e}")
            continue
        write_json(out / "lists" / f"{ds.name}.json", rows)
        detail_rows = [r for r in rows if wants_detail(ds, r, detail_mode)]
        fetched, failed = fetch_details(client, ds, detail_rows, out, language, workers, refresh)
        manifest["datasets"][ds.name] = {"listed": len(rows), "detail_targets": len(detail_rows),
                                         "fetched_now": fetched, "failed": failed}

    if include_community:
        from .community import scrape_builds, scrape_content
        log("Guides & patch notes")
        manifest["content"] = scrape_content(out, min_interval, refresh)
        log("Community builds")
        manifest["community"] = scrape_builds(out, min_interval, refresh, pages_per_combo=build_pages,
                                              min_likes=min_likes, workers=workers)

    manifest["finished"] = datetime.now(timezone.utc).isoformat()
    write_json(out / "manifest.json", manifest)
    return manifest
