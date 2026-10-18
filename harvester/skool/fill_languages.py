"""Fill `groups.language` from name / description / lp_description text.

Standalone DB pass — no scraper involved. Reads groups whose language is
unknown, detects the language with langdetect over the combined text
(lp_description first, then description, then name), and updates ONLY the
language column. Every row gets a language:

  * detected code ('en', 'de', …) is mapped to Skool's language names
    ('english', 'german', …) so the value matches the rest of the table
  * low-confidence detections are still assigned (counted as `low conf`)
  * undetectable text → english
  * a language outside Skool's set → english

Run:
    cd C:/Users/Pouri/Desktop/skool
    uv run python -m skool.fill_languages            # dry-run report
    uv run python -m skool.fill_languages --write    # actually update
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from sqlalchemy import text as sql_text

from .db.db import dispose_db, session_scope

log = logging.getLogger("skool.fill_languages")

# langdetect code -> Skool language name (the values used in discovery).
CODE_TO_LANGUAGE = {
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

# detection below this confidence is treated as unknown
MIN_CONFIDENCE = 0.90
# text shorter than this is too little signal
MIN_TEXT_LEN = 20
BATCH = 2000


# everything undetectable / outside the set lands here
DEFAULT_LANGUAGE = "english"


def _combined_text(name: str | None, description: str | None, lp: str | None) -> str:
    """lp_description + description + name as one document.

    The name is included last so even groups with no/short descriptions have
    some signal to detect from.
    """
    parts = []
    for value in (lp, description, name):
        if value and value.strip():
            parts.append(value.strip())
        if len(" ".join(parts)) >= 400:
            break
    return " ".join(parts)[:1200]


async def fill(write: bool = False) -> None:
    # import lazily so --help works without the dependency installed
    try:
        from langdetect import DetectorFactory, detect_langs

        DetectorFactory.seed = 0  # deterministic results
    except ImportError:
        log.error("langdetect not installed:  uv pip install langdetect")
        return

    # languages that actually exist in the table — anything else stays NULL
    async with session_scope() as session:
        rows = (
            await session.execute(
                sql_text(
                    "SELECT DISTINCT language FROM skool.groups "
                    "WHERE language IS NOT NULL"
                )
            )
        ).all()
    known = {r[0] for r in rows}
    log.info("Languages already in DB: %s", sorted(known))

    scanned = updated = undetectable = skipped_short = low_conf = foreign = 0
    per_lang: dict[str, int] = {}
    last_id = ""  # keyset pagination — never re-reads a row

    while True:
        async with session_scope() as session:
            batch = (
                await session.execute(
                    sql_text("""
                        SELECT id, name, description, lp_description
                        FROM skool.groups
                        WHERE language IS NULL AND id > :last
                        ORDER BY id
                        LIMIT :lim
                    """),
                    {"last": last_id, "lim": BATCH},
                )
            ).all()
        if not batch:
            break
        last_id = batch[-1][0]  # advance the cursor even when nothing is written

        updates: list[tuple[str, str]] = []
        for gid, name, description, lp in batch:
            scanned += 1
            body = _combined_text(name, description, lp)
            # No confidence gate anymore: every row gets a language. Short or
            # ambiguous text still goes through detect on whatever signal it
            # has (the group name is included); anything undetectable or in a
            # language outside Skool's set defaults to english.
            language: str | None = None
            try:
                candidates = detect_langs(body) if body else []
                if candidates:
                    best = candidates[0]
                    code = getattr(best, "lang", None) or (
                        best[0] if isinstance(best, tuple) else str(best)
                    )
                    language = CODE_TO_LANGUAGE.get(code)
                    prob = float(getattr(best, "prob", 0.0))
                    if prob < MIN_CONFIDENCE:
                        low_conf += 1  # counted, but still assigned below
            except Exception:  # noqa: BLE001 - langdetect raises on odd input
                language = None

            if not language or language not in known:
                # undetectable, or a language outside Skool's set -> english
                if language is None:
                    undetectable += 1
                elif language not in known:
                    foreign += 1
                language = DEFAULT_LANGUAGE
            if len(body) < MIN_TEXT_LEN:
                skipped_short += 1  # counted; still assigned above

            updates.append((gid, language))
            per_lang[language] = per_lang.get(language, 0) + 1

        if write and updates:
            async with session_scope() as session:
                await session.execute(
                    sql_text("""
                        UPDATE skool.groups
                        SET language = data.lang
                        FROM (
                            SELECT CAST(unnest(CAST(:ids AS text[])) AS text) AS id,
                                   CAST(unnest(CAST(:langs AS text[])) AS text) AS lang
                        ) AS data
                        WHERE skool.groups.id = data.id
                    """),
                    {"ids": [u[0] for u in updates], "langs": [u[1] for u in updates]},
                )
        updated += len(updates)

        total_done = scanned
        log.info(
            "scanned=%s updated=%s (short=%s lowconf=%s undetect=%s other-lang=%s)",
            total_done,
            updated,
            skipped_short,
            low_conf,
            undetectable,
            foreign,
        )

    log.info("=" * 50)
    log.info("DONE | write=%s", write)
    log.info("  scanned:      %s", scanned)
    log.info("  updated:      %s", updated)
    log.info("  too short:    %s", skipped_short)
    log.info("  low conf:     %s", low_conf)
    log.info("  undetectable: %s", undetectable)
    log.info("  other lang:   %s", foreign)
    for lang, count in sorted(per_lang.items(), key=lambda kv: -kv[1]):
        log.info("  %-12s %s", lang, count)


async def _run(write: bool) -> None:
    try:
        await fill(write=write)
    finally:
        # dispose inside the SAME event loop that owns the connections —
        # a second asyncio.run() would close them from a foreign loop and
        # spew proactor tracebacks on shutdown
        await dispose_db()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fill groups.language from text")
    parser.add_argument(
        "--write", action="store_true", help="actually UPDATE (default: dry-run)"
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S"
    )
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass
    asyncio.run(_run(write=args.write))


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
