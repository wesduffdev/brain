"""Behavior: the reading faculty ingests a document — reads it, cleans it, and
chunks it into training-ready text — and writes an MLX-LM LoRA dataset from those
chunks (reading R1, ADR 0036). Pure and deterministic: no model, no MLX, no GPU,
so the whole ingest half runs in the plain suite.
"""
from __future__ import annotations

import json

import pytest

from app.language.ingest import (
    IngestedDocument,
    ingest_document,
    ingest_text,
    write_dataset,
)

_MESSY = (
    "First paragraph line one.  \r\n"
    "First paragraph line\ttwo.\r\n"
    "\r\n\r\n\r\n"
    "Second paragraph here.\r\n"
)


def _write(tmp_path, text, name="doc.txt"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_ingest_reads_cleans_and_chunks_a_document(tmp_path):
    doc = ingest_document(_write(tmp_path, _MESSY), max_chars=1000, overlap=100)

    assert isinstance(doc, IngestedDocument)
    assert doc.chunks, "a non-empty document yields at least one chunk"
    joined = "\n".join(doc.chunks)
    assert "\r" not in joined          # carriage returns normalised away
    assert "\t" not in joined          # tabs collapsed to spaces
    assert "\n\n\n" not in joined      # runs of blank lines collapsed
    assert "  " not in joined          # runs of spaces collapsed
    for chunk in doc.chunks:
        assert chunk == chunk.strip()  # no leading/trailing whitespace


def test_chunking_is_deterministic(tmp_path):
    path = _write(tmp_path, _MESSY)
    assert ingest_document(path).chunks == ingest_document(path).chunks


def test_short_document_is_a_single_chunk(tmp_path):
    doc = ingest_document(_write(tmp_path, "A short note."), max_chars=1000)
    assert doc.chunks == ("A short note.",)


def test_a_long_paragraph_is_split_into_overlapping_chunks(tmp_path):
    words = " ".join(f"word{i:04d}" for i in range(600))  # one long paragraph
    doc = ingest_document(_write(tmp_path, words), max_chars=200, overlap=60)

    assert len(doc.chunks) > 1, "a paragraph past max_chars splits into many chunks"
    for chunk in doc.chunks:
        assert len(chunk) <= 200       # no chunk exceeds the configured size
    # adjacent chunks overlap — the tail of one reappears at the head of the next
    tail = set(doc.chunks[0].split()[-6:])
    head = set(doc.chunks[1].split()[:12])
    assert tail & head, "consecutive chunks share overlapping words"


def test_empty_document_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        ingest_document(_write(tmp_path, "   \n\t\r\n  \n"))


def test_as_examples_wraps_each_chunk_as_text(tmp_path):
    doc = ingest_text("Alpha para.\n\nBeta para.", source="mem", max_chars=1000)
    assert doc.as_examples() == tuple({"text": c} for c in doc.chunks)


def test_write_dataset_emits_train_and_valid_jsonl(tmp_path):
    text = "\n\n".join(f"Paragraph number {i} with some words." for i in range(10))
    doc = ingest_text(text, source="mem", max_chars=60)
    out = write_dataset(doc, str(tmp_path / "ds"), valid_fraction=0.1)

    train_lines = (tmp_path / "ds" / "train.jsonl").read_text().splitlines()
    valid_lines = (tmp_path / "ds" / "valid.jsonl").read_text().splitlines()
    assert len(train_lines) == out["train_count"] >= 1
    assert len(valid_lines) == out["valid_count"] >= 1
    assert out["train_count"] + out["valid_count"] == len(doc.chunks)
    # every line is a JSON object carrying the chunk text under "text"
    for line in train_lines + valid_lines:
        assert set(json.loads(line)) == {"text"}


def test_dataset_split_is_deterministic(tmp_path):
    text = "\n\n".join(f"Paragraph {i}." for i in range(8))
    doc = ingest_text(text, source="mem", max_chars=40)
    write_dataset(doc, str(tmp_path / "a"), valid_fraction=0.25)
    write_dataset(doc, str(tmp_path / "b"), valid_fraction=0.25)
    for name in ("train.jsonl", "valid.jsonl"):
        assert (tmp_path / "a" / name).read_text() == (tmp_path / "b" / name).read_text()
