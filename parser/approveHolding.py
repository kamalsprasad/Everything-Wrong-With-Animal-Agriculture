#!/usr/bin/env python3
"""Approve holding.json entries into README.md.

This module is intentionally dependency-free and can be used both by the local
dashboard backend and directly from the terminal.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_HOLDING_PATH = Path(__file__).resolve().parent / "holding.json"
DEFAULT_README_PATH = PROJECT_DIR / "README.md"

CATEGORY_ANCHORS: dict[str, dict[str, str]] = {
    "Environment": {
        "Climate Change": "climate",
        "Land Use & Pollution": "land-use",
        "Water Use & Pollution": "water-use",
    },
    "Damage to Communities": {
        "Environmental Justice": "communities",
    },
    "Human Rights & Health": {
        "Public Health": "health",
        "Worker Safety": "health",
        "Indigenous Rights": "health",
    },
    "Non-human Animals": {
        "Farmed Animals": "farmed",
        "Wildlife": "wildlife",
        "Fisheries": "non-human",
    },
    "Solutions & Alternatives": {
        "Veganic Farming": "solutions",
        "Affordability": "solutions",
        "Policy & Advertising": "solutions",
    },
    "FAQs": {
        "General": "faqs",
    },
}

SECTION_LABELS = {
    "Environment": "Environment",
    "Damage to Communities": "Damage to Communities",
    "Human Rights & Health": "Human Rights & Health",
    "Non-human Animals": "Non-human Animals",
    "Solutions & Alternatives": "Solutions & Alternatives",
    "FAQs": "FAQs",
}


@dataclass(frozen=True)
class EntryTarget:
    category: str
    subcategory: str
    anchor: str
    label: str


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return url.strip().lower().rstrip("/")
    parts = parsed._asdict()
    parts["scheme"] = parts["scheme"].lower()
    parts["netloc"] = parts["netloc"].lower()
    parts["path"] = parts["path"].rstrip("/")
    parts["fragment"] = ""
    return parsed.__class__(**parts).geturl() or url.strip().lower().rstrip("/")


def load_holding(path: Path = DEFAULT_HOLDING_PATH) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON array")
    return data


def get_entry_target(entry: dict[str, Any]) -> EntryTarget:
    category = str(entry.get("category") or "FAQs")
    subcategory = str(entry.get("subcategory") or "General")
    anchor = CATEGORY_ANCHORS.get(category, {}).get(subcategory)
    if not anchor:
        anchor = slugify_anchor(category)
    label = SECTION_LABELS.get(category, category)
    if subcategory and subcategory != "General":
        label = f"{label} / {subcategory}"
    return EntryTarget(category=category, subcategory=subcategory, anchor=anchor, label=label)


def slugify_anchor(text: str) -> str:
    text = text.lower().replace("&", "and")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "general"


def escape_link_text(text: str) -> str:
    return text.replace("[", "\\[").replace("]", "\\]")


def entry_to_markdown(entry: dict[str, Any]) -> str:
    title = str(entry.get("title") or "Untitled").strip()
    url = str(entry.get("url") or "").strip()
    snippet = str(entry.get("snippet") or "").strip()
    tags = entry.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    tag_text = ", ".join(str(tag) for tag in tags if str(tag).strip())

    lines = [f"    - ### [{escape_link_text(title)}]({url})", ""]
    if snippet:
        lines.extend([f"      > {snippet}", ""])
    if tag_text:
        lines.extend([f"      _Tags: **{tag_text}**_", ""])
    return "\n".join(lines).rstrip() + "\n"


def entry_exists_in_readme(readme_text: str, url: str) -> bool:
    return normalize_url(url) in readme_text


def find_anchor_insertion_index(lines: list[str], anchor: str) -> int:
    anchor_patterns = (
        f'name="{anchor}"',
        f"#{anchor})",
        f"#{anchor}</a>",
    )
    for index, line in enumerate(lines):
        if any(pattern in line for pattern in anchor_patterns):
            insert_at = index + 1
            while insert_at < len(lines) and lines[insert_at].strip() == "":
                insert_at += 1
            return insert_at

    contributing_index = next(
        (index for index, line in enumerate(lines) if line.startswith("## Contributing")),
        len(lines),
    )
    return contributing_index


def build_insertion_plan(
    selected_urls: Iterable[str],
    holding_entries: list[dict[str, Any]],
    readme_text: str,
) -> tuple[dict[str, list[str]], list[dict[str, str]], list[dict[str, str]]]:
    by_url = {normalize_url(str(entry.get("url", ""))): entry for entry in holding_entries}
    pending: dict[str, list[str]] = {}
    skipped: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []

    for raw_url in selected_urls:
        normalized = normalize_url(raw_url)
        entry = by_url.get(normalized)
        if entry is None:
            errors.append({"url": raw_url, "reason": "Entry not found in holding.json"})
            continue
        if entry_exists_in_readme(readme_text, str(entry.get("url", ""))):
            skipped.append({"url": raw_url, "reason": "Already present in README.md"})
            continue
        target = get_entry_target(entry)
        pending.setdefault(target.anchor, []).append(entry_to_markdown(entry))

    return pending, skipped, errors


def apply_insertions(readme_text: str, pending: dict[str, list[str]]) -> tuple[str, list[dict[str, Any]]]:
    if not pending:
        return readme_text, []

    lines = readme_text.splitlines(keepends=True)
    plans = []
    for anchor, markdown_blocks in pending.items():
        index = find_anchor_insertion_index(lines, anchor)
        block = "\n".join(markdown_blocks).rstrip() + "\n\n"
        plans.append((index, block, anchor, len(markdown_blocks)))

    for index, block, anchor, count in sorted(plans, key=lambda item: item[0], reverse=True):
        lines[index:index] = [block]

    summary = [
        {"target_anchor": anchor, "inserted": count, "insertion_index": index}
        for index, _block, anchor, count in sorted(plans, key=lambda item: item[0])
    ]
    return "".join(lines), summary


def approve_entries(
    selected_urls: Iterable[str],
    holding_path: Path = DEFAULT_HOLDING_PATH,
    readme_path: Path = DEFAULT_README_PATH,
    dry_run: bool = False,
) -> dict[str, Any]:
    urls = list(selected_urls)
    holding_entries = load_holding(holding_path)
    readme_text = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""
    pending, skipped, errors = build_insertion_plan(urls, holding_entries, readme_text)

    if dry_run:
        return {
            "dry_run": True,
            "inserted": sum(len(blocks) for blocks in pending.values()),
            "skipped": skipped,
            "errors": errors,
            "target_sections": [],
            "pending": [
                {
                    "target_anchor": anchor,
                    "markdown": "\n".join(blocks).rstrip() + "\n",
                }
                for anchor, blocks in pending.items()
            ],
        }

    if not pending:
        return {
            "dry_run": False,
            "inserted": 0,
            "skipped": skipped,
            "errors": errors,
            "target_sections": [],
        }

    updated_readme, target_sections = apply_insertions(readme_text, pending)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(readme_path.parent),
            prefix=".README-",
            suffix=".md",
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(updated_readme)
        assert tmp_path is not None
        tmp_path.replace(readme_path)
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass

    return {
        "dry_run": False,
        "inserted": sum(len(blocks) for blocks in pending.values()),
        "skipped": skipped,
        "errors": errors,
        "target_sections": target_sections,
        "readme_path": str(readme_path),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Approve selected holding.json entries into README.md")
    parser.add_argument("--holding", default=str(DEFAULT_HOLDING_PATH), help="Path to holding.json")
    parser.add_argument("--readme", default=str(DEFAULT_README_PATH), help="Path to README.md")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be inserted without writing README.md")
    parser.add_argument("--url", action="append", dest="urls", default=[], help="URL to approve. Can be provided multiple times.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = approve_entries(args.urls, Path(args.holding), Path(args.readme), dry_run=args.dry_run)
    except Exception as exc:
        print(f"approveHolding error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
