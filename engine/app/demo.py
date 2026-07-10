"""Watch the being decide — and stay safe. This is the observable end of the
slice: each tick the being scores its options and takes ONE action toward an
object, with a stated reason. A hot object sits in the room the whole time and is
NEVER touched: safety hard-blocks it no matter how the utility falls. Partway
through, the room goes dark, safety drains, and the curious explorer turns
fearful and withdraws.

    cd engine
    PYTHONPATH=. python -m app.demo          # 120 ticks from ../config
    PYTHONPATH=. python -m app.demo 300      # 300 ticks

Set CONFIG_ROOT to point at a different config directory.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional

from app.config_service import ConfigService
from app.simulation import Simulation

_DEFAULT_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")


def _hot_object_ids(sim: Simulation) -> List[str]:
    """The ids of objects the being perceives as hot — the ones safety protects."""
    return [
        obj["objectId"]
        for obj in sim.state()["perceived"]["objects"]
        if "hot" in obj.get("properties", [])
    ]


def _print_action(state: Dict) -> None:
    action = state.get("currentAction")
    line = f"tick={state['tick']:>4}  [{state['emotion']:>8}]  "
    if action is None:
        print(line + "(resting — nothing to do)")
    else:
        print(line + f"{action['type']:>8} -> {action['targetId']:<16} | {action['reason']}")


def main(argv: Optional[List[str]] = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    ticks = int(argv[0]) if argv else 120
    config_root = os.environ.get("CONFIG_ROOT", _DEFAULT_CONFIG_ROOT)

    sim = Simulation(ConfigService.from_files(config_root))

    perceived = sim.state()["perceived"]["objects"]
    seen = "  ".join(obj["objectId"] for obj in perceived)
    hot_ids = _hot_object_ids(sim)
    print(f"the being wakes in a room with {len(perceived)} object(s):  {seen}")
    print(f"one is hot and must never be touched:  {', '.join(hot_ids) or '(none)'}\n")

    darken_at = 10

    print("--- a curious explorer decides what to do each tick ---")
    for _ in range(ticks):
        if sim.current_tick == darken_at:
            print(f"\ntick={sim.current_tick:>4}  *** the room goes dark — a world event ***\n")
            sim.change_environment(light="dark")
        _print_action(sim.tick())

    # The proof: over the whole run, no action ever touched or grabbed a hot object.
    unsafe = [
        e
        for e in sim.interactions()
        if e["objectId"] in hot_ids and e["action"] in {"touch", "grab"}
    ]
    touched_hot_at_all = [e for e in sim.interactions() if e["objectId"] in hot_ids]
    print(
        f"\nfinished at tick {sim.current_tick}; dominant emotion: {sim.state()['emotion']}"
    )
    print(f"actions taken: {len(sim.interactions())}")
    print(
        f"actions ON the hot object: {len(touched_hot_at_all)} "
        f"(safe ones like observe/push) — of which touch/grab: {len(unsafe)}"
    )
    assert not unsafe, "SAFETY VIOLATION: a hot object was touched"
    print("safety held: the hot object was never touched or grabbed.")


if __name__ == "__main__":
    main()
