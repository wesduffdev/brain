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
from app.domain.instinct import REACTION_LABELS
from app.policies import MOTION_FEATURE_NAMES
from app.domain.event import DomainEvent
from app.services.instinct_service import INSTINCT_REACTIONS_TOPIC
from app.services.reaction_response_service import ACTION_EVENTS_TOPIC, ACTION_INTERRUPTED
from app.services.stimulus_service import (
    OBJECT_CONTACTED,
    PERCEPTION_TOPIC,
    SOUND_SPIKE,
)
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


def _run_react(config, *, bus, ticks):
    """Run the wired being (loads models/instinct.pt via the bootstrap) beside a
    no-instinct baseline, printing each tick, and return
    (reacted, interrupted_events, wired_actions, baseline_actions)."""
    baseline = Simulation(config)  # no instinct chain -> the decided-action reference
    interrupted: List[DomainEvent] = []
    bus.subscribe(ACTION_EVENTS_TOPIC, interrupted.append)
    reacted = 0
    with build_simulation(config, event_publisher=bus, event_consumer=bus) as sim:
        for _ in range(ticks):
            a = sim.tick()
            baseline.tick()
            if a.get("reaction") is not None:
                reacted += 1
            broke_off = a.get("reaction") is not None and a.get("currentAction") is None
            _print_action(a)
            if broke_off:
                print("           ^^^ action BROKEN OFF — the flinch cancelled it (outcome never landed)")
        wired_actions = len(sim.interactions())
    interrupts = [e for e in interrupted if e.event_type == ACTION_INTERRUPTED]
    return reacted, interrupts, wired_actions, len(baseline.interactions())


def _react_demo(config_root: str, ticks: int = 8) -> None:
    """INTERRUPT-ON demonstration: the RUNNING being VISIBLY REACTS to a fast,
    body-bound approach (the red ball) AND now BREAKS OFF its action when the flinch
    is strong enough — the first time instinct changes what the being DOES. Two runs
    beside a no-instinct baseline show the safety-gated cancellation:

      1. shipped floor (empty) — the flinch CANCELS the being's action: its outcome
         never lands and an `ActionInterrupted` is emitted on the durable action topic;
      2. a floor that FORBIDS the protective `withdraw` on the ball — the interruption
         is SUPPRESSED, so the being completes its action. The floor is never bypassed.

    allow_interrupt is ON in the shipped config; the SafetyService floor is the sole
    arbiter. The bootstrap loads the trained instinct predictor from
    `models/instinct.pt`; with no torch or no artifact the chain is inert and the run
    says so (train it with `python -m app.ml.train_instinct_model`)."""
    base = ConfigService.from_files(config_root).with_room_contents(["obj_red_ball"])
    label = base.object_catalog()["obj_red_ball"].developer_label or "obj_red_ball"
    print(f"the being sits alone; then a fast, body-bound {label} rushes straight at it.")
    print("instinct: visual_only ON, allow_interrupt is ON — a strong flinch may break off a SAFE action.\n")

    # 1) shipped floor (empty): the flinch may cancel the being's action.
    print(f"--- [1] shipped floor: wired being (allow_interrupt ON) beside a baseline, {ticks} ticks ---")
    reacted, interrupts, wired_acts, base_acts = _run_react(
        base, bus=InMemoryEventBus(), ticks=ticks
    )
    print()
    if reacted:
        print(f"the being VISIBLY REACTED on {reacted} tick(s) (`state().reaction` surfaced, emotion read `scared`).")
        if interrupts:
            first = interrupts[0].payload
            print(
                f"INTERRUPTED: {len(interrupts)} action(s) broken off by a flinch — "
                f"first at tick {first['tick']} ({first['action']}). The wired being took "
                f"{wired_acts} action(s) vs {base_acts} for the no-instinct baseline: the "
                f"cancelled action's outcome never landed."
            )
        else:
            print("no interruption fired — the flinch never cleared the intensity threshold this run.")
    else:
        print(
            "the instinct chain was inert — no trained model loaded. Run "
            "`PYTHONPATH=. python -m app.ml.train_instinct_model` to produce "
            "models/instinct.pt, then retry."
        )

    # 2) a floor that forbids the protective withdraw on the ball: SUPPRESSION.
    print()
    print(f"--- [2] SUPPRESSION: the floor FORBIDS `withdraw` on the ball, {ticks} ticks ---")
    guarded = base.with_safety_rules(
        [{"action": "withdraw", "blocked_property": "round", "reason": "breaking off here is invalid"}]
    )
    reacted2, interrupts2, wired2, base2 = _run_react(
        guarded, bus=InMemoryEventBus(), ticks=ticks
    )
    print()
    if reacted2 and not interrupts2:
        print(
            f"the being still FELT the flinch ({reacted2} tick(s)) but the floor SUPPRESSED "
            f"the interruption: {wired2} action(s) taken, same as the baseline's {base2} — "
            f"the being completed its action and the safety floor was never bypassed."
        )
    elif interrupts2:
        print("UNEXPECTED: an interruption fired despite the floor forbidding the protective response.")
    else:
        print("the instinct chain was inert — train models/instinct.pt to see suppression.")


