"""Exercise the real Tk event loop with synthetic files, without user dialogs."""

import gc
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
    gc.collect()


@pytest.fixture(autouse=True)
def collect_gui_cycles_on_main_thread(tk_root):
    yield
    # Test Apps contain Tk variable/callback cycles. Reclaim them here while
    # their Tcl interpreter still exists, never later on a document worker.
    gc.collect()


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
        assert app.report is not None
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


def test_score_review_and_audit_become_stale_after_edits_or_new_search(tmp_path, monkeypatch, tk_root):
    from tests.test_detection import make_pdf
    source = make_pdf(tmp_path / 'source.pdf', ['Nom : Alice Dupont'])
    target = tmp_path / 'copy.pdf'
    monkeypatch.setattr('partage_clair.gui.messagebox.askokcancel', lambda *_: True)
    monkeypatch.setattr('partage_clair.gui.filedialog.asksaveasfilename', lambda **_: str(target))
    errors = []
    monkeypatch.setattr('partage_clair.gui.messagebox.showerror', lambda *args: errors.append(args))
    root = tk_root
    root.report_callback_exception = lambda *args: errors.append(args)
    app = App(root)
    try:
        assert app.get_preparation_score().value is None
        app.load(source)
        wait(root, lambda: app.doc and not app.busy)
        assert app.report is not None
        assert not app.all_boxes()
        app.show_assurance()
        panel = app.assurance_window
        panel.purpose.set('Partager un exemple sans identité')
        panel.audience.set('Publication publique')
        for check in panel.checks.values():
            check.set(True)
        panel.validate_review()
        assert app.criteria_snapshot == app.review_signature()
        app.approve_finding(next(f for f in app.report.findings if f.value == 'Alice Dupont'))
        assert app.criteria_snapshot is None
        panel.validate_review()
        app.export()
        wait(root, lambda: app.last_output and not app.busy)
        assert app.current_audit() is None
        app.audit_copy()
        wait(root, lambda: app.audit is not None and not app.busy)
        assert app.current_audit().passed
        panel.copy_read.set(True)
        panel.validate_copy()
        assert app.copy_snapshot == app.review_signature()
        assert app.get_preparation_score().value == 95
        # A timestamp/content change of the controlled file must remove its score credit.
        target.touch()
        assert app.current_audit() is None
        assert app.get_preparation_score().value <= 69
        app.find_name('Dupont', exact=True)
        wait(root, lambda: not app.busy)
        assert app.criteria_snapshot is None and app.copy_snapshot is None and app.current_audit() is None
        assert next(f for f in app.report.findings if f.kind == 'Texte ajouté')
        assert len(app.approved) == 1, 'Search must not approve or apply a new mask.'
        assert not errors
    finally:
        cleanup(root, app)


def test_generalisation_requires_explicit_validation_and_undo_restores_method(tmp_path, monkeypatch, tk_root):
    from tests.test_detection import make_pdf
    source = make_pdf(tmp_path / 'age.pdf', ['Nom : Alice Dupont\nAge : 36 ans'])
    target = tmp_path / 'generalised.pdf'
    errors = []
    monkeypatch.setattr('partage_clair.gui.messagebox.askokcancel', lambda *_: True)
    monkeypatch.setattr('partage_clair.gui.messagebox.showerror', lambda *args: errors.append(args))
    monkeypatch.setattr('partage_clair.gui.filedialog.asksaveasfilename', lambda **_: str(target))
    root = tk_root
    root.report_callback_exception = lambda *args: errors.append(args)
    app = App(root)
    try:
        app.load(source)
        wait(root, lambda: app.doc and not app.busy)
        assert app.report is not None
        age = next(f for f in app.report.findings if f.kind == 'Âge')
        app.review.tree.selection_set(age.id)
        root.update()
        app.review.method.set('Réduire la précision')
        app.review.method_detail()
        assert not app.approved and not app.choices, 'Selecting a method is not approval.'
        app.review.accept()
        assert app.choices[age.id].text == '30-39 ans'
        assert app.redaction_plan()[1] and app.get_preparation_score().indirect_remaining >= 1
        app.undo_mask()
        assert not app.choices and not app.approved
        app.redo_mask()
        assert app.choices[age.id].text == '30-39 ans'
        app.export()
        wait(root, lambda: app.last_output and not app.busy)
        app.audit_copy()
        wait(root, lambda: app.audit is not None and not app.busy)
        assert app.audit.labels_ok and app.audit.masks_ok
        from partage_clair.methods import MethodChoice
        name = next(f for f in app.report.findings if f.value == 'Alice Dupont')
        app.approve_finding(name, MethodChoice('pseudonym', 'Personne B'))
        app.review.tree.selection_set(age.id)
        root.update()
        assert str(app.review.alias['state']) == 'disabled'
        app.review.tree.selection_set(name.id)
        root.update()
        assert app.review.alias.get() == 'Personne B'
        assert not errors
    finally:
        cleanup(root, app)


