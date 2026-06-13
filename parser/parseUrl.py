#!/usr/bin/env python3
"""
parseUrl — fetch one URL, extract a README-ready entry, and append it to holding.json.

Usage:
  python parser/parseUrl.py https://example.com/article
  parser/parseUrl https://example.com/article

The script intentionally avoids a web app and keeps dependencies minimal:
- HTML parsing uses only Python's standard library.
- PDF text extraction uses pypdf only when needed. If pypdf is missing, the
  wrapper command re-runs under `uv run --with pypdf`.
"""

from __future__ import annotations

import argparse
import html
import importlib
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Iterable

ROOT_DIR = Path(__file__).resolve().parents[1]
PARSER_DIR = ROOT_DIR / "parser"
HOLDING_PATH = PARSER_DIR / "holding.json"
USER_AGENT = (
    "Mozilla/5.0 (compatible; EverythingWrongAnimalAgricultureParser/0.1; "
    "+https://github.com/Everything-Wrong-With-Animal-Agriculture)"
)

STOPWORDS = {
    "about",
    "above",
    "after",
    "again",
    "against",
    "also",
    "among",
    "animal",
    "animals",
    "article",
    "because",
    "before",
    "being",
    "below",
    "between",
    "both",
    "could",
    "during",
    "each",
    "either",
    "else",
    "every",
    "from",
    "further",
    "had",
    "has",
    "have",
    "having",
    "here",
    "hers",
    "herself",
    "him",
    "himself",
    "his",
    "how",
    "https",
    "into",
    "itself",
    "just",
    "more",
    "most",
    "other",
    "over",
    "own",
    "same",
    "should",
    "such",
    "than",
    "that",
    "their",
    "theirs",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "under",
    "until",
    "very",
    "what",
    "when",
    "where",
    "which",
    "while",
    "with",
    "would",
    "www",
    "year",
    "years",
    "you",
    "your",
    "yours",
    "yourself",
    "yourselves",
}

TAXONOMY: dict[str, dict[str, list[str]]] = {
    "Environment": {
        "Climate Change": [
            "climate",
            "emissions",
            "greenhouse",
            "methane",
            "carbon",
            "fossil",
            "warming",
            "ipcc",
            "paris agreement",
            "dairy companies",
            "meat companies",
            "lobbying",
            "plant-based replacements",
            "veganism",
            "carbon emissions",
            "greenhouse gas emissions",
            "fossil fuel emissions",
            "climate action",
            "climate crisis",
            "climate change targets",
            "mitigation",
        ],
        "Land Use & Pollution": [
            "land use",
            "pasture",
            "deforestation",
            "rainforest",
            "biodiversity",
            "pollution",
            "manure",
            "fertilizer",
            "fertiliser",
            "ranching",
            "cattle ranching",
            "land-use",
            "cropland",
            "feed crops",
            "habitat loss",
            "native forests",
            "agricultural land",
            "animal feed",
        ],
        "Water Use & Pollution": [
            "water",
            "drought",
            "wastewater",
            "nitrogen",
            "coral",
            "runoff",
            "water pollution",
            "dairy water",
            "milk water",
            "groundwater",
            "nitrates",
            "manure lagoon",
            "manure lagoons",
            "poop",
            "seagrass",
        ],
    },
    "Damage to Communities": {
        "Environmental Justice": [
            "environmental racism",
            "environmental justice",
            "low-income",
            "black",
            "brown",
            "indigenous",
            "communities",
            "pollution lawsuit",
            "rural communities",
            "factory farms",
            "san joaquin",
            "tulare",
            "nearby residents",
            "residents near",
            "hog farms",
            "pig farms",
            "cafo",
            "ammonia",
            "hydrogen sulfide",
            "blue baby syndrome",
            "respiratory",
            "toxic",
            "odor",
            "odour",
        ]
    },
    "Human Rights & Health": {
        "Public Health": [
            "health",
            "mortality",
            "disease",
            "pandemic",
            "covid",
            "antibiotic",
            "antimicrobial",
            "mrsa",
            "food safety",
            "public health",
            "noncommunicable",
            "zoonotic",
            "bird flu",
            "avian flu",
            "swine flu",
            "infection",
            "superbug",
            "antimicrobial resistance",
        ],
        "Worker Safety": [
            "workers",
            "slaughterhouse",
            "slaughter",
            "meat plant",
            "poultry plant",
            "tyson",
            "executives",
            "campaign",
            "forced labor",
            "forced-labor",
            "slavery",
            "slavery-like",
            "slave labor",
            "modern slavery",
            "labor prosecutors",
            "labor prosecutor",
            "labor lawsuit",
            "labor rights",
            "labor violations",
            "labor camp",
            "workers were held",
            "coerced labor",
            "human trafficking",
            "trafficking",
            "debt bondage",
            "abusive labor",
            "unsafe working conditions",
            "worker safety",
            "worker deaths",
            "covid office pool",
        ],
        "Indigenous Rights": [
            "indigenous",
            "tribes",
            "territory",
            "ranchers",
            "bolsonaro",
            "mining",
            "logging",
            "indigenous rights",
            "indigenous people",
            "traditional lands",
            "land rights",
            "raposa serra do sol",
        ],
    },
    "Non-human Animals": {
        "Farmed Animals": [
            "farmed animals",
            "land animals",
            "pigs",
            "chickens",
            "cows",
            "cattle",
            "poultry",
            "fish",
            "shellfish",
            "killed",
            "slaughter",
        ],
        "Wildlife": [
            "wildlife",
            "biodiversity",
            "extinction",
            "native species",
            "wolves",
            "elk",
            "prairie dogs",
            "turtles",
            "bees",
            "butterflies",
        ],
        "Fisheries": [
            "fisheries",
            "seafood",
            "fish as livestock feed",
            "overfishing",
            "marine",
            "aquatic",
        ],
    },
    "Solutions & Alternatives": {
        "Veganic Farming": [
            "veganic",
            "stock-free",
            "plant-based",
            "alternatives",
            "plant-based diets",
            "plant-based meals",
        ],
        "Affordability": [
            "cheaper",
            "quicker",
            "cost",
            "price",
            "affordability",
            "meal cost",
        ],
        "Policy & Advertising": [
            "ban meat adverts",
            "advertisement",
            "policy",
            "meat adverts",
            "public spaces",
            "reduction",
            "ban",
            "advertising",
            "public service",
            "public campaigns",
            "labeling",
            "labelling",
        ],
    },
    "FAQs": {
        "General": ["faq", "frequently asked", "why", "contributing"],
    },
}

