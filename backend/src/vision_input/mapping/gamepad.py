"""Compatibility migration for pre-gamepad demo profiles. Saved files are not rewritten."""
from .schema import ControlOutput, GamepadAxisOutput, Profile

GAME_AXES = {
    "race.steer1": "left_x", "race.steer2": "right_x", "race.gas": "rt", "race.brake": "lt",
    "pong.left": "left_y", "pong.right": "right_y",
    "fruit.x1": "left_x", "fruit.y1": "left_y", "fruit.x2": "right_x", "fruit.y2": "right_y",
    "hockey.x1": "left_x", "hockey.y1": "left_y", "hockey.x2": "right_x", "hockey.y2": "right_y",
    "survival.x": "left_x", "survival.y": "left_y",
}


def gamepad_profile(p: Profile) -> Profile:
    legacy = {GAME_AXES[m.output.name] for m in p.mappings
              if isinstance(m.output, ControlOutput) and m.output.name in GAME_AXES}
    if not legacy:
        return p
    mappings = [m.model_copy(update={"output": GamepadAxisOutput(axis=GAME_AXES[m.output.name])})
                if isinstance(m.output, ControlOutput) and m.output.name in GAME_AXES else m for m in p.mappings]
    # Old per-game channels could coexist. Keep the most recently assigned owner
    # on each migrated standard axis instead of adding opposing game controls.
    seen = set()
    kept = []
    for m in reversed(mappings):
        if isinstance(m.output, GamepadAxisOutput) and m.output.axis in legacy:
            if m.output.axis in seen:
                continue
            seen.add(m.output.axis)
        kept.append(m)
    return p.model_copy(update={"mappings": list(reversed(kept))})
