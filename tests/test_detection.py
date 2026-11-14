"""Synthetic private-like strings only. No user documents are loaded by these tests."""

from pathlib import Path
from threading import Event

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from partage_clair.core import Box, Document, DocumentError, ExportCancelled
from partage_clair.detection import DetectionIndex, TextLayer, canonical, scan


def make_pdf(path, lines, rotation=0, crop=False):
    writer = PdfWriter()
    for text in lines:
        page = writer.add_blank_page(500, 400)
        page[NameObject('/Resources')] = DictionaryObject({
            NameObject('/Font'): DictionaryObject({NameObject('/F1'): DictionaryObject({
                NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
                NameObject('/BaseFont'): NameObject('/Helvetica'),
                NameObject('/Encoding'): NameObject('/WinAnsiEncoding'),
            })}),
        })
        commands = ['BT /F1 17 Tf 45 330 Td']
        for line in text.split('\n'):
            commands.append(f'<{line.encode("cp1252").hex()}> Tj 0 -38 Td')
        commands.append('ET')
        content = DecodedStreamObject()
        content.set_data('\n'.join(commands).encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(content)
        if crop:
            page.cropbox.lower_left = (20, 15)
            page.cropbox.upper_right = (480, 380)
        page.rotate(rotation)
    writer.write(path)
    return path


def simple_layer(text, page=1):
    boxes = tuple(None if c.isspace() else Box(page, .01 + i * .006, .1, .015 + i * .006, .14)
                  for i, c in enumerate(text))
    return TextLayer(page, text, boxes, 'test')


def test_name_validation_resolves_every_page_case_and_components(tmp_path):
    source = make_pdf(tmp_path / 'source.pdf', [
        'Nom : Alice Dupont', 'Bonjour ALICE\nSignature : DUPONT',
        'alice dupont a signé.\nDupontel et Malice restent visibles.',
    ])
    with Document(source) as doc:
        index, report = scan(doc, use_ocr=False)
        finding = next(f for f in report.findings if f.kind == 'Nom' and canonical(f.value) == 'alice dupont')
        assert finding.pages == (1, 2, 3)
        assert len(finding.zones) == 4
        # Suggestions alone must have no effect on an export.
        doc.export(tmp_path / 'untouched.pdf', [])
        doc.export(tmp_path / 'masked.pdf', index.approved_zones([finding.id]))
        layers = [doc.text_layer(i) for i in range(doc.pages)]
    with Document(tmp_path / 'masked.pdf') as masked:
        for box in finding.zones:
            image = masked.render(box.page - 1, 150)
            w, h = image.size
            interior = image.crop((round(box.x0 * w) + 2, round(box.y0 * h) + 2,
                                   round(box.x1 * w) - 2, round(box.y1 * h) - 2))
            assert interior.getextrema() == ((0, 0),) * 3
            interior.close()
            image.close()
    layer = layers[2]
    start = layer.text.index('Dupontel')
    safe_box = layer.zones(start, start + len('Dupontel'))[0]
    assert not any(b.page == 3 and b.y0 <= safe_box.y0 and b.y1 >= safe_box.y1 for b in finding.zones)
    reader = PdfReader(tmp_path / 'masked.pdf')
    assert all(not p.extract_text() for p in reader.pages)
    assert reader.metadata is None


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
def test_name_geometry_matches_cropped_rotated_render(tmp_path, rotation):
    source = make_pdf(tmp_path / 'rotated.pdf', ['Nom : Élodie Martin'], rotation=rotation, crop=True)
    with Document(source) as doc:
        index, _ = scan(doc, use_ocr=False)
        finding = index.add_name('elodie martin')
        assert finding.zones
        doc.export(tmp_path / 'share.pdf', list(finding.zones), dpi=150)
    with Document(tmp_path / 'share.pdf') as doc:
        image = doc.render(0, 150)
        for box in finding.zones:
            w, h = image.size
            assert image.getpixel((round((box.x0 + box.x1) / 2 * w),
                                   round((box.y0 + box.y1) / 2 * h))) == (0, 0, 0)
        # An independent OCR pass on the visually upright copy catches misplaced masks.
        pytest.importorskip('rapidocr')
        from partage_clair.ocr import LocalOcr
        upright = image.rotate(rotation, expand=True)
        text = canonical(LocalOcr().layer(upright, 1).text)
        assert 'nom' in text
        assert 'elodie' not in text and 'martin' not in text
        upright.close()
        image.close()


def test_accents_hyphens_case_and_repeated_whitespace():
    layers = [simple_layer('Nom : Élodie Martin'), simple_layer('ELODIE\nMARTIN', 2),
              simple_layer('Elodie a signé. Martinique n’est pas Martin.', 3)]
    index = DetectionIndex(layers)
    finding = index.add_name('Élodie Martin')
    assert finding.pages == (1, 2, 3)
    assert finding.terms == ('elodie martin', 'elodie', 'martin')
    assert canonical("Jean‑Pierre D’Angelo") == "jean-pierre d'angelo"


def test_categories_checksums_and_no_default_approval():
    text = ('Email : alice@example.test\nTéléphone : 06 12 34 56 78\n'
            'IBAN : FR76 3000 6000 0112 3456 7890 189\n'
            'Carte : 4111 1111 1111 1111\nAdresse : 12 rue des Fleurs\n'
            'Date de naissance : 12/03/1990')
    # Separate lines keep the synthetic horizontal coordinates within the page.
    index = DetectionIndex([simple_layer(line, i + 1) for i, line in enumerate(text.splitlines())])
    findings = index.suggest()
    kinds = {f.kind for f in findings}
    assert {'E-mail', 'Téléphone', 'IBAN', 'Carte bancaire', 'Adresse', 'Date de naissance'} <= kinds
    assert index.approved_zones([]) == ()
    bad = DetectionIndex([simple_layer('FR00 3000 6000 0112 3456 7890 189')])
    assert not any(f.kind == 'IBAN' for f in bad.suggest())


def test_unknown_validation_and_missing_name_are_refused():
    index = DetectionIndex([simple_layer('Alice Dupont')])
    with pytest.raises(DocumentError):
        index.approved_zones(['not-a-finding'])
    with pytest.raises(DocumentError, match='Aucune occurrence'):
        index.add_name('Inconnu Absent')


def test_email_ocr_spacing_is_grouped_and_entire_region_is_covered():
    index = DetectionIndex([simple_layer('alice@example.test', 1),
                            simple_layer('ALICE @ example . test', 2)])
    findings = [f for f in index.suggest() if f.kind == 'E-mail']
    assert len(findings) == 1 and findings[0].pages == (1, 2)
    assert findings[0].zones[1].x1 == index.layers[1].boxes[-1].x1


def test_cancelled_analysis_returns_no_partial_report(tmp_path):
    path = make_pdf(tmp_path / 'source.pdf', ['Nom : Alice Dupont'] * 3)
    cancel = Event()
    with Document(path) as doc, pytest.raises(ExportCancelled):
        scan(doc, use_ocr=False, cancel=cancel,
             progress=lambda done, total: cancel.set() if done == 1 else None)


def test_real_ocr_runs_without_network_on_image_and_scan(tmp_path, monkeypatch):
    pytest.importorskip('rapidocr')
    import socket

    import requests

    from partage_clair.ocr import LocalOcr
    forbidden = []

    def no_network(*args, **kwargs):
        forbidden.append(True)
        raise AssertionError('Network access is forbidden during document analysis')
    monkeypatch.setattr(requests.sessions.Session, 'request', no_network)
    monkeypatch.setattr(socket, 'create_connection', no_network)
    source = make_pdf(tmp_path / 'source.pdf', ['Nom : Alice Dupont\nEmail : alice@example.test'])
    with Document(source) as doc:
        image = doc.render(0, 150)
        image.save(tmp_path / 'scan.png')
        image.close()
    with Document(tmp_path / 'scan.png') as doc:
        index, report = scan(doc)
        assert report.ocr_pages == 1 and not report.warnings
        assert any(f.kind == 'E-mail' for f in report.findings)
        finding = index.add_name('Alice Dupont')
        doc.export(tmp_path / 'masked.png', list(finding.zones))
    with Image.open(tmp_path / 'masked.png') as image:
        output_text = canonical(LocalOcr().layer(image, 1).text)
        assert 'alice' not in output_text and 'dupont' not in output_text
    from partage_clair.pdf_output import ImagePdfWriter
    with Image.open(tmp_path / 'scan.png') as image, (tmp_path / 'scan.pdf').open('wb') as stream:
        writer = ImagePdfWriter(stream, [(500, 400)])
        writer.page(0, image)
        writer.finish()
    with Document(tmp_path / 'scan.pdf') as doc:
        assert not doc.text_layer(0).text
        index, report = scan(doc)
        assert report.ocr_pages == 1 and not report.warnings
        assert index.add_name('Alice Dupont').zones
    assert not forbidden


def test_missing_ocr_models_fail_closed_without_download(tmp_path, monkeypatch):
    rapidocr = pytest.importorskip('rapidocr')
    from partage_clair.ocr import LocalOcr
    monkeypatch.setattr(rapidocr, '__file__', str(Path(tmp_path) / '__init__.py'))
    with pytest.raises(DocumentError, match='Aucun téléchargement'):
        LocalOcr()
