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

from app.adapters.in_memory_event_bus import InMemoryEventBus
from app.bootstrap import build_simulation
from app.config_service import ConfigService
from app.domain.event import DomainEvent
from app.services.instinct_service import INSTINCT_REACTIONS_TOPIC
from app.services.reaction_response_service import ACTION_EVENTS_TOPIC
from app.services.stimulus_service import PERCEPTION_TOPIC
from app.simulation import Simulation

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
    # VISUAL-ON: when the being visibly reacts, show the surfaced reaction alongside
    # the action it still decided (visual-only surfaces + colours emotion; it never
    # interrupts). Absent when the instinct flags are off or nothing is reacting.
    reaction = state.get("reaction")
    suffix = (
        f"   <-- reacts: {reaction['type']} ({reaction['intensity']:.2f})"
        if reaction is not None
        else ""
    )
    if action is None:
        print(line + "(resting — nothing to do)" + suffix)
    else:
        print(line + f"{action['type']:>8} -> {action['targetId']:<16} | {action['reason']}" + suffix)


def _react_demo(config_root: str, ticks: int = 6) -> None:
    """VISUAL-ON demonstration: the RUNNING being VISIBLY REACTS to a fast,
    body-bound approach (the red ball) — it surfaces `state().reaction` and its
    DERIVED emotion shifts to `scared` — while the action it decides stays identical,
    tick for tick, to the SAME being with no instinct chain. Visual-only never
    interrupts (allow_interrupt is off), so the two beings act in lockstep; only the
    felt/expressed layer differs. The bootstrap loads the trained instinct predictor
    from `models/instinct.pt`; with no torch or no artifact the chain is inert and the
    run says so (train it with `python -m app.ml.train_instinct_model`)."""
    config = ConfigService.from_files(config_root).with_room_contents(["obj_red_ball"])
    label = config.object_catalog()["obj_red_ball"].developer_label or "obj_red_ball"
    print(f"the being sits alone; then a fast, body-bound {label} rushes straight at it.\n")

    baseline = Simulation(config)  # no instinct chain -> the decided-action reference
    bus = InMemoryEventBus()
    interrupted: List[DomainEvent] = []
    bus.subscribe(ACTION_EVENTS_TOPIC, interrupted.append)

    reacted = 0
    actions_matched = True
    print(f"--- wired being (visual_only ON) beside a no-instinct baseline, {ticks} ticks ---")
    with build_simulation(config, event_publisher=bus, event_consumer=bus) as sim:
        for _ in range(ticks):
            a = sim.tick()
            b = baseline.tick()
            if a.get("currentAction") != b.get("currentAction"):
                actions_matched = False
            if a.get("reaction") is not None:
                reacted += 1
            _print_action(a)

    print()
    if reacted:
        print(
            f"the being VISIBLY REACTED on {reacted} tick(s): `state().reaction` surfaced "
            f"and its derived emotion read `scared` on the approach."
        )
    else:
        print(
            "the instinct chain was inert — no trained model loaded. Run "
            "`PYTHONPATH=. python -m app.ml.train_instinct_model` to produce "
            "models/instinct.pt, then retry."
        )
    verdict = "IDENTICAL" if actions_matched else "DIFFERENT"
    print(
        f"the decided ACTION was {verdict} to the no-instinct baseline every tick — "
        f"{len(interrupted)} action(s) interrupted (allow_interrupt stays off)."
    )


def main(argv: Optional[List[str]] = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    config_root = os.environ.get("CONFIG_ROOT", _DEFAULT_CONFIG_ROOT)
    # VISUAL-ON: `demo react [ticks]` runs the reaction demonstration (the being
    # visibly reacts to a body-bound approach, action unchanged) instead of the
    # single-object walk.
    if any(token.strip().lstrip("-").lower() == "react" for token in argv):
        react_ticks = next(
            (int(t.strip().lstrip("-")) for t in argv if t.strip().lstrip("-").isdigit()), 6
        )
        _react_demo(config_root, ticks=react_ticks)
        return
    ticks, selector = _parse_argv(argv)

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
    # Put the being's perception on the event bus so we can SEE the approach
    # stimuli it raises as the object moves toward it (WORLD-MOTION, ADR 0027).
    bus = InMemoryEventBus()
    approaches: List[DomainEvent] = []
    reactions: List[DomainEvent] = []
    bus.subscribe(PERCEPTION_TOPIC, approaches.append)
    bus.subscribe(INSTINCT_REACTIONS_TOPIC, reactions.append)
    # Wire perception AND the instinct-reaction stream through ONE shared bus and
    # let the bootstrap load the trained instinct predictor: the deployed runtime
    # drives the perception->instinct->reaction chain LIVE, in shadow (RUNTIME-WIRE).
    # With no torch or no `models/instinct.pt`, the predictor is None and the chain
    # stays inert -- the demo then runs exactly as it did before.
    with build_simulation(
        config.with_room_contents([object_id]),
        event_publisher=bus,
        event_consumer=bus,
    ) as sim:
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
        if approaches:
            nearest = min(
                approaches, key=lambda e: e.payload["features"]["time_to_contact"]
            )
            f = nearest.payload["features"]
            print(
                f"approach stimuli on the bus: {len(approaches)} "
                f"`ObjectApproached` event(s) — nearest had "
                f"trajectory_toward_body={f['trajectory_toward_body']:.2f}, "
                f"time_to_contact={f['time_to_contact']:.2f}."
            )
        else:
            print("approach stimuli on the bus: none (nothing moved toward the being).")

        triggered = [r for r in reactions if r.payload.get("triggered")]
        if reactions:
            print(
                f"instinct chain (shadow): {len(reactions)} reaction event(s) flowed "
                f"perception->instinct->reaction, {len(triggered)} triggered and "
                f"persisted; instinct lag now {sim.instinct_lag()} (no behaviour change)."
            )
        else:
            print(
                "instinct chain: inert -- no trained instinct model loaded "
                "(run `python -m app.ml.train_instinct_model` to produce models/instinct.pt)."
            )

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
