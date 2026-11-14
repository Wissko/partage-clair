"""Test mouse-to-document geometry without requiring a desktop in CI."""

from types import SimpleNamespace

import pytest

from partage_clair.gui import App


@pytest.fixture
def app():
    instance = App.__new__(App)
    instance.area = (100, 50, 400, 800)
    instance.doc = object()
    instance.page = 1
    instance.boxes = []
    instance.drag = None
    instance.draw = lambda: None
    return instance


def test_reverse_drag_maps_to_page_coordinates(app):
    app.start(SimpleNamespace(x=420, y=690))
    app.finish(SimpleNamespace(x=180, y=210))
    assert len(app.boxes) == 1
    box = app.boxes[0]
    assert box.page == 2
    assert (box.x0, box.y0, box.x1, box.y1) == (.2, .2, .8, .8)


def test_drag_clamps_to_page_and_tiny_clicks_add_no_mask(app):
    app.start(SimpleNamespace(x=101, y=51))
    app.finish(SimpleNamespace(x=101.5, y=51.5))
    assert not app.boxes
    app.start(SimpleNamespace(x=180, y=210))
    app.finish(SimpleNamespace(x=2000, y=2000))
    assert (app.boxes[0].x1, app.boxes[0].y1) == (1, 1)


def test_drag_cannot_start_outside_document(app):
    app.start(SimpleNamespace(x=5, y=5))
    app.finish(SimpleNamespace(x=200, y=300))
    assert not app.boxes
