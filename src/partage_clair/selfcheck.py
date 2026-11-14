"""Offline frozen-binary smoke check using only generated synthetic documents."""

import json
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter

from . import __version__
from .core import Box, Document


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
            image = Image.new('RGB', (900, 160), 'white')
            ImageDraw.Draw(image).text((25, 35), 'Nom : Alice Dupont', fill='black',
                                      font=ImageFont.load_default(size=34))
            image.save(folder / 'ocr-source.png')
            image.close()
            with patch('requests.sessions.Session.request', side_effect=RuntimeError('Network forbidden')):
                with Document(folder / 'ocr-source.png') as doc:
                    index, report_ocr = scan(doc)
                    assert report_ocr.ocr_pages == 1 and not report_ocr.warnings
                    finding = index.add_name('Alice Dupont')
                    assert finding.zones
                    doc.export(folder / 'ocr-masked.png', list(finding.zones))
                    audit = audit_export(doc, folder / 'ocr-masked.png', finding.zones, [finding],
                                         file_digest(folder / 'ocr-masked.png'))
                    assert audit.passed and not audit.approved_residuals
                with Document(folder / 'source.pdf') as doc:
                    pdf_audit = audit_export(doc, folder / 'output.pdf', [Box(1, 0, 0, .5, .5)], [],
                                             file_digest(folder / 'output.pdf'))
                    assert pdf_audit.passed
                from .ocr import LocalOcr
                with Image.open(folder / 'ocr-masked.png') as image:
                    text = canonical(LocalOcr().layer(image, 1).text)
                    assert 'alice' not in text and 'dupont' not in text
            result['local_ocr'] = True
            result['export_audit'] = True
            # Validate the bundled Tcl/Tk resources as well as the decoder DLLs.
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            root.update_idletasks()
            root.destroy()
            result['success'] = True
    except Exception as error:
        result['error'] = f'{type(error).__name__}: {error}'
    Path(report).write_text(json.dumps(result, indent=2), encoding='utf-8')
    return 0 if result['success'] else 1
