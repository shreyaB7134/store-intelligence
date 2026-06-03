# PROMPT:
# Test re-entry detection logic in the pipeline.
# Tests: ReIDEngine cosine similarity, gallery management, frame gap eviction.
#
# CHANGES MADE:
# - Direct unit tests on ReIDEngine (no DB needed)
# - Tests embedding match and no-match scenarios

from __future__ import annotations

import numpy as np
import pytest

from pipeline.reid_engine import ReIDEngine


# ---------------------------------------------------------------------------
# Empty gallery
# ---------------------------------------------------------------------------
def test_reid_empty_gallery():
    """find_match against an empty gallery must return None."""
    engine = ReIDEngine()
    embedding = np.random.randn(96)
    result = engine.find_match(embedding, current_frame=100)
    assert result is None


# ---------------------------------------------------------------------------
# Gallery insertion
# ---------------------------------------------------------------------------
def test_reid_adds_to_gallery():
    """add_to_gallery must insert the visitor ID into the internal gallery dict."""
    engine = ReIDEngine()
    embedding = np.ones(96) / np.sqrt(96)
    engine.add_to_gallery("VIS_001", embedding, frame_idx=0)
    assert "VIS_001" in engine._gallery


# ---------------------------------------------------------------------------
# Positive match (high cosine similarity)
# ---------------------------------------------------------------------------
def test_reid_matches_similar_embedding():
    """
    An embedding that is very close (small Gaussian noise) to a gallery
    embedding should be matched to the correct visitor ID.
    """
    engine = ReIDEngine()
    embedding = np.ones(96)
    embedding = embedding / np.linalg.norm(embedding)

    # Register visitor as exited so it is eligible for re-entry matching
    engine.add_to_gallery("VIS_001", embedding, frame_idx=0)
    engine.update_exit_frame("VIS_001", frame_idx=0)

    # Probe: same direction with tiny noise (cosine similarity ≈ 1)
    noisy = embedding + np.random.randn(96) * 0.05
    noisy = noisy / np.linalg.norm(noisy)

    match = engine.find_match(noisy, current_frame=50)
    assert match == "VIS_001"


# ---------------------------------------------------------------------------
# Negative match (orthogonal / opposite embedding)
# ---------------------------------------------------------------------------
def test_reid_no_match_different_embedding():
    """
    An embedding pointing in the opposite direction to the gallery entry
    must NOT be matched (cosine similarity ≈ -1, below threshold).
    """
    engine = ReIDEngine()
    emb1 = np.ones(96) / np.sqrt(96)
    emb2 = -emb1  # 180° opposite

    engine.add_to_gallery("VIS_001", emb1, frame_idx=0)
    engine.update_exit_frame("VIS_001", frame_idx=0)

    match = engine.find_match(emb2, current_frame=50)
    assert match is None


# ---------------------------------------------------------------------------
# Exclusion of currently-active visitors
# ---------------------------------------------------------------------------
def test_reid_excludes_active_visitors():
    """
    Visitors passed in the exclude_ids set must never be returned as a match,
    even when their embedding similarity is high.
    """
    engine = ReIDEngine()
    embedding = np.ones(96) / np.sqrt(96)
    engine.add_to_gallery("VIS_001", embedding, frame_idx=0)
    engine.update_exit_frame("VIS_001", frame_idx=0)

    match = engine.find_match(embedding, current_frame=50, exclude_ids={"VIS_001"})
    assert match is None


# ---------------------------------------------------------------------------
# Frame-gap eviction (time-to-live)
# ---------------------------------------------------------------------------
def test_reid_evicts_old_entries():
    """
    A gallery entry whose exit frame is older than MAX_REENTRY_FRAME_GAP frames
    should NOT be returned as a match (stale entry must be evicted at query time).
    """
    engine = ReIDEngine()
    embedding = np.ones(96) / np.sqrt(96)
    engine.add_to_gallery("VIS_001", embedding, frame_idx=0)
    engine.update_exit_frame("VIS_001", frame_idx=0)

    # Query far beyond the allowed re-entry window
    far_future = engine.MAX_REENTRY_FRAME_GAP + 100
    match = engine.find_match(embedding, current_frame=far_future)
    assert match is None  # Entry is too old; must not match


# ---------------------------------------------------------------------------
# Gallery size cap
# ---------------------------------------------------------------------------
def test_reid_gallery_eviction():
    """
    The gallery must never exceed MAX_GALLERY_SIZE entries.
    When capacity is exceeded the oldest entries should be evicted automatically.
    """
    engine = ReIDEngine()
    engine.MAX_GALLERY_SIZE = 5  # Override for a fast, deterministic test

    for i in range(10):
        emb = np.random.randn(96)
        emb = emb / np.linalg.norm(emb)
        engine.add_to_gallery(f"VIS_{i:03d}", emb, frame_idx=i)

    assert len(engine._gallery) <= 5, (
        f"Gallery size {len(engine._gallery)} exceeds MAX_GALLERY_SIZE=5"
    )