# Reverse lookup for known phrases and important nouns.
KNOWN_TERMS = sorted(
    {
        term
        for subcategories in TAXONOMY.values()
        for terms in subcategories.values()
        for term in terms
    }
    | {
        "usa",
        "europe",
        "eu",
        "uk",
        "brazil",
        "california",
        "north carolina",
        "oklahoma",
        "arkansas",
        "iowa",
        "delaware",
        "mississippi",
        "maryland",
        "kansas",
        "wyoming",
        "jbs",
        "cargill",
        "hormel",
        "fonterra",
        "smithfield",
        "greenpeace",
        "tyson",
        "who",
        "ipcc",
        "paris agreement",
        "ag-gag",
        "factory farms",
        "cafo",
        "manure",
        "methane",
        "dairy",
        "beef",
        "pork",
        "chicken",
        "poultry",
        "fish",
        "pasture",
        "deforestation",
        "biodiversity",
        "water",
        "emissions",
        "climate",
        "plant-based",
        "veganic",
        "slaughterhouse",
        "indigenous",
        "workers",
        "forced labor",
        "slavery",
        "labor prosecutors",
        "human rights",
        "worker safety",
        "indigenous people",
        "land rights",
        "environmental justice",
        "hog farms",
        "pig farms",
        "manure lagoon",
        "manure lagoons",
        "groundwater",
        "nitrates",
        "blue baby syndrome",
        "respiratory",
        "zoonotic",
        "bird flu",
        "avian flu",
        "superbug",
        "antimicrobial resistance",
    }
)


