"""Offline frozen-binary smoke check using only generated synthetic documents."""

import json
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter

from . import __version__
from .core import Box, Document, OutputLabel


def check_rules_batch(root, app, folder, result):
    """Exercise the frozen CSV import and batch UI with both AI constructors forbidden."""
    import time
    from unittest.mock import patch

    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    from .detection_options import DetectionOptions

    writer = PdfWriter()
    page = writer.add_blank_page(400, 300)
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({
        NameObject('/F1'): DictionaryObject({NameObject('/Type'): NameObject('/Font'),
            NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})})})
    content = DecodedStreamObject()
    content.set_data(b'BT /F1 18 Tf 35 230 Td (nadia benali signe.) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(content)
    source = folder / 'strict-source.pdf'
    writer.write(source)
    original = source.read_bytes()
    catalog = folder / 'employees.csv'
    catalog.write_text('prenom;nom\nNadia;Benali\n', encoding='utf-8-sig')
    errors, batch = [], None

    def wait(predicate):
        deadline = time.monotonic() + 25
        while not predicate() and not errors and time.monotonic() < deadline:
            root.update()
            time.sleep(.01)
        assert predicate() and not errors

    try:
        with patch('partage_clair.ocr.LocalOcr.__init__', side_effect=RuntimeError('OCR forbidden')) as ocr, \
             patch('partage_clair.ner.LocalNer.__init__', side_effect=RuntimeError('NER forbidden')) as ner, \
             patch('partage_clair.batch_ui.messagebox.showerror', side_effect=lambda *a, **k: errors.append(a)):
            app.show_batch()
            batch = app.batch_window
            batch.set_detection_options(DetectionOptions(mode='rules', profile='insurance'))
            batch.settings()
            picker = batch.detection_window
            batch.import_references(catalog, 'employees')
            wait(lambda: not batch.busy)
            assert len(picker.entries) == 1
            picker.apply()
            batch.files = (source, folder / 'ocr-source.png')
            batch.analyze()
            wait(lambda: not batch.busy)
            assert len(batch.jobs) == 2 and not any(j.ready or j.approved for j in batch.jobs.values())
            assert batch.jobs['2'].report.manual_pages == (1,)
            batch.documents.selection_set('1')
            batch.select_document()
            wait(lambda: not batch.busy and batch.preview is not None)
            finding = next(f for f in batch.job().report.findings if f.value == 'Nadia Benali')
            batch.findings.selection_set(finding.id)
            assert not batch.job().approved
            batch.candidates(True)
            wait(lambda: not batch.busy)
            assert not batch.job().ready
            batch.action('review_page', page=1)
            wait(lambda: not batch.busy)
            batch.action('approve_document')
            wait(lambda: not batch.busy)
            output = folder / 'strict-output'
            output.mkdir()
            batch.begin('export', folder=output)
            wait(lambda: not batch.busy)
            assert batch.jobs['1'].output and not batch.jobs['2'].output
            assert source.read_bytes() == original
            assert not PdfReader(batch.jobs['1'].output).pages[0].extract_text()
            ocr.assert_not_called()
            ner.assert_not_called()
            result.update(strict_rules=True, reference_import=True, batch_review=True)
    finally:
        if batch:
            batch.worker.stop()
            batch.worker.thread.join(timeout=10)
            assert not batch.worker.thread.is_alive()
            if batch.poll_after:
                root.after_cancel(batch.poll_after)
            batch.clear_preview()
            batch.window.destroy()
            app.batch_window = None


def run(report):
    result = {'version': __version__, 'success': False}
    try:
        with tempfile.TemporaryDirectory(prefix='partage-clair-selfcheck-') as folder:
            folder = Path(folder)
            source = folder / 'synthetic.png'
            Image.new('RGB', (50, 40), 'red').save(source)
            with Document(source) as doc:
                doc.export(folder / 'image.png', [Box(1, 0, 0, .5, .5)])
            with Image.open(folder / 'image.png') as image:
                assert image.getpixel((5, 5)) == (0, 0, 0)
                assert not image.info
            writer = PdfWriter()
            writer.add_metadata({'/Author': 'SYNTHETIC'})
            writer.add_blank_page(300, 400)
            writer.write(folder / 'source.pdf')
            with Document(folder / 'source.pdf') as doc:
                doc.export(folder / 'output.pdf', [Box(1, 0, 0, .5, .5)])
            reader = PdfReader(folder / 'output.pdf')
            assert reader.metadata is None and not reader.pages[0].extract_text()
            with Document(folder / 'output.pdf') as doc:
                image = doc.render(0, 72)
                try:
                    assert image.getpixel((10, 10)) == (0, 0, 0)
                finally:
                    image.close()
            # The portable must include the OCR models and infer without any HTTP request.
            from unittest.mock import patch

            from .assurance import audit_export, file_digest
            from .detection import canonical, scan
            image = Image.new('RGB', (1000, 270), 'white')
            ImageDraw.Draw(image).multiline_text((25, 30),
                                      'Alice Dupont travaille chez AXA.\nClient : Orion Fictif\nPolice : POL-760023', fill='black',
                                      font=ImageFont.load_default(size=34))
            image.save(folder / 'ocr-source.png')
            image.close()
            with patch('requests.sessions.Session.request', side_effect=RuntimeError('Network forbidden')):
                with Document(folder / 'ocr-source.png') as doc:
                    index, report_ocr = scan(doc)
                    assert report_ocr.ocr_pages == 1 and not report_ocr.warnings
                    assert report_ocr.ner_requested and report_ocr.ner_pages == 1
                    assert any(f.kind == 'Nom' and f.value == 'Alice Dupont' for f in report_ocr.findings)
                    assert any(f.kind == 'Entreprise / client' and f.value == 'AXA' for f in report_ocr.findings)
                    finding = index.add_name('Alice Dupont')
                    assert finding.zones
                    doc.export(folder / 'ocr-masked.png', list(finding.zones))
                    audit = audit_export(doc, folder / 'ocr-masked.png', finding.zones, [finding],
                                         file_digest(folder / 'ocr-masked.png'))
                    assert audit.passed and not audit.approved_residuals
                    labels = tuple(OutputLabel(box, 'Personne A', 'pseudonym') for box in finding.zones)
                    doc.export(folder / 'ocr-pseudonym.png', [], labels=labels)
                    check = audit_export(doc, folder / 'ocr-pseudonym.png', [], [finding],
                                         file_digest(folder / 'ocr-pseudonym.png'), labels=labels)
                    assert check.passed and check.labels_ok
                with Document(folder / 'source.pdf') as doc:
                    pdf_audit = audit_export(doc, folder / 'output.pdf', [Box(1, 0, 0, .5, .5)], [],
                                             file_digest(folder / 'output.pdf'))
                    assert pdf_audit.passed
                    labels = (OutputLabel(Box(1, .2, .2, .8, .4), '2026', 'generalise'),)
                    doc.export(folder / 'labelled.pdf', [], labels=labels)
                    check = audit_export(doc, folder / 'labelled.pdf', [], [],
                                         file_digest(folder / 'labelled.pdf'), labels=labels)
                    assert check.passed and check.labels_ok
                from .ocr import LocalOcr
                with Image.open(folder / 'ocr-masked.png') as image:
                    text = canonical(LocalOcr().layer(image, 1).text)
                    assert 'alice' not in text and 'dupont' not in text
            result['local_ocr'] = True
            result['export_audit'] = True
            result['replacement_export'] = True
            result['context_recognition'] = True
            # Validate the bundled Tcl/Tk resources as well as the decoder DLLs.
            import time
            import tkinter as tk

            from .gui import App
            root = tk.Tk()
            root.withdraw()
            errors = []
            root.report_callback_exception = lambda *args: errors.append(args)
            app = App(root, initial_path=folder / 'ocr-source.png')
            app.show_review = lambda: None  # Keep the portable smoke check invisible.
            try:
                with patch('partage_clair.gui.messagebox.showerror', side_effect=lambda *args: errors.append(args)), \
                     patch('requests.sessions.Session.request', side_effect=RuntimeError('Network forbidden')):
                    deadline = time.monotonic() + 25
                    while (app.report is None or app.busy) and not errors and time.monotonic() < deadline:
                        root.update()
                        time.sleep(.01)
                    assert not errors and app.report is not None and not app.busy
                    assert app.report.ocr_pages == 1 and not app.report.warnings
                    assert app.report.ner_requested and app.report.ner_pages == 1
                    assert app.report.findings and not app.all_boxes() and not app.approved and not app.choices
                    result['automatic_detection'] = True
                    from .detection_options import category_for
                    app.show_detection_options()
                    picker = app.detection_window
                    picker.window.withdraw()
                    assert all(v.get() for v in picker.variables.values())
                    for key, variable in picker.variables.items():
                        variable.set(key in ('companies', 'references', 'custom'))
                    picker.terms.insert('1.0', 'Alice Dupont')
                    picker.apply()
                    deadline = time.monotonic() + 25
                    while (app.report is None or app.busy) and not errors and time.monotonic() < deadline:
                        root.update()
                        time.sleep(.01)
                    assert not errors and app.report is not None and not app.busy
                    assert app.report.findings and not app.all_boxes() and not app.approved and not app.choices
                    assert {f.kind for f in app.report.findings} >= {'Entreprise / client', 'Référence métier', 'Texte ajouté'}
                    assert all(category_for(f.kind) in app.detection_options.categories for f in app.report.findings)
                    result['category_selection'] = True
                    result['business_dictionary'] = True
                    check_rules_batch(root, app, folder, result)
            finally:
                app.worker.stop()
                app.worker.thread.join(timeout=10)
                assert not app.worker.thread.is_alive()
                for callback in root.tk.call('after', 'info'):
                    root.after_cancel(callback)
                if app.preview:
                    app.preview.close()
                root.destroy()
            result['success'] = True
    except Exception as error:
        result['error'] = f'{type(error).__name__}: {error}'
    Path(report).write_text(json.dumps(result, indent=2), encoding='utf-8')
    return 0 if result['success'] else 1
