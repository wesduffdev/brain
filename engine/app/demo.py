"""Watch the minimal being drift — and take fright. This is the observable end
of the slice: the being starts calm in a comfortable room, then the room goes
dark, its safety need falls tick by tick, and its dominant emotion turns to
`scared` (fear).

    cd engine
    PYTHONPATH=. python -m app.demo          # 300 ticks from ../config
    PYTHONPATH=. python -m app.demo 600      # 600 ticks

Set CONFIG_ROOT to point at a different config directory.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional

from app.config_service import ConfigService
from app.simulation import Simulation

_DEFAULT_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")


def _fmt(state: Dict) -> str:
    needs = "  ".join(f"{k}={v:>3}" for k, v in sorted(state["needs"].items()))
    return f"[{state['emotion']:>10}]  {needs}"


def main(argv: Optional[List[str]] = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    ticks = int(argv[0]) if argv else 300
    config_root = os.environ.get("CONFIG_ROOT", _DEFAULT_CONFIG_ROOT)

    sim = Simulation(ConfigService.from_files(config_root))
    print(f"tick={sim.current_tick:>4}  {_fmt(sim.state())}   (birth)")

    perceived = sim.state()["perceived"]["objects"]
    if perceived:
        seen = "  ".join(
            f"{obj['objectId']}(conf={obj['confidence']:.2f})" for obj in perceived
        )
        print(f"perceives {len(perceived)} object(s) in the room:  {seen}")

    # Partway through, the room goes dark — a world event, not an action of the
    # being. From then on its contextual safety need falls until fear fires.
    darken_at = max(30, ticks // 5)

    previous_emotion = sim.state()["emotion"]
    for _ in range(ticks):
        if sim.current_tick == darken_at:
            sim.change_environment(light="dark")
            print(f"tick={sim.current_tick:>4}  *** the room goes dark ***")

        state = sim.tick()
        emotion_changed = state["emotion"] != previous_emotion
        # Sample the drift periodically, and always mark an emotion change.
        if emotion_changed or state["tick"] % 30 == 0:
            marker = "  <- emotion change" if emotion_changed else ""
            print(f"tick={state['tick']:>4}  {_fmt(state)}{marker}")
            previous_emotion = state["emotion"]

    final = sim.state()
    print(f"\nfinished at tick {sim.current_tick}; dominant emotion: {final['emotion']}")


if __name__ == "__main__":
    main()
