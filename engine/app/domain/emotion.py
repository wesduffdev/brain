"""The being's emotion vocabulary.

One emotion is dominant at a time. This module is just the closed set of
labels plus which of them this slice can actually reach — it holds no logic.
EmotionService (in services/) does the deriving.
"""
from __future__ import annotations

# The full vocabulary the being may eventually feel.
EMOTIONS = frozenset(
    {
        "happy",
        "curious",
        "hungry",
        "sleepy",
        "scared",  # fear
        "frustrated",
        "calm",
        "excited",
        "comforted",
    }
)

# The subset reachable from internal need state alone (this slice). The rest —
# happy, excited, comforted — need an external event and arrive with the
# object/interaction slice.
FROM_NEEDS = frozenset(
    {
        "scared",
        "hungry",
        "sleepy",
        "frustrated",
        "curious",
        "calm",
    }
)