def _sensory_demo(config_root: str, ticks: int = 8) -> None:
    """SENSORY-STIM demonstration: real SOUND and TOUCH signals now drive the
    instinct chain. The running being (loads `models/instinct.pt` via the
    bootstrap) is shown beside a no-instinct baseline. A fast ball RUSHES IN and
    REACHES the body (a CONTACT -> the being WITHDRAWS), and partway through the
    room fills with a sudden UNKNOWN sound (a spike -> the being FREEZES) —
    reactions the motion-only stimulus could never produce, because
    sound_spike_intensity / touch_intensity were stubbed 0.0 until this slice.
    With no torch or no artifact the chain is inert and the run says so."""
    base = ConfigService.from_files(config_root).with_room_contents(["obj_red_ball"])
    print("the being sits alone; a ball rushes in and REACHES it, then a sudden UNKNOWN sound fills the room.")
    print("SENSORY-STIM: sound_spike_intensity + touch_intensity now populate the frozen 14-feature stimulus.\n")

    bus = InMemoryEventBus()
    perception: List[DomainEvent] = []
    reactions: List[DomainEvent] = []
    bus.subscribe(PERCEPTION_TOPIC, perception.append)
    bus.subscribe(INSTINCT_REACTIONS_TOPIC, reactions.append)
    baseline = Simulation(base)  # no instinct chain -> the reference

    sound_at = max(3, ticks - 3)
    print(f"--- the wired being beside a no-instinct baseline, {ticks} ticks ---")
    with build_simulation(base, event_publisher=bus, event_consumer=bus) as sim:
        for t in range(1, ticks + 1):
            state = sim.tick()
            baseline.tick()
            _print_action(state)
            if t == sound_at:
                print(f"\ntick={sim.current_tick:>4}  *** a sudden UNKNOWN sound fills the room ***\n")
                sim.change_environment(sound="unknown_sound")

    spikes = [e for e in perception if e.event_type == SOUND_SPIKE]
    contacts = [e for e in perception if e.event_type == OBJECT_CONTACTED]
    triggered = [
        (e.payload["tick"], e.payload["reaction"], e.payload["intensity"])
        for e in reactions
        if e.payload.get("triggered")
    ]
    print()
    if not reactions and not spikes and not contacts:
        print(
            "the instinct chain was inert -- no trained model loaded. Run "
            "`PYTHONPATH=. python -m app.ml.train_instinct_model` to produce "
            "models/instinct.pt, then retry."
        )
        return
    print(f"sensory stimuli on the bus: {len(spikes)} sound spike(s), {len(contacts)} contact(s).")
    for label in ("flinch", "withdraw", "freeze"):
        hits = [t for (t, r, _) in triggered if r == label]
        if hits:
            intensity = next(i for (t, r, i) in triggered if r == label)
            print(f"  the being {label.upper()} on tick(s) {hits} (intensity ~{intensity:.2f}).")
    fired = sorted({r for (_, r, _) in triggered})
    baseline_reacted = 0  # baseline has no instinct chain, so it never reacts
    print(
        f"reactions triggered: {fired or 'none'} -- the no-instinct baseline reacted on "
        f"{baseline_reacted} tick(s)."
    )
    if "freeze" not in fired:
        print("NOTE: freeze did not clear its threshold on the trained model's sound features this run.")
    if "withdraw" not in fired:
        print("NOTE: withdraw did not clear its threshold on the trained model's contact features this run.")


