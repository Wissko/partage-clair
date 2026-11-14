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
    instance.approved = {}
    instance.choices = {}
    instance.review = None
    instance.history, instance.future = [], []
    instance.busy, instance.selected = None, None
    instance.canvas = SimpleNamespace(canvasx=lambda x: x, canvasy=lambda y: y,
                                     focus_set=lambda: None)
    instance.drag = None
    instance.draw = lambda: None
    instance.refresh_status = lambda: None
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


def test_scrolled_coordinates_keep_correct_mask_position(app):
    app.canvas.canvasx = lambda x: x + 100
    app.canvas.canvasy = lambda y: y + 200
    app.start(SimpleNamespace(x=80, y=10))
    app.finish(SimpleNamespace(x=320, y=490))
    box = app.boxes[0]
    assert (box.x0, box.y0, box.x1, box.y1) == (.2, .2, .8, .8)


def test_delete_undo_redo_and_new_edit_clear_future(app):
    app.start(SimpleNamespace(x=180, y=210))
    app.finish(SimpleNamespace(x=420, y=690))
    original = list(app.boxes)
    app.delete_mask()
    assert not app.boxes
    app.undo_mask()
    assert app.boxes == original
    app.redo_mask()
    assert not app.boxes
    app.undo_mask()
    app.undo_mask()
    assert not app.boxes
    app.start(SimpleNamespace(x=200, y=220))
    app.finish(SimpleNamespace(x=300, y=400))
    assert not app.future


def test_windows_azerty_physical_zero_key_resets_zoom(app, monkeypatch):
    monkeypatch.setattr('partage_clair.gui.sys.platform', 'win32')
    values = []
    app.set_zoom = lambda value: values.append(value)
    widget = SimpleNamespace(winfo_class=lambda: 'Canvas')
    app.platform_shortcut(SimpleNamespace(keycode=48, widget=widget))
    assert values == [1]