# Strong human-centered signals should outrank incidental environmental terms.
# For example, an article about the Amazon can mention deforestation, but if the
# main issue is forced labor or slavery-like labor it belongs under Human Rights.
STRONG_CATEGORY_HINTS: dict[str, list[str]] = {
    "Human Rights & Health": [
        "forced labor",
        "forced-labor",
        "slavery",
        "slavery-like",
        "slave labor",
        "modern slavery",
        "labor prosecutors",
        "labor prosecutor",
        "labor lawsuit",
        "labor rights",
        "labor violations",
        "workers were held",
        "coerced labor",
        "human trafficking",
        "trafficking",
        "debt bondage",
        "abusive labor",
        "worker deaths",
        "worker safety",
        "covid office pool",
        "indigenous rights",
        "land rights",
        "traditional lands",
        "raposa serra do sol",
    ],
    "Damage to Communities": [
        "environmental racism",
        "environmental justice",
        "blue baby syndrome",
        "hydrogen sulfide",
        "manure lagoon",
        "manure lagoons",
        "nearby residents",
        "residents near",
        "rural communities",
    ],
    "Non-human Animals": [
        "killed for food",
        "animal abuse",
        "farmed animals",
        "slaughtered",
        "extinction",
        "native species",
    ],
}


CATEGORY_PRIORITY = {
    "Human Rights & Health": 5,
    "Damage to Communities": 4,
    "Non-human Animals": 3,
    "Environment": 2,
    "Solutions & Alternatives": 1,
    "FAQs": 0,
}


# Title/snippet-level hints describe the article's main angle better than
# repeated body terms. These keep README placement aligned with the existing
# category structure when an article touches several themes.
TITLE_SUBCATEGORY_HINTS: dict[tuple[str, str], list[str]] = {
    ("Environment", "Land Use & Pollution"): [
        "cropland",
        "land use",
        "pasture",
        "feed crops",
        "agricultural land",
        "animal feed",
        "food security",
        "food loss",
        "replacement diets",
        "plant-based replacement diets",
    ],
    ("Environment", "Water Use & Pollution"): [
        "water use",
        "dairy water",
        "milk water",
        "water pollution",
        "wastewater",
    ],
    ("Damage to Communities", "Environmental Justice"): [
        "environmental racism",
        "environmental justice",
        "factory farms",
        "rural communities",
    ],
    ("Human Rights & Health", "Worker Safety"): [
        "forced labor",
        "slavery",
        "slavery-like",
        "labor prosecutors",
        "workers were held",
    ],
    ("Human Rights & Health", "Indigenous Rights"): [
        "indigenous rights",
        "land rights",
        "traditional lands",
        "indigenous tribes",
    ],
}



@dataclass
class FetchResult:
    url: str
    content_type: str
    text: str
    meta_description: str | None = None
    source_title: str | None = None
    headings: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)


