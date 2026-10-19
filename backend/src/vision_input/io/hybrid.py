"""One-hand object/hand routing. No model calls; only fresh hand observations advance state."""
from __future__ import annotations

import numpy as np

from ..hands.detector import Hand
from ..hands.gestures import GestureOutput, GestureRecognizer, features
from .depth import palm_scale


class HybridRouter:
    CONFIRM_FRAMES = 3
    CONFIRM_S = .06
    LOSS_S = .20

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.source = 'object'
        self.pending: str | None = None
        self.count = 0
        self.since = 0.
        self.last_t: float | None = None
        self.last_seen: float | None = None
        self.palm: np.ndarray | None = None
        self.handedness: str | None = None
        self.armed = False
        self.neutral_n = 0
        self.gestures = GestureRecognizer()
        self.out = GestureOutput('none', False, False, 0., False)
        self.click_latched = {'left': False, 'right': False}
        self.gap: float | None = None
        self.blocked = False
        self.changed = False

    def pick(self, hands: list[Hand], center: tuple[float, float] | None, t: float) -> Hand | None:
        valid = [h for h in hands if np.isfinite(h.points).all() and .015 < palm_scale(h) < .5]
        if not valid:
            return None
        palms = [features(h, self.gestures.cfg).palm for h in valid]
        target = self.palm if self.palm is not None else np.asarray(center) if center is not None else None
        i = int(np.argmin([np.linalg.norm(p - target) for p in palms])) if target is not None else 0
        h = valid[i]
        # Do not adopt a distant second hand when the controlling hand disappears.
        if self.palm is not None and np.linalg.norm(palms[i] - self.palm) > max(.12, 1.5 * palm_scale(h)):
            # After a sustained loss, a sole hand of the same handedness can reinitialize
            # only when no button is held. update() still requires an open neutral pose.
            reacquire = (len(valid) == 1 and h.handedness == self.handedness and
                         self.last_seen is not None and t - self.last_seen > self.LOSS_S and
                         not self.out.left and not self.out.right)
            if not reacquire:
                return None
        return h

    def _cancel(self) -> None:
        self.pending, self.count = None, 0

    def _confirm(self, target: str, t: float) -> bool:
        if self.pending != target:
            self.pending, self.count, self.since = target, 0, t
        self.count += 1
        return self.count >= self.CONFIRM_FRAMES and t - self.since >= self.CONFIRM_S

    def update(self, hand: Hand | None, hand_t: float | None, t: float,
               box: tuple[float, float, float, float] | None, *, detach: float,
               pinch: float, external_down: bool = False) -> GestureOutput:
        self.changed = False
        self.gestures.cfg.pinch_on = pinch
        self.gestures.cfg.pinch_off = pinch * 1.5
        self.gestures.cfg.scroll_gain = 0.
        # Scroll is a delta, never replay it for a duplicated hand observation.
        self.out.scroll = 0.
        if hand is None or hand_t is None:
            self._cancel()
            self.blocked = self.source == 'hand'
            if self.last_seen is None or t - self.last_seen > self.LOSS_S:
                self.armed, self.neutral_n = False, 0
                self.out = self.gestures.update(None, t)
            return self.out
        if self.last_t is not None and hand_t <= self.last_t:
            return self.out
        if self.last_seen is not None and hand_t - self.last_seen > self.LOSS_S:
            self.armed, self.neutral_n = False, 0
            self._cancel()
            self.gestures.reset()
        self.last_t, self.last_seen = hand_t, hand_t
        f = features(hand, self.gestures.cfg)
        self.palm = f.palm.copy()
        self.handedness = hand.handedness
        self.gap = None
        if box is not None:
            b = np.asarray(box)
            # Full hand separation: touching fingertips also prevent premature hand mode.
            self.gap = float(np.min(np.linalg.norm(hand.points - np.clip(hand.points, b[:2], b[2:]), axis=1))) / palm_scale(hand)
        detached = self.gap is not None and self.gap > detach
        near = self.gap is not None and self.gap < detach * .4
        held = self.out.left or self.out.right or external_down
        neutral = f.pinch_index > pinch * 1.5 and f.pinch_middle > pinch * 1.5
        if self.source == 'object':
            self.blocked = detached
            if detached and neutral and not external_down:
                if self._confirm('hand', hand_t):
                    self.source, self.changed = 'hand', True
                    self.armed, self.neutral_n = True, self.CONFIRM_FRAMES
                    self.gestures.reset()
                    self._cancel()
                    self.blocked = False
            else:
                self._cancel()
            self.out = GestureOutput('move', False, False, 0., False, f)
            return self.out
        # A closed pinch keeps the hand source until opened; regripping cannot generate another click.
        if near and not held:
            self.blocked = True
            self.armed, self.neutral_n = False, 0
            self.gestures.reset()
            self.out = GestureOutput('none', False, False, 0., True, f)
            if self._confirm('object', hand_t):
                self.source, self.changed = 'object', True
                self._cancel()
                self.blocked = False
            return self.out
        self._cancel()
        self.blocked = False
        # In the uncertainty band, inhibit NEW presses, but allow a closed pinch to release.
        if not held and (self.gap is None or not detached):
            self.armed, self.neutral_n = False, 0
            self.gestures.reset()
            self.blocked = True
            self.out = GestureOutput('none', False, False, 0., True, f)
            return self.out
        if not self.armed:
            self.neutral_n = self.neutral_n + 1 if neutral else 0
            self.armed = self.neutral_n >= self.CONFIRM_FRAMES
            self.out = GestureOutput('move', False, False, 0., False, f)
            return self.out
        self.out = self.gestures.update(hand, hand_t)
        self.out.scroll = 0.
        if self.out.gesture == 'scroll':
            self.out.gesture = 'move'
        return self.out
