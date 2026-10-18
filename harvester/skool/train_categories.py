"""Train a text classifier and fill `groups.category_slug` where it is NULL.

Standalone DB pass, like `fill_languages.py` — no scraper involved.

Labeled rows:  groups with a known category_slug  → (text, category)
Target rows:   groups whose category_slug is NULL/empty

The input text per group is name + display_name + description +
lp_description. Languages are mixed (48 of them), so the model uses character
n-grams (`char_wb`, 3..5) which are language-agnostic and robust to typos.

Modes:
    python -m skool.train_categories            # train + report + save model
    python -m skool.train_categories --predict  # + predict NULLs (dry-run)
    python -m skool.train_categories --write    # + actually UPDATE the DB

Only the `category_slug` column is ever written. Updates use keyset pagination
(`id > last_id`) so no row is read twice, and the run is idempotent — a rerun
picks up only rows that are still NULL.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import pathlib
import sys

import joblib
from sqlalchemy import text as sql_text

from .db.db import dispose_db, session_scope

log = logging.getLogger("skool.train_categories")

MODEL_PATH = pathlib.Path(__file__).resolve().parent.parent / "models" / "category_clf.joblib"

BATCH = 2000


def _row_text(name: str | None, display_name: str | None,
              description: str | None, lp_description: str | None) -> str:
    """Combine the group's text fields into one document."""
    parts = []
    for value in (name, display_name, description, lp_description):
        if value and value.strip():
            parts.append(value.strip())
        if len(" ".join(parts)) >= 600:
            break
    return " ".join(parts)[:1500]


async def load_data() -> tuple[list[str], list[str], list[tuple[str, str, str]]]:
    """Scan the table once; split into (train texts, labels, NULL targets).

    Targets carry (id, text, name) so predictions can be logged meaningfully.
    """
    labeled_texts: list[str] = []
    labels: list[str] = []
    targets: list[tuple[str, str, str]] = []

    last_id = ""
    while True:
        async with session_scope() as session:
            batch = (
                await session.execute(
                    sql_text("""
                        SELECT id, name, display_name, description,
                               lp_description, category_slug
                        FROM skool.groups
                        WHERE id > :last
                        ORDER BY id
                        LIMIT :lim
                    """),
                    {"last": last_id, "lim": BATCH},
                )
            ).all()
        if not batch:
            break
        last_id = batch[-1][0]

        for gid, name, display_name, description, lp, category in batch:
            body = _row_text(name, display_name, description, lp)
            if not body:
                continue  # nothing to learn from / predict on
            if category:
                labeled_texts.append(body)
                labels.append(category)
            else:
                targets.append((gid, body, name or ""))
    log.info(
        "Loaded %s labeled rows, %s predictable NULL targets",
        len(labeled_texts),
        len(targets),
    )
    return labeled_texts, labels, targets


def build_model(threshold_info: bool = False):
    """Word + char n-gram TF-IDF (union) -> calibrated LinearSVC.

    Word features capture clear niche keywords ("crypto", "yoga"); char
    n-grams keep the multilingual/typo robustness. The union of both beats
    either alone on this data.
    """
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.pipeline import FeatureUnion, Pipeline
    from sklearn.svm import LinearSVC

    base = LinearSVC(C=1.0, class_weight="balanced", random_state=42)
    return Pipeline([
        (
            "features",
            FeatureUnion([
                (
                    "word",
                    TfidfVectorizer(
                        analyzer="word",
                        ngram_range=(1, 2),
                        min_df=2,
                        sublinear_tf=True,
                        max_features=120_000,
                    ),
                ),
                (
                    "char",
                    TfidfVectorizer(
                        analyzer="char_wb",
                        ngram_range=(3, 5),
                        min_df=2,
                        sublinear_tf=True,
                        max_features=200_000,
                    ),
                ),
            ]),
        ),
        (
            "clf",
            CalibratedClassifierCV(base, method="sigmoid", cv=3),
        ),
    ])


