"""Watch the being decide — alone in a room with one object.

Each tick the being scores its options and takes ONE action toward the object,
with a stated reason. By default the object is the hot lamp: nothing hard-blocks
the being from touching it (ADR 0013/0014), so a curious explorer reaches out,
is hurt — a pain/fear spike recorded as `causes_pain` — and afterwards keeps its
distance. Partway through the room goes dark and safety drains further.

Point it at a different object to watch how the being treats that one:

    make demo                    # 300 ticks, the hot lamp (default)
    make demo OBJ=ball           # the red ball
    make demo OBJ=blanket TICKS=200

Or call the script directly (it also accepts `--ball` / `obj_red_ball`, and the
tick count and object in either order):

    cd engine
    PYTHONPATH=. python -m app.demo            # 120 ticks, hot lamp
    PYTHONPATH=. python -m app.demo 300 ball
    PYTHONPATH=. python -m app.demo --blanket

Set CONFIG_ROOT to point at a different config directory.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional, Tuple

from app.bootstrap import build_simulation
from app.config_service import ConfigService

_DEFAULT_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")


def _parse_argv(argv: List[str]) -> Tuple[int, Optional[str]]:
    """Split args into (ticks, object selector), order-independent. A bare
    integer is the tick count; anything else (leading dashes stripped) names the
    object to put in the room. Absent -> (120, None)."""
    ticks = 120
    selector: Optional[str] = None
    for arg in argv:
        token = arg.strip()
        if token.lstrip("-").isdigit():
            ticks = int(token.lstrip("-"))
        elif token:
            selector = token.lstrip("-")
    return ticks, selector


def _default_object_id(config: ConfigService) -> str:
    """The hot lamp is the default — it carries the safety story. Fall back to
    the first catalogued object when no hot object exists."""
    catalog = config.object_catalog()
    for object_id, obj in catalog.items():
        if "hot" in obj.properties:
            return object_id
    if not catalog:
        raise SystemExit("no objects are configured; nothing to demo")
    return next(iter(catalog))


def _print_action(state: Dict) -> None:
    action = state.get("currentAction")
    line = f"tick={state['tick']:>4}  [{state['emotion']:>8}]  "
    if action is None:
        print(line + "(resting — nothing to do)")
    else:
        print(line + f"{action['type']:>8} -> {action['targetId']:<16} | {action['reason']}")


def main(argv: Optional[List[str]] = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    ticks, selector = _parse_argv(argv)
    config_root = os.environ.get("CONFIG_ROOT", _DEFAULT_CONFIG_ROOT)

    config = ConfigService.from_files(config_root)
    object_id = config.resolve_object(selector) if selector else _default_object_id(config)
    obj = config.object_catalog()[object_id]
    is_hot = "hot" in obj.properties

    label = obj.developer_label or object_id
    props = ", ".join(obj.properties) or "no notable properties"
    print(f"the being wakes in a room with one object: {label} ({props})")
    if is_hot:
        print("it is hot — touching it will hurt, but nothing stops the being from trying.\n")
    else:
        print()

    # The bootstrap persists the run when DATABASE_URL is set (events, derived
    # examples, and shadow predictions land in Postgres); with no DB it is the
    # same in-memory being the demo has always shown. The `with` closes the being's
    # DB session when the run finishes, so the demo never leaks one.
    with build_simulation(config.with_room_contents([object_id])) as sim:
        darken_at = 10
        print(f"--- a curious explorer decides what to do each tick, for {ticks} ticks ---")
        for _ in range(ticks):
            if sim.current_tick == darken_at:
                print(f"\ntick={sim.current_tick:>4}  *** the room goes dark — a world event ***\n")
                sim.change_environment(light="dark")
            _print_action(sim.tick())

        events = sim.interactions()
        on_object = [e for e in events if e["objectId"] == object_id]
        print(f"\nfinished at tick {sim.current_tick}; dominant emotion: {sim.state()['emotion']}")
        print(f"actions taken: {len(events)}  (on {label}: {len(on_object)})")

        if is_hot:
            harmful = [e for e in on_object if e["action"] in {"touch", "grab"}]
            felt_pain = any("causes_pain" in e["observedOutcome"] for e in on_object)
            now = sim.state()
            print(f"the being reached out: {len(harmful)} harmful contact(s) with {label}.")
            if felt_pain:
                print(
                    "touching it hurt — recorded as `causes_pain`, so the being can later "
                    "learn hot -> pain."
                )
            print(
                f"felt state now — pain: {now['needs'].get('pain', 0)}, "
                f"safety: {now['needs'].get('safety')}, comfort: {now['needs'].get('comfort')}."
            )
            print(
                "recoverable harm is allowed and learnable — nothing hard-blocked it (ADR 0013/0014)."
            )
        else:
            by_action: Dict[str, int] = {}
            for event in on_object:
                by_action[event["action"]] = by_action.get(event["action"], 0) + 1
            breakdown = ", ".join(f"{a}×{n}" for a, n in sorted(by_action.items())) or "nothing yet"
            print(f"how it engaged {label}: {breakdown}")


if __name__ == "__main__":
    main()