def test_open_autoscans_once_and_never_carries_approval_to_next_document(tmp_path, monkeypatch, tk_root):
    from PIL import Image, ImageDraw, ImageFont

    from tests.test_detection import make_pdf
    source = make_pdf(tmp_path / 'first.pdf', ['Nom : Alice Dupont', 'ALICE et DUPONT signent.'])
    image = Image.new('RGB', (900, 160), 'white')
    ImageDraw.Draw(image).text((25, 35), 'Nom : Alice Dupont', fill='black', font=ImageFont.load_default(size=34))
    second = tmp_path / 'second.png'
    image.save(second)
    image.close()
    errors = []
    monkeypatch.setattr('partage_clair.gui.messagebox.showerror', lambda *args: errors.append(args))
    root = tk_root
    app = App(root, initial_path=source)
    calls = []
    original = app.worker.submit

    def submit(operation, **arguments):
        calls.append(operation)
        return original(operation, **arguments)
    app.worker.submit = submit
    try:
        wait(root, lambda: app.report is not None and not app.busy)
        assert calls.count('scan') == 1
        assert not app.all_boxes() and not app.approved and not app.choices and not app.dirty()
        finding = next(f for f in app.report.findings if f.value == 'Alice Dupont')
        assert finding.pages == (1, 2)
        app.move(1)
        wait(root, lambda: app.page == 1 and not app.busy)
        app.set_zoom(2)
        wait(root, lambda: not app.busy)
        assert calls.count('scan') == 1, 'Navigation and zoom must not trigger another scan.'
        app.approve_finding(finding)
        assert app.approved
        app.load(second)
        wait(root, lambda: app.doc.kind == 'image' and app.report is not None and not app.busy)
        assert calls.count('scan') == 2 and app.report.ocr_pages == 1
        assert finding.id in {f.id for f in app.report.findings}
        assert not app.approved and not app.all_boxes() and not app.choices and not app.dirty()
        old_report = app.report
        app.load(tmp_path / 'missing.pdf')
        wait(root, lambda: not app.busy)
        assert len(errors) == 1 and calls.count('scan') == 2
        assert app.report is old_report, 'A failed open must not replace or rescan the existing document.'
    finally:
        cleanup(root, app)