def train(labeled_texts: list[str], labels: list[str]):
    """Stratified 85/15 split, full per-class report, save the fitted model."""
    from sklearn.metrics import classification_report
    from sklearn.model_selection import train_test_split

    x_train, x_test, y_train, y_test = train_test_split(
        labeled_texts,
        labels,
        test_size=0.15,
        random_state=42,
        stratify=labels,
    )
    log.info("Train=%s test=%s classes=%s", len(x_train), len(x_test), len(set(labels)))

    model = build_model()
    model.fit(x_train, y_train)

    report = classification_report(
        y_test, model.predict(x_test), digits=3, zero_division=0
    )
    log.info("Classification report (test split):\n%s", report)

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    log.info("Model saved to %s", MODEL_PATH)
    return model


async def predict_and_maybe_write(
    model, targets: list[tuple[str, str, str]], threshold: float, write: bool
) -> None:
    """Predict in batches, apply the confidence gate, optionally UPDATE."""
    updates: list[tuple[str, str]] = []  # (group_id, predicted_category)
    below = 0
    distribution: dict[str, int] = {}

    for start in range(0, len(targets), BATCH):
        chunk = targets[start : start + BATCH]
        texts = [t[1] for t in chunk]
        proba = model.predict_proba(texts)
        classes = model.named_steps["clf"].classes_
        best_idx = proba.argmax(axis=1)
        best_prob = proba.max(axis=1)

        for (gid, _body, name), idx, prob in zip(chunk, best_idx, best_prob):
            if float(prob) < threshold:
                below += 1
                continue
            cat = str(classes[idx])
            updates.append((gid, cat))
            distribution[cat] = distribution.get(cat, 0) + 1
            log.debug("predict %s (%s): %s %.2f", gid, name[:40], cat, prob)

    log.info(
        "Prediction: %s above threshold | %s below (%s) stay NULL",
        len(updates),
        below,
        threshold,
    )
    log.info("Predicted distribution:")
    for cat, count in sorted(distribution.items(), key=lambda kv: -kv[1]):
        log.info("  %-18s %s", cat, count)

    if not write:
        log.info("Dry-run — nothing written to the database")
        return

    written = 0
    for start in range(0, len(updates), BATCH):
        chunk = updates[start : start + BATCH]
        async with session_scope() as session:
            await session.execute(
                sql_text("""
                    UPDATE skool.groups
                    SET category_slug = data.cat
                    FROM (
                        SELECT CAST(unnest(CAST(:ids AS text[])) AS text) AS id,
                               CAST(unnest(CAST(:cats AS text[])) AS text) AS cat
                    ) AS data
                    WHERE skool.groups.id = data.id
                      AND (skool.groups.category_slug IS NULL
                           OR skool.groups.category_slug = '')
                """),
                {
                    "ids": [u[0] for u in chunk],
                    "cats": [u[1] for u in chunk],
                },
            )
        written += len(chunk)
        log.info("wrote %s/%s", written, len(updates))

    log.info("DONE: %s rows updated (only category_slug)", written)


async def _run(predict: bool, write: bool, threshold: float) -> None:
    try:
        labeled_texts, labels, targets = await load_data()
        if not labeled_texts or len(set(labels)) < 2:
            log.error("Not enough labeled data to train")
            return
        model = train(labeled_texts, labels)
        if predict or write:
            await predict_and_maybe_write(model, targets, threshold, write)
        else:
            log.info("Train-only mode: pass --predict or --write to classify NULLs")
    finally:
        # dispose inside the SAME event loop that owns the connections
        await dispose_db()


def main() -> None:
    parser = argparse.ArgumentParser(description="Train + fill groups.category_slug")
    parser.add_argument(
        "--predict", action="store_true",
        help="classify NULL categories (dry-run, nothing written)",
    )
    parser.add_argument(
        "--write", action="store_true", help="actually UPDATE category_slug"
    )
    parser.add_argument(
        "--threshold", type=float, default=0.75,
        help="min calibrated probability to accept a prediction (default: 0.75)",
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
    asyncio.run(_run(predict=args.predict, write=args.write, threshold=args.threshold))


if __name__ == "__main__":
    main()
