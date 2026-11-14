"""Exercise the real Tk event loop with synthetic files, without user dialogs."""

import os
import time
import tkinter as tk
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from partage_clair.core import Box, Document
from partage_clair.gui import App

pytestmark = pytest.mark.skipif(os.name != 'nt' and not os.environ.get('DISPLAY'),
                                reason='Tk requires a display; Linux CI uses xvfb-run.')


def wait(root, predicate):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return
        time.sleep(.01)
    pytest.fail('Tk operation did not complete')


@pytest.fixture(scope='module')
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


def cleanup(root, app):
    app.worker.stop()
    app.worker.thread.join(timeout=10)
    for callback in root.tk.call('after', 'info'):
        root.after_cancel(callback)
    if app.preview:
        app.preview.close()
    for child in root.winfo_children():
        child.destroy()


def test_real_event_loop_navigation_export_and_responsiveness(tmp_path, monkeypatch, tk_root):
    source = tmp_path / 'source.pdf'
    output = tmp_path / 'shared.pdf'
    writer = PdfWriter()
    writer.add_blank_page(300, 400)
    writer.add_blank_page(400, 300)
    writer.write(source)
    errors = []
    monkeypatch.setattr('partage_clair.gui.messagebox.askokcancel', lambda *_: True)
    monkeypatch.setattr('partage_clair.gui.messagebox.showerror', lambda *args: errors.append(args))
    monkeypatch.setattr('partage_clair.gui.filedialog.asksaveasfilename', lambda **_: str(output))
    root = tk_root
    root.report_callback_exception = lambda *args: errors.append(args)
    app = App(root)
    try:
        app.load(source)
        wait(root, lambda: app.doc is not None and not app.busy)
        assert app.doc.pages == 2
        app.move(1)
        wait(root, lambda: app.page == 1 and not app.busy)
        app.set_zoom(2)
        wait(root, lambda: not app.busy)
        assert app.preview_dpi == 180
        app.boxes = [Box(2, 0, 0, .5, .5)]
        original = Document.export

        def slower(self, *args, **kwargs):
            time.sleep(.15)
            return original(self, *args, **kwargs)
        monkeypatch.setattr(Document, 'export', slower)
        ticks = []

        def heartbeat():
            ticks.append(True)
            if app.busy:
                root.after(10, heartbeat)
        app.export()
        root.after(10, heartbeat)
        wait(root, lambda: not app.busy)
        assert len(ticks) >= 3, 'The UI loop must remain alive while the worker exports.'
        assert app.last_output == Path(output)
        assert not app.dirty()
        assert len(PdfReader(output).pages) == 2
        app.remember()
        app.boxes.append(Box(1, 0, 0, .2, .2))
        app.refresh_status()
        assert str(app.output_button['state']) == 'disabled'
        assert not errors
    finally:
        cleanup(root, app)


def test_detection_needs_validation_and_group_cannot_be_partially_removed(tmp_path, monkeypatch, tk_root):
    from tests.test_detection import make_pdf
    source = make_pdf(tmp_path / 'names.pdf', ['Nom : Alice Dupont', 'ALICE et DUPONT signent.'])
    monkeypatch.setattr('partage_clair.gui.messagebox.askokcancel', lambda *_: True)
    def no_ocr(_self):
        raise RuntimeError('Test only native text; real OCR is exercised separately.')
    monkeypatch.setattr('partage_clair.ocr.LocalOcr.__init__', no_ocr)
    root = tk_root
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    app = App(root)
    try:
        app.load(source)
        wait(root, lambda: app.doc and not app.busy)
        app.detect()
        wait(root, lambda: app.report is not None and not app.busy)
        assert not app.all_boxes() and not app.approved
        finding = next(f for f in app.report.findings if f.value == 'Alice Dupont')
        app.approve_finding(finding)
        assert {b.page for b in app.all_boxes()} == {1, 2}
        assert app.dirty()
        app.selected = 0
        app.delete_mask()
        assert not app.all_boxes() and not app.approved
        app.undo_mask()
        assert {b.page for b in app.all_boxes()} == {1, 2}
        app.redo_mask()
        assert not app.all_boxes()
        assert not errors
    finally:
        cleanup(root, app)