def test_cancel_automatic_scan_does_not_restart_and_manual_retry_is_available(tmp_path, monkeypatch, tk_root):
    from partage_clair.core import ExportCancelled
    from partage_clair.detection import scan
    from tests.test_detection import make_pdf
    source = make_pdf(tmp_path / 'source.pdf', ['Nom : Alice Dupont'])
    started = []

    def cancellable(document, **arguments):
        started.append(True)
        if len(started) == 1:
            while not arguments['cancel'].wait(.01):
                pass
            raise ExportCancelled('Analyse annulée pour ce test.')
        arguments['use_ocr'] = False
        return scan(document, **arguments)
    monkeypatch.setattr('partage_clair.detection.scan', cancellable)
    errors = []
    monkeypatch.setattr('partage_clair.gui.messagebox.showerror', lambda *args: errors.append(args))
    root = tk_root
    app = App(root, initial_path=source)
    try:
        wait(root, lambda: app.busy == 'scan' and started)
        assert str(app.cancel_button['state']) == 'normal'
        app.cancel_export()
        wait(root, lambda: not app.busy)
        assert len(started) == 1 and app.report is None and not app.all_boxes()
        app.move(0)
        wait(root, lambda: not app.busy)
        assert len(started) == 1
        app.detect()
        wait(root, lambda: app.report is not None and not app.busy)
        assert len(started) == 2 and not app.approved and not app.choices
        assert not errors
    finally:
        cleanup(root, app)


def test_category_picker_dictionary_and_scope_changes_keep_human_validation(tmp_path, monkeypatch, tk_root):
    from partage_clair.detection import scan
    from partage_clair.detection_options import ALL_CATEGORIES
    from tests.test_detection import make_pdf
    source = make_pdf(tmp_path / 'business.pdf', [
        'Nom : Alice Dupont\nClient : Orion Fictif\nMail : alice@example.test\nProjet Albatros',
        'ALICE et DUPONT\nORION FICTIF\nPROJET ALBATROS'])

    def native(document, **arguments):
        arguments['use_ocr'] = False
        return scan(document, **arguments)
    monkeypatch.setattr('partage_clair.detection.scan', native)
    errors = []
    monkeypatch.setattr('partage_clair.gui.messagebox.showerror', lambda *args: errors.append(args))
    root = tk_root
    app = App(root)
    try:
        app.show_detection_options()
        picker = app.detection_window
        assert len(picker.variables) == len(ALL_CATEGORIES)
        assert all(v.get() for v in picker.variables.values())
        for key, variable in picker.variables.items():
            variable.set(key == 'emails')
        picker.apply()
        assert app.detection_window is None and app.detection_options.categories == ('emails',)
        app.load(source)
        wait(root, lambda: app.report is not None and not app.busy)
        assert {f.kind for f in app.report.findings} == {'E-mail'}
        assert not app.approved and not app.all_boxes()
        app.show_detection_options()
        picker = app.detection_window
        picker.select_all()
        picker.terms.insert('1.0', 'projet albatros\nabsent fictif')
        picker.apply()
        assert app.report is None and app.get_preparation_score().value is None
        wait(root, lambda: app.report is not None and not app.busy)
        phrase = next(f for f in app.report.findings if f.kind == 'Texte ajouté')
        assert phrase.pages == (1, 2)
        assert not app.approved and not app.choices and not app.all_boxes()
        finding = next(f for f in app.report.findings if f.kind == 'Nom' and f.value == 'Alice Dupont')
        app.approve_finding(finding)
        approved_state = app.mask_state()
        app.criteria_snapshot = app.review_signature()
        app.show_detection_options()
        picker = app.detection_window
        for key, variable in picker.variables.items():
            variable.set(key == 'emails')
        picker.terms.delete('1.0', 'end')
        picker.apply()
        assert app.report is None and app.criteria_snapshot is None
        wait(root, lambda: app.report is not None and not app.busy)
        assert app.report.categories == ('emails',)
        assert app.mask_state() == approved_state
        assert {f.kind for f in app.report.findings} == {'E-mail', 'Nom'}
        assert app.get_preparation_score().value <= 49
        assert 'partiel' in app.scope_hint.get()
        app.revoke_finding(finding.id)
        assert not app.all_boxes()
        app.undo_mask()
        assert app.mask_state() == approved_state
        app.load(source)
        wait(root, lambda: app.report is not None and not app.busy)
        assert not app.approved and not app.all_boxes()
        assert app.detection_options.categories == ('emails',)
        assert {f.kind for f in app.report.findings} == {'E-mail'}
        assert not errors
    finally:
        cleanup(root, app)
