"""ingest — read a document, clean it, and chunk it into training-ready text
(reading R1, ADR 0036).

The front half of the reading faculty, and deliberately PURE: it touches no
model, no MLX, and no GPU, so the whole thing runs in the plain suite and is
fully deterministic. Given a document you hand the being, it produces the
training corpus a LoRA fine-tune learns from — a tuple of cleaned text chunks,
and (via `write_dataset`) the `train.jsonl` / `valid.jsonl` pair in the
`{"text": ...}` shape MLX-LM's LoRA trainer reads.

Public surface:
  - `IngestedDocument` — a cleaned, chunked document (its `source` + `chunks`).
  - `ingest_text(text, source, ...)` / `ingest_document(path, ...)` — clean and
    chunk a string / a file into an `IngestedDocument`.
  - `write_dataset(document, dest_dir, ...)` — write the MLX-LM LoRA dataset
    (train/valid JSONL) from a document's chunks, with a deterministic split.

Cleaning normalises line endings, collapses tabs/space runs and blank-line runs,
and strips each line — so the corpus is uniform regardless of how the source was
authored. Chunking packs whole paragraphs up to `max_chars`, and splits a single
over-long paragraph into word-boundary windows that share `overlap` characters,
so no training chunk is oversized and continuous prose keeps its context across a
split.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

# Control characters that carry no text (everything below space except the
# newline we keep as structure). Compiled once; tabs are handled separately.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BLANK_RUN = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class IngestedDocument:
    """A document after cleaning + chunking: where it came from (`source`) and
    the ordered, training-ready text `chunks` derived from it. `text` rejoins the
    chunks; `as_examples` wraps each chunk in the `{"text": ...}` record the
    MLX-LM LoRA trainer consumes."""

    source: str
    chunks: Tuple[str, ...]

    @property
    def text(self) -> str:
        return "\n\n".join(self.chunks)

    def as_examples(self) -> Tuple[Dict[str, str], ...]:
        return tuple({"text": chunk} for chunk in self.chunks)


def _clean(raw: str) -> str:
    """Normalise raw document text into uniform training prose."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\t", " ")
    text = _CONTROL.sub("", text)
    # Collapse internal whitespace per line and drop leading/trailing spaces.
    lines = [" ".join(line.split()) for line in text.split("\n")]
    text = "\n".join(lines)
    # Collapse runs of blank lines to a single paragraph boundary.
    text = _BLANK_RUN.sub("\n\n", text)
    return text.strip()


def _split_long(paragraph: str, max_chars: int, overlap: int) -> List[str]:
    """Split one over-long paragraph into word-boundary windows of at most
    `max_chars`, each sharing about `overlap` characters with the previous one so
    context is not lost at a boundary. Always makes forward progress."""
    words = paragraph.split()
    if overlap >= max_chars:
        raise ValueError(
            f"overlap ({overlap}) must be smaller than max_chars ({max_chars}) "
            f"to window an over-long paragraph"
        )
    windows: List[str] = []
    i = 0
    while i < len(words):
        # Grow a window from i until the next word would overflow max_chars.
        j = i
        length = 0
        while j < len(words):
            add = len(words[j]) + (1 if j > i else 0)
            if length + add > max_chars and j > i:
                break
            length += add
            j += 1
        windows.append(" ".join(words[i:j]))
        if j >= len(words):
            break
        # Step back over the trailing words that fit within `overlap` so the next
        # window repeats them; guaranteed to still advance past i.
        back = 0
        carried = 0
        k = j - 1
        while k > i and carried + len(words[k]) + (1 if carried else 0) <= overlap:
            carried += len(words[k]) + (1 if carried else 0)
            back += 1
            k -= 1
        i = j - back
    return windows


def _chunk(text: str, max_chars: int, overlap: int, min_chunk_chars: int) -> Tuple[str, ...]:
    """Pack cleaned `text` into training chunks: whole paragraphs combined up to
    `max_chars`, an over-long paragraph windowed with `overlap`. Chunks shorter
    than `min_chunk_chars` are dropped."""
    if max_chars <= 0:
        raise ValueError(f"max_chars must be positive, got {max_chars}")

    units: List[str] = []
    for paragraph in (p.strip() for p in text.split("\n\n")):
        if not paragraph:
            continue
        if len(paragraph) <= max_chars:
            units.append(paragraph)
        else:
            units.extend(_split_long(paragraph, max_chars, overlap))

    chunks: List[str] = []
    current = ""
    for unit in units:
        if not current:
            current = unit
        elif len(current) + 2 + len(unit) <= max_chars:
            current = current + "\n\n" + unit
        else:
            chunks.append(current)
            current = unit
    if current:
        chunks.append(current)

    return tuple(c for c in chunks if len(c) >= min_chunk_chars)


def ingest_text(
    text: str,
    *,
    source: str,
    max_chars: int = 1000,
    overlap: int = 100,
    min_chunk_chars: int = 1,
) -> IngestedDocument:
    """Clean and chunk in-memory `text` into an `IngestedDocument`. A document
    that is empty after cleaning is rejected (fail-loud), never silently dropped."""
    cleaned = _clean(text)
    if not cleaned:
        raise ValueError(f"document {source!r} is empty after cleaning; nothing to ingest")
    chunks = _chunk(cleaned, max_chars, overlap, min_chunk_chars)
    if not chunks:
        raise ValueError(f"document {source!r} produced no chunks (min_chunk_chars too high?)")
    return IngestedDocument(source=source, chunks=chunks)


def ingest_document(
    path: str,
    *,
    max_chars: int = 1000,
    overlap: int = 100,
    min_chunk_chars: int = 1,
) -> IngestedDocument:
    """Read the document at `path` (UTF-8, lenient) and ingest its text."""
    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    return ingest_text(
        raw,
        source=path,
        max_chars=max_chars,
        overlap=overlap,
        min_chunk_chars=min_chunk_chars,
    )


def write_dataset(
    document: IngestedDocument,
    dest_dir: str,
    *,
    valid_fraction: float = 0.1,
) -> Dict[str, object]:
    """Write `document`'s chunks as an MLX-LM LoRA dataset — `train.jsonl` and
    `valid.jsonl` under `dest_dir`, one `{"text": chunk}` object per line. The
    split is DETERMINISTIC: the last `round(n * valid_fraction)` chunks (at least
    one, and never all) are held out for validation; a single-chunk document is
    written to both so MLX-LM always finds a validation set. Returns the two paths
    and their line counts."""
    chunks = list(document.chunks)
    n = len(chunks)
    if n == 0:
        raise ValueError("cannot write a dataset for a document with no chunks")

    if n == 1:
        train, valid = chunks, chunks
    else:
        k = max(1, round(n * valid_fraction))
        k = min(k, n - 1)  # keep at least one chunk for training
        train, valid = chunks[: n - k], chunks[n - k :]

    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    train_path = dest / "train.jsonl"
    valid_path = dest / "valid.jsonl"
    train_path.write_text("".join(json.dumps({"text": c}) + "\n" for c in train))
    valid_path.write_text("".join(json.dumps({"text": c}) + "\n" for c in valid))

    return {
        "train": str(train_path),
        "valid": str(valid_path),
        "train_count": len(train),
        "valid_count": len(valid),
    }
