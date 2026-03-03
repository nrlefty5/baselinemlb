#!/usr/bin/env python3
"""
assemble_lgbm_model.py
======================
One-time script to reconstruct lgbm_matchup_model.txt from its chunks.

The LightGBM model file (1.2 MB) was split into 20 chunks stored in
models/artifacts/chunks/ due to repository constraints. Run this script
once from the repository root to assemble the full model file.

Usage
-----
    python models/artifacts/assemble_lgbm_model.py

After running, lgbm_matchup_model.txt will be present in models/artifacts/.
"""

from pathlib import Path

CHUNKS_DIR = Path(__file__).parent / "chunks"
OUTPUT_FILE = Path(__file__).parent / "lgbm_matchup_model.txt"
NUM_CHUNKS = 20


def assemble():
    print(f"Assembling {NUM_CHUNKS} chunks from {CHUNKS_DIR} ...")

    if not CHUNKS_DIR.exists():
        raise FileNotFoundError(
            f"Chunks directory not found: {CHUNKS_DIR}\n"
            "Make sure you have pulled the full repository."
        )

    parts = []
    for i in range(NUM_CHUNKS):
        chunk_path = CHUNKS_DIR / f"lgbm_model_chunk_{i:02d}.txt"
        if not chunk_path.exists():
            raise FileNotFoundError(f"Missing chunk: {chunk_path}")
        with open(chunk_path, "r", encoding="utf-8") as f:
            parts.append(f.read())
        print(f"  Loaded chunk {i:02d}: {len(parts[-1])} chars")

    assembled = "".join(parts)
    print(f"\nTotal assembled: {len(assembled):,} chars")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(assembled)

    print(f"Model saved to: {OUTPUT_FILE}")

    # Quick sanity check
    assert assembled.startswith("tree\nversion=v4\n"), (
        "Assembled file does not start with expected LightGBM header!"
    )
    assert assembled.endswith("pandas_categorical:null\n"), (
        "Assembled file does not end with expected LightGBM footer!"
    )
    print("Sanity check passed: LightGBM format verified.")
    return OUTPUT_FILE


if __name__ == "__main__":
    assemble()
