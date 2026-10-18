"""The viewer's coast after a drag: Android's fling model, and reading the release speed."""

import math

import pytest

from golblick import fling


def test_the_coast_starts_at_the_release_speed():
    """No jolt on letting go: the first instant moves at the speed the pointer did."""
    coast = fling.Fling(1500.0, 0.0)
    dt = 1e-4
    assert coast.offset(dt)[0] / dt == pytest.approx(1500.0, rel=1e-3)


def test_a_slow_drag_barely_carries_on_and_a_fast_one_keeps_turning():
    """Distance grows as speed to about the 1.74th power, so halving the speed leaves about 30%."""
    slow, fast = fling.Fling(1000.0, 0.0), fling.Fling(2000.0, 0.0)
    exponent = fling.DECELERATION / (fling.DECELERATION - 1)
    assert exponent == pytest.approx(1.736, abs=0.001)
    assert slow.distance / fast.distance == pytest.approx(0.5 ** exponent)
    assert slow.duration < fast.duration


def test_it_ends_where_it_said_and_stays_there():
    coast = fling.Fling(0.0, -2500.0)
    assert not coast.done(coast.duration / 2)
    assert coast.offset(coast.duration) == pytest.approx((0.0, -coast.distance))
    assert coast.offset(coast.duration * 3) == coast.offset(coast.duration)
    assert coast.done(coast.duration)


def test_only_the_main_direction_carries_on():
    """A sideways flick a little off level must not drift the horizon afterwards."""
    coast = fling.Fling(-1800.0, 400.0)
    x, y = coast.offset(0.2)
    assert x < 0 and y == 0.0


def test_too_slow_is_a_stop_and_too_fast_is_capped():
    assert fling.Fling(30.0, 0.0).duration == 0.0
    assert fling.Fling(30.0, 0.0).offset(0.1) == (0.0, 0.0)
    assert fling.Fling(9000.0, 0.0).distance == pytest.approx(fling.Fling(fling.MAX_SPEED, 0.0).distance)


def test_a_denser_screen_coasts_the_same_distance_in_inches():
    """The deceleration is physical, so pixels scale with the screen's density."""
    low, high = fling.Fling(800.0, 0.0, dpi=96), fling.Fling(1600.0, 0.0, dpi=192)
    assert high.distance / 192 == pytest.approx(low.distance / 96)
    assert high.duration == pytest.approx(low.duration)


def test_release_speed_is_fitted_over_the_end_of_the_drag():
    steady = [(i / 125, 3 + 900 * i / 125, 40 - 200 * i / 125) for i in range(20)]
    vx, vy = fling.release_velocity(steady)
    assert (vx, vy) == pytest.approx((900.0, -200.0))


def test_a_twitch_at_the_end_of_a_slow_drag_does_not_fling_hard():
    """Two events 2 ms apart, 10 px apart, read 5000 px/s; the fit over 80 ms doesn't."""
    slow = [(i / 125, 100 * i / 125, 0.0) for i in range(20)]
    t, x, _ = slow[-1]
    twitched = slow + [(t + 0.002, x + 10, 0.0)]
    vx, _ = fling.release_velocity(twitched)
    assert vx < 1000 < (10 / 0.002)


def test_a_pointer_that_stopped_before_letting_go_does_not_fling():
    moved = [(i / 125, 900 * i / 125, 0.0) for i in range(10)]
    t, x, y = moved[-1]
    held = moved + [(t + 0.15, x, y)]
    assert fling.release_velocity(held) == (0.0, 0.0)
    assert fling.release_velocity([]) == (0.0, 0.0)


def test_the_viewer_coasts_after_a_quick_drag_and_a_press_stops_it():
    """Through the real widget, with Qt's own events, not by calling the model."""
    pytest.importorskip("PySide6")
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    from golblick import viewer

    app = QApplication.instance() or QApplication([])
    view = viewer.SphereView(fov=75.0)
    view.resize(800, 600)

    left, none = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton

    def send(kind, x, ms):
        button = none if kind == QMouseEvent.Type.MouseMove else left
        held = none if kind == QMouseEvent.Type.MouseButtonRelease else left
        where = QPointF(x, 300)
        event = QMouseEvent(kind, where, where, button, held, Qt.KeyboardModifier.NoModifier)
        event.setTimestamp(ms)
        QApplication.sendEvent(view, event)

    send(QMouseEvent.Type.MouseButtonPress, 100, 1000)
    for step in range(1, 9):                       # 1500 px/s to the right
        send(QMouseEvent.Type.MouseMove, 100 + 15 * step, 1000 + 10 * step)
    send(QMouseEvent.Type.MouseButtonRelease, 220, 1080)
    let_go = view.longitude
    assert view._fling is not None and view._fling_timer.isActive()

    app.processEvents()
    import time

    deadline = time.monotonic() + 0.3
    while time.monotonic() < deadline:
        app.processEvents()
    coasted = view.longitude
    # Dragging right turns the view left (longitude falls), and the coast keeps going that way.
    assert coasted < let_go - 1.0

    send(QMouseEvent.Type.MouseButtonPress, 400, 5000)
    stopped = view.longitude
    deadline = time.monotonic() + 0.1
    while time.monotonic() < deadline:
        app.processEvents()
    assert view.longitude == stopped and view._fling is None
    assert not math.isnan(stopped)