class _FixedInstinctPredictor:
    """A torch-free `InstinctPredictorPort` for the temperament demo: a CONSTANT flinch
    probability, so what changes whether the being fires is the DRIFT of its own
    threshold (habituation / sensitization), not the model. Stands in for
    models/instinct.pt so the demo runs with no torch and no artifact."""

    def __init__(self, flinch: float) -> None:
        self._flinch = flinch

    def predict_reactions(self, stimulus):
        from app.domain.instinct import REACTION_LABELS
        from app.ports.instinct import InstinctPrediction

        reactions = {label: 0.0 for label in REACTION_LABELS}
        reactions["flinch"] = self._flinch
        reactions["ignore"] = 1.0 - self._flinch
        return InstinctPrediction(reactions=reactions, intensity=self._flinch)


def _temperament_config(*, contains, harmful, flinch_threshold=0.5):
    """A minimal one-object world for the temperament demo. `harmful` decides whether
    the object hurts on touch (drives the being's `pain` need, the harm cue)."""
    outcomes = ["pleasant", "causes_pain", "scary"]
    touch_outcomes = {"hot": ["causes_pain", "scary"]} if harmful else {"soft": ["pleasant"]}
    props = ["hot"] if harmful else ["soft"]
    actions = {
        "actions": {
            "observe": {"affordance": "look", "utility": {"base": 1.0, "needs": {}, "emotions": {}},
                        "expected_outcomes": ["pleasant"], "reason": "a careful look"},
            "touch": {"affordance": "touch", "utility": {"base": 10.0, "needs": {}, "emotions": {}},
                      "expected_outcomes": ["pleasant"], "property_outcomes": touch_outcomes,
                      "reason": "reaching out to touch"},
        }
    }
    tick_rates = {"tick": {"duration_ms": 1000},
                  "needs": {"pain": {"direction": "decrease", "amount": 2, "every_ticks": 6,
                                     "min": 0, "max": 100, "start": 0},
                            "safety": {"direction": "contextual", "amount": 0, "every_ticks": 1,
                                       "min": 0, "max": 100, "start": 80},
                            "comfort": {"direction": "contextual", "amount": 0, "every_ticks": 1,
                                        "min": 0, "max": 100, "start": 70}}}
    return ConfigService.from_dict(
        tick_rates,
        {"rules": [], "default": "calm"},
        rooms={"room": {"id": "room_001", "contains": list(contains)}},
        objects={"properties": props, "affordances": ["look", "touch"],
                 "objects": {contains[0]: {"developerLabel": "obj", "properties": props,
                                           "affordances": ["look", "touch"]}}},
        actions=actions,
        safety={"rules": []},
        outcome={"labels": outcomes, "context_features": []},
        outcome_effects={"effects": {"causes_pain": {"pain": 7, "safety": -20, "comfort": -10},
                                     "scary": {"safety": -10}, "pleasant": {"comfort": 3}}},
        instinct={"feature_order": list(MOTION_FEATURE_NAMES), "labels": list(REACTION_LABELS),
                  "runtime": {"enabled": True},
                  "reaction": {"shadow": True, "thresholds": {"flinch": flinch_threshold},
                               "cooldowns": {"flinch": 0}, "visual_only": True,
                               "temperament": {"habituate_rate": 0.2, "sensitize_rate": 0.2,
                                               "floor": 0.05, "ceiling": 0.98}}},
        motion={"normalization": {"max_distance": 10.0, "max_speed": 5.0, "max_acceleration": 5.0,
                                  "max_time_to_contact": 10.0, "max_size": 1.0, "max_size_change_rate": 1.0},
                "approach": {"min_closing_speed": 0.0},
                "objects": {contains[0]: {"position": [50.0, 0.0], "velocity": [-0.5, 0.0], "size": 0.3}}},
    )