class SimpleHTMLParser(HTMLParser):
    """Small dependency-free HTML extractor for title, headings, paragraphs, and text."""

    BLOCK_TAGS = {"p", "blockquote", "li", "h1", "h2", "h3", "h4", "h5", "h6"}
    SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "canvas"}
    HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_chunks: list[str] = []
        self.meta_description: str | None = None
        self.meta_og_title: str | None = None
        self.headings: list[str] = []
        self.blocks: list[str] = []
        self.all_text_chunks: list[str] = []
        self._skip_depth = 0
        self._current_tag: str | None = None
        self._current_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr_map = {key.lower(): value or "" for key, value in attrs}

        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return

        if tag == "title":
            self._start_capture("title")
            return

        if tag == "meta":
            name = attr_map.get("name", "").lower()
            prop = attr_map.get("property", "").lower()
            content = clean_text(attr_map.get("content", ""))
            if name == "description" and content:
                self.meta_description = content
            if prop in {"og:title", "twitter:title"} and content:
                self.meta_og_title = content
            return

        if tag in self.BLOCK_TAGS:
            self._start_capture(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return

        if self._current_tag == tag:
            text = clean_text("".join(self._current_chunks))
            if text:
                if tag == "title":
                    self.title_chunks.append(text)
                elif tag in self.HEADING_TAGS:
                    self.headings.append(text)
                else:
                    self.blocks.append(text)
            self._current_tag = None
            self._current_chunks = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self.all_text_chunks.append(data)
        if self._current_tag:
            self._current_chunks.append(data)

    def handle_entityref(self, name: str) -> None:
        if self._skip_depth:
            return
        self.all_text_chunks.append(f"&{name};")
        if self._current_tag:
            self._current_chunks.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._skip_depth:
            return
        self.all_text_chunks.append(f"&#{name};")
        if self._current_tag:
            self._current_chunks.append(f"&#{name};")

    def _start_capture(self, tag: str) -> None:
        self._current_tag = tag
        self._current_chunks = []


def clean_text(text: str, max_length: int | None = None) -> str:
    text = html.unescape(text)
    text = re.sub(r"[\t\r\n]+", " ", text)
    text = re.sub(r"[ \u00a0]+", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = text.strip()
    if max_length is not None and len(text) > max_length:
        text = text[: max_length - 1].rstrip() + "…"
    return text


def normalize_url(raw_url: str) -> str:
    parsed = urllib.parse.urlparse(raw_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Only http and https URLs are supported: {raw_url}")
    if not parsed.netloc:
        raise ValueError(f"URL must include a host: {raw_url}")

    parts = parsed._asdict()
    parts["scheme"] = parts["scheme"].lower()
    parts["netloc"] = parts["netloc"].lower()
    parts["path"] = urllib.parse.unquote(parts["path"])
    parts["query"] = urllib.parse.unquote(parts["query"])
    parts["fragment"] = ""
    normalized = urllib.parse.urlunparse(urllib.parse.ParseResult(**parts))
    return normalized.rstrip("/") or normalized


def fetch_url(url: str, timeout: int = 30) -> FetchResult:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/pdf,application/xhtml+xml,q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
            headers = response.headers
            final_url = normalize_url(response.geturl())
            content_type = headers.get_content_type() or ""
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP error {exc.code} while fetching {url}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not fetch {url}: {exc.reason}") from exc

    if is_pdf_response(final_url, content_type, data):
        text = extract_pdf_text(data)
        return FetchResult(
            url=final_url,
            content_type=content_type or "application/pdf",
            text=text,
            meta_description=None,
            source_title=None,
            headings=[],
        )

    charset = headers.get_content_charset() or detect_encoding(data)
    decoded = data.decode(charset, errors="replace")
    parser = SimpleHTMLParser()
    parser.feed(decoded)
    parser.close()

    title = clean_text(" ".join(parser.title_chunks))
    if not title and parser.meta_og_title:
        title = clean_text(parser.meta_og_title)

    all_text = clean_text(" ".join(parser.all_text_chunks))
    return FetchResult(
        url=final_url,
        content_type=content_type or "text/html",
        text=all_text,
        meta_description=parser.meta_description,
        source_title=title,
        headings=[clean_text(h) for h in parser.headings if clean_text(h)],
        blocks=[clean_text(b) for b in parser.blocks if clean_text(b)],
    )


def detect_encoding(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    return "utf-8"


def is_pdf_response(url: str, content_type: str, data: bytes) -> bool:
    if content_type.lower() == "application/pdf":
        return True
    if url.lower().split("?", 1)[0].endswith(".pdf"):
        return True
    return data.startswith(b"%PDF")


def extract_pdf_text(data: bytes) -> str:
    try:
        pypdf = importlib.import_module("pypdf")
    except ImportError as exc:
        raise RuntimeError(
            "PDF parsing requires pypdf. Re-run with: "
            "uv run --with pypdf python3 parser/parseUrl.py <url>"
        ) from exc

    PdfReader = pypdf.PdfReader
    reader = PdfReader(BytesIO(data))
    chunks: list[str] = []
    max_chars = 80_000
    for page in reader.pages:
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        if page_text:
            chunks.append(page_text)
        if sum(len(chunk) for chunk in chunks) >= max_chars:
            break
    return clean_text("\n\n".join(chunks))


def choose_title(fetch: FetchResult) -> str:
    if fetch.source_title:
        return fetch.source_title
    if fetch.headings:
        return fetch.headings[0]
    first_line = next((line for line in fetch.text.splitlines() if clean_text(line)), "")
    return clean_text(first_line, 160) or fetch.url


def choose_snippet(fetch: FetchResult) -> str:
    if fetch.meta_description:
        return clean_text(fetch.meta_description, 260)

    blocks = getattr(fetch, "blocks", []) or []
    quote_blocks = [block for block in blocks if looks_quote_like(block)]
    if quote_blocks:
        return clean_text(quote_blocks[0], 300)

    useful_blocks = [block for block in blocks if len(block) >= 80]
    if useful_blocks:
        return clean_text(useful_blocks[0], 300)

    for line in fetch.text.splitlines():
        line = clean_text(line)
        if len(line) >= 80:
            return clean_text(line, 300)

    return clean_text(fetch.text, 300)


def looks_quote_like(text: str) -> bool:
    stripped = text.strip()
    return (
        stripped.startswith(("“", '"', "‘", "'"))
        or stripped.endswith(("”", '"', "’", "'"))
        or re.search(r"\bsaid\b|\breported\b|\baccording to\b", stripped, re.IGNORECASE) is not None
    )


def choose_category_and_subcategory(text: str, title: str, snippet: str = "") -> tuple[str, str]:
    title_corpus = f"{title}\n{snippet}".lower()
    haystack = f"{title}\n{snippet}\n{text}".lower()

    # Title/snippet hints are a compact statement of the article's main angle.
    for (category, subcategory), hints in TITLE_SUBCATEGORY_HINTS.items():
        if any(hint in title_corpus for hint in hints):
            return category, subcategory

    # A strong rights/labor/community/animal-welfare signal should not be
    # drowned out by repeated environmental terms in the body text.
    for category, hints in STRONG_CATEGORY_HINTS.items():
        for hint in hints:
            if hint in title_corpus or hint in haystack:
                return category, choose_subcategory_for_category(category, haystack)

    best_category = "FAQs"
    best_subcategory = "General"
    best_score = 0
    best_priority = CATEGORY_PRIORITY.get(best_category, 0)

    for category, subcategories in TAXONOMY.items():
        for subcategory, terms in subcategories.items():
            score = 0
            for term in terms:
                if term not in haystack:
                    continue
                occurrences = haystack.count(term)
                # Title/snippet matches are more likely to describe the article's
                # actual focus than a single incidental mention in the body.
                weight = 3 if term in title_corpus else 1
                score += (len(term.split()) + 1) * occurrences * weight
            priority = CATEGORY_PRIORITY.get(category, 0)
            if score > best_score or (score == best_score and priority > best_priority):
                best_score = score
                best_priority = priority
                best_category = category
                best_subcategory = subcategory

    return best_category, best_subcategory


def choose_subcategory_for_category(category: str, haystack: str) -> str:
    if category == "Human Rights & Health":
        if any(term in haystack for term in (
            "forced labor",
            "forced-labor",
            "slavery",
            "slavery-like",
            "slave labor",
            "modern slavery",
            "labor prosecutors",
            "labor prosecutor",
            "labor lawsuit",
            "labor rights",
            "labor violations",
            "workers were held",
            "coerced labor",
            "human trafficking",
            "trafficking",
            "debt bondage",
            "abusive labor",
            "worker safety",
            "worker deaths",
        )):
            return "Worker Safety"
        if any(term in haystack for term in ("indigenous", "tribes", "territory", "land rights", "traditional lands")):
            return "Indigenous Rights"
        if any(term in haystack for term in ("health", "mortality", "disease", "pandemic", "covid", "antibiotic", "mrsa", "zoonotic", "infection", "superbug")):
            return "Public Health"
        return "Worker Safety"
    if category == "Damage to Communities":
        return "Environmental Justice"
    if category == "Non-human Animals":
        if any(term in haystack for term in ("fish", "seafood", "fisheries", "marine", "aquatic", "overfishing")):
            return "Fisheries"
        if any(term in haystack for term in ("wildlife", "extinction", "native species", "wolves", "elk", "prairie dogs", "turtles", "bees", "butterflies")):
            return "Wildlife"
        return "Farmed Animals"
    return "General"


def extract_tags(text: str, title: str, snippet: str, category: str, subcategory: str, limit: int = 8) -> list[str]:
    title_corpus = f"{title}\n{snippet}".lower()
    body_corpus = text.lower()
    full_corpus = f"{title_corpus}\n{body_corpus}".lower()
    tags: list[str] = []

    def add_tag(term: str) -> None:
        formatted = format_tag(term)
        if not formatted:
            return
        slug = tag_slug(formatted)
        if all(tag_slug(existing) != slug for existing in tags):
            tags.append(formatted)

    # Prefer terms that describe the article's actual focus before generic
    # lexicographic tag ordering pulls in incidental environment terms.
    selected_subcategory_terms = TAXONOMY.get(category, {}).get(subcategory, [])
    category_terms = [term for term in selected_subcategory_terms if term in full_corpus]
    for term in category_terms:
        add_tag(term)
        if len(tags) >= limit:
            return tags

    for term in KNOWN_TERMS:
        if term in title_corpus:
            add_tag(term)
        if len(tags) >= limit:
            return tags

    for term in KNOWN_TERMS:
        if term in body_corpus:
            add_tag(term)
        if len(tags) >= limit:
            return tags

    # If known tags are sparse, fall back to frequent words, prioritizing
    # title/snippet words before body words.
    for corpus in (title_corpus, body_corpus):
        words = re.findall(r"[a-z][a-z0-9-]{2,}", corpus)
        counts = Counter(word for word in words if word not in STOPWORDS and len(word) >= 4)
        for word, _ in counts.most_common():
            tag = format_tag(word)
            if tag_slug(tag) in {tag_slug(t) for t in tags}:
                continue
            tags.append(tag)
            if len(tags) >= limit:
                break
        if len(tags) >= limit:
            break

    # Keep category/subcategory context if keyword extraction is sparse.
    if len(tags) < 3:
        for tag in [category, subcategory]:
            formatted = format_tag(tag)
            if tag_slug(formatted) not in {tag_slug(t) for t in tags}:
                tags.append(formatted)
            if len(tags) >= limit:
                break

    return tags[:limit]


def tag_slug(tag: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", tag.lower()).strip("-")


def format_tag(term: str) -> str:
    term = clean_text(term).lower()
    term = term.replace("&", "and")
    term = re.sub(r"[^a-z0-9\s-]+", "", term)
    term = re.sub(r"\s+", " ", term).strip()
    return term


def load_holding() -> list[dict[str, object]]:
    if not HOLDING_PATH.exists() or HOLDING_PATH.stat().st_size == 0:
        return []
    try:
        with HOLDING_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{HOLDING_PATH} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise RuntimeError(f"{HOLDING_PATH} must contain a JSON array")
    return data


def save_holding(entries: list[dict[str, object]]) -> None:
    PARSER_DIR.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=PARSER_DIR,
        prefix=".holding-",
        suffix=".json",
        delete=False,
    )
    try:
        with tmp:
            json.dump(entries, tmp, indent=2, ensure_ascii=False)
            tmp.write("\n")
        os.replace(tmp.name, HOLDING_PATH)
    finally:
        try:
            os.unlink(tmp.name)
        except FileNotFoundError:
            pass


def entry_exists(entries: Iterable[dict[str, object]], url: str) -> bool:
    return any(normalize_entry_url(str(entry.get("url", ""))) == url for entry in entries)


def normalize_entry_url(url: str) -> str:
    try:
        return normalize_url(url)
    except ValueError:
        return url.strip().lower().rstrip("/")


def build_entry(url: str) -> dict[str, object]:
    fetch = fetch_url(url)
    title = choose_title(fetch)
    snippet = choose_snippet(fetch)
    category, subcategory = choose_category_and_subcategory(fetch.text, title, snippet)
    tags = extract_tags(fetch.text, title, snippet, category, subcategory)
    return {
        "url": fetch.url,
        "category": category,
        "subcategory": subcategory,
        "title": title,
        "snippet": snippet,
        "tags": tags,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse a URL and append a curated entry to parser/holding.json")
    parser.add_argument("url", help="HTML or PDF URL to parse")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the entry without writing holding.json",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-parse an existing URL and replace its holding.json entry.",
    )
    return parser.parse_args(argv)


def replace_entry(entries: list[dict[str, object]], url: str, entry: dict[str, object]) -> list[dict[str, object]]:
    replaced = False
    updated: list[dict[str, object]] = []
    for existing in entries:
        if not replaced and normalize_entry_url(str(existing.get("url", ""))) == url:
            updated.append(entry)
            replaced = True
        else:
            updated.append(existing)
    if not replaced:
        updated.append(entry)
    return updated


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        normalized_url = normalize_url(args.url)
        entries = load_holding()
        if entry_exists(entries, normalized_url) and not args.force:
            print(f"Duplicate URL skipped: {normalized_url}")
            return 0

        entry = build_entry(normalized_url)
        if not args.dry_run:
            entries = replace_entry(entries, normalized_url, entry)
            save_holding(entries)

        print(json.dumps(entry, indent=2, ensure_ascii=False))
        if not args.dry_run:
            action = "refreshed" if args.force else "updated"
            print(f"{action} {HOLDING_PATH.relative_to(ROOT_DIR)} with 1 entry.")
        return 0
    except Exception as exc:
        print(f"parseUrl error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
