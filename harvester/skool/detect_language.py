"""Fill in the `language` of groups that have none.

For every group whose `language` is NULL/empty, detect the language from its
text — preferring the long landing-page description (`lp_description`) over
the short one (`description`) — and write it back. **Only the `language`
column is touched**; every other field stays exactly as it is.

Detection uses langdetect (ISO 639-1 codes), mapped to Skool's language names
(`english`, `german`, …). A group is only updated when detection is confident;
ambiguous text stays NULL so a later run (or better text) can decide.

Run:
    python -m skool.detect_language                 # detect + update
    python -m skool.detect_language --dry-run       # report only, no writes
    python -m skool.detect_language --limit 1000    # first 1000 only
    python -m skool.detect_language --batch-size 500 --confidence 0.95
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Any

log = logging.getLogger("skool.detect_language")

# langdetect returns ISO 639-1 codes; Skool's `language` column uses full names.
# Codes not listed here are skipped (not part of Skool's language list).
_ISO_TO_NAME: dict[str, str] = {
    "en": "english",
    "de": "german",
    "es": "spanish",
    "fr": "french",
    "zh-cn": "chinese",
    "zh-tw": "chinese",
    "it": "italian",
    "nl": "dutch",
    "vi": "vietnamese",
    "ar": "arabic",
    "he": "hebrew",
    "da": "danish",
    "ro": "romanian",
    "tr": "turkish",
    "pl": "polish",
    "cs": "czech",
    "hu": "hungarian",
    "sv": "swedish",
    "pt": "portuguese",
    "bg": "bulgarian",
    "no": "norwegian",
    "fi": "finnish",
    "hr": "croatian",
    "lv": "latvian",
    "sk": "slovak",
    "sr": "serbian",
    "mn": "mongolian",
    "ht": "haitian",
    "th": "thai",
    "sl": "slovenian",
    "ru": "russian",
    "lt": "lithuanian",
    "am": "amharic",
    "ms": "malay",
    "et": "estonian",
    "el": "greek",
    "uk": "ukrainian",
    "sw": "swahili",
    "ja": "japanese",
    "tl": "filipino",
    "fa": "persian",
    "cy": "welsh",
    "ko": "korean",
    "zh": "chinese",
    "id": "indonesian",
    "la": "latin",
    "bn": "bengali",
    "ca": "catalan",
    "hi": "hindi",
}

# langdetect is probabilistic; below this confidence we keep NULL rather than
# guess. 0.80 keeps short descriptions honest (a ~30-word Spanish blurb scores
# es≈0.86) while still filtering emoji-only / ambiguous text.
DEFAULT_CONFIDENCE = 0.80


def _detector() -> Any:
    """langdetect with a fixed seed so results are deterministic."""
    from langdetect import DetectorFactory, detect_langs

    DetectorFactory.seed = 0
    return detect_langs


def detect_language(text: str, min_confidence: float = DEFAULT_CONFIDENCE) -> str | None:
    """Detect the language of `text`; None when unsure or unsupported.

    Returns the Skool language name ('english', 'german', …).
    """
    if not text or len(text.strip()) < 20:
        # too little signal — single words / emoji strings are unreliable
        return None
    try:
        candidates = _detector()(text)
    except Exception:  # noqa: BLE001 - langdetect raises LangDetectException
        return None
    if not candidates:
        return None
    best = max(candidates, key=lambda c: c.prob)
    name = _ISO_TO_NAME.get(best.lang.lower())
    if not name or best.prob < min_confidence:
        return None
    return name


async def run(
    batch_size: int = 500,
    limit: int | None = None,
    dry_run: bool = False,
    min_confidence: float = DEFAULT_CONFIDENCE,
) -> dict[str, int]:
    """Walk all language-less groups and fill their `language` column.

    Only `language` is written — via a targeted UPDATE, never an upsert.
    """
    from sqlalchemy import text as sql_text

    from .db.db import dispose_db, session_scope

    stats = {"seen": 0, "detected": 0, "updated": 0, "unsure": 0, "unsupported": 0}
    offset = 0

    while True:
        async with session_scope() as session:
            rows = (
                await session.execute(
                    sql_text(
                        """
                        SELECT id, name, lp_description, description
                        FROM skool.groups
                        WHERE language IS NULL OR language = ''
                        ORDER BY id
                        LIMIT :limit OFFSET :offset
                        """
                    ),
                    {"limit": batch_size, "offset": offset},
                )
            ).mappings()
            batch = [dict(r) for r in rows]

        if not batch:
            break

        updates: dict[str, str] = {}
        for row in batch:
            stats["seen"] += 1
            text_body = (row.get("lp_description") or "").strip() or (
                row.get("description") or ""
            ).strip()
            detected = detect_language(text_body, min_confidence)
            if detected:
                updates[row["id"]] = detected
                stats["detected"] += 1
            else:
                stats["unsure"] += 1

        if updates and not dry_run:
            async with session_scope() as session:
                # one UPDATE per distinct target language, chunked by ids
                for lang_name, ids in _by_language(updates).items():
                    await session.execute(
                        sql_text(
                            'UPDATE skool.groups SET language = :lang WHERE id = ANY(:ids)'
                        ),
                        {"lang": lang_name, "ids": list(ids)},
                    )
            stats["updated"] += len(updates)

        log.info(
            "%s processed | %s detected | %s updated%s",
            stats["seen"],
            stats["detected"],
            stats["updated"] if not dry_run else 0,
            " (dry-run)" if dry_run else "",
        )

        offset += batch_size
        if limit is not None and offset >= limit:
            break

    return stats


def _by_language(updates: dict[str, str]) -> dict[str, list[str]]:
    """Group {group_id: language} into {language: [group_ids]}."""
    out: dict[str, list[str]] = {}
    for gid, lang in updates.items():
        out.setdefault(lang, []).append(gid)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fill missing group languages from their descriptions")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--limit", type=int, default=None, help="max groups to process")
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    parser.add_argument(
        "--confidence", type=float, default=DEFAULT_CONFIDENCE,
        help="minimum detection probability (default: 0.90)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    stats = asyncio.run(
        run(
            batch_size=args.batch_size,
            limit=args.limit,
            dry_run=args.dry_run,
            min_confidence=args.confidence,
        )
    )
    log.info(
        "Done: seen=%(seen)s detected=%(detected)s updated=%(updated)s unsure=%(unsure)s",
        stats,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