def _temperament_demo(config_root: str, ticks: int = 12) -> None:
    """INS-TEMPERAMENT demonstration: identical stimuli provoke DIFFERENT reactions as
    the being accrues experience. Torch-free — a fixed fake predictor stands in for
    models/instinct.pt, so the DRIFT of the being's own thresholds is what changes.

      1. HABITUATION — a harmless object rushes at the being every tick. It flinches at
         first, then STOPS as its effective flinch threshold climbs (it learns the
         approach is nothing to fear).
      2. SENSITIZATION — the being reaches out and is HURT (its `pain` spikes). A MILD
         approach that it ignored at first now makes it FLINCH — being hurt made it
         jumpier."""
    from app.bootstrap import build_simulation

    def run(config, predictor, label):
        bus = InMemoryEventBus()
        reactions: List[DomainEvent] = []
        bus.subscribe(INSTINCT_REACTIONS_TOPIC, reactions.append)
        by_tick = {}
        with build_simulation(config, event_publisher=bus, event_consumer=bus,
                              instinct_predictor=predictor) as sim:
            for _ in range(ticks):
                sim.tick()
                fired = [r.payload["tick"] for r in reactions if r.payload.get("triggered")]
                by_tick = {r.payload["tick"]: r.payload.get("triggered", False) for r in reactions}
                thr = sim.reaction_thresholds().get("flinch")
                t = sim.current_tick
                mark = "FLINCH" if by_tick.get(t) else "  --  "
                pain = sim.state()["needs"].get("pain", 0)
                print(f"  tick={t:>3}  [{mark}]  flinch-threshold={thr:0.3f}  pain={pain:>3}")
        fired_ticks = sorted(k for k, v in by_tick.items() if v)
        return fired_ticks

    print("INS-TEMPERAMENT: the being's instinct becomes ADAPTIVE — reaction thresholds")
    print("drift from experience. (torch-free: a fixed fake predictor stands in for the model.)\n")

    print(f"--- [1] HABITUATION: a HARMLESS object rushes in every tick, {ticks} ticks ---")
    print("    fixed flinch probability 0.70; static threshold starts at 0.50\n")
    habituated = run(_temperament_config(contains=["obj_ball"], harmful=False),
                     _FixedInstinctPredictor(0.70), "habituation")
    print()
    if habituated:
        print(f"    flinched on ticks {habituated}, then STOPPED — the harmless approach "
              f"no longer startles it (habituated).")
    else:
        print("    (no flinch — check config)")

    print()
    print(f"--- [2] SENSITIZATION: a MILD approach (prob 0.45 < threshold 0.50) while the ---")
    print(f"---     being TOUCHES a hot object and is HURT, {ticks} ticks ---\n")
    sensitized = run(_temperament_config(contains=["obj_stove"], harmful=True),
                     _FixedInstinctPredictor(0.45), "sensitization")
    print()
    if sensitized:
        print(f"    the mild approach it first IGNORED now triggers a flinch (ticks {sensitized}) — "
              f"being hurt lowered its thresholds (sensitized).")
    else:
        print("    (no flinch triggered — sensitization did not cross the stimulus this run)")


def main(argv: Optional[List[str]] = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    config_root = os.environ.get("CONFIG_ROOT", _DEFAULT_CONFIG_ROOT)
    # INTERRUPT-ON: `demo react [ticks]` runs the reaction demonstration — the being
    # visibly reacts to a body-bound approach AND breaks off a safe action when the
    # flinch is strong enough (safety-gated), instead of the single-object walk.
    if any(token.strip().lstrip("-").lower() == "temperament" for token in argv):
        temperament_ticks = next(
            (int(t.strip().lstrip("-")) for t in argv if t.strip().lstrip("-").isdigit()), 12
        )
        _temperament_demo(config_root, ticks=temperament_ticks)
        return
    if any(token.strip().lstrip("-").lower() == "react" for token in argv):
        react_ticks = next(
            (int(t.strip().lstrip("-")) for t in argv if t.strip().lstrip("-").isdigit()), 8
        )
        _react_demo(config_root, ticks=react_ticks)
        return
    # SENSORY-STIM: `demo sensory [ticks]` shows the being FREEZE at a sudden
    # loud/unknown sound and WITHDRAW from a contact — the sound/touch sources this
    # slice adds — beside a no-instinct baseline.
    if any(token.strip().lstrip("-").lower() == "sensory" for token in argv):
        sensory_ticks = next(
            (int(t.strip().lstrip("-")) for t in argv if t.strip().lstrip("-").isdigit()), 8
        )
        _sensory_demo(config_root, ticks=sensory_ticks)
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
