"""Regression tests for interruption, publication races and streaming pixel fidelity."""

import errno
from threading import Event

import pytest
from PIL import Image, ImageChops
from pypdf import PdfReader, PdfWriter

from partage_clair.core import Box, Document, DocumentError, ExportCancelled, cover
from partage_clair.pdf_output import ImagePdfWriter


@pytest.fixture
def pdf(tmp_path):
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(240, 320)
    source = tmp_path / 'source.pdf'
    writer.write(source)
    return source


def test_cancel_between_pages_cleans_temporary_and_preserves_original(pdf, tmp_path):
    cancel = Event()
    original = pdf.read_bytes()
    progress = []

    def report(done, total):
        progress.append((done, total))
        if done == 1:
            cancel.set()

    with Document(pdf) as doc:
        with pytest.raises(ExportCancelled):
            doc.export(tmp_path / 'cancelled.pdf', [], cancel=cancel, progress=report)
    assert progress == [(0, 3), (1, 3)]
    assert pdf.read_bytes() == original
    assert not (tmp_path / 'cancelled.pdf').exists()
    assert not list(tmp_path.glob('.partage-clair-*'))


def test_failure_after_partial_render_leaves_no_output(pdf, tmp_path, monkeypatch):
    def fail(self, index, image):
        self.stream.write(b'partial-output')
        raise OSError('Simulated disk failure')
    monkeypatch.setattr(ImagePdfWriter, 'page', fail)
    with Document(pdf) as doc, pytest.raises(OSError):
        doc.export(tmp_path / 'failure.pdf', [])
    assert not (tmp_path / 'failure.pdf').exists()
    assert not list(tmp_path.glob('.partage-clair-*'))


def test_fallback_for_filesystems_without_hardlinks(pdf, tmp_path, monkeypatch):
    def unsupported(*_):
        raise OSError(errno.EOPNOTSUPP, 'Simulated unsupported link')
    monkeypatch.setattr('partage_clair.core.os.link', unsupported)
    with Document(pdf) as doc:
        doc.export(tmp_path / 'fallback.pdf', [])
    assert len(PdfReader(tmp_path / 'fallback.pdf').pages) == 3
    assert not list(tmp_path.glob('.partage-clair-*'))


def test_publication_race_never_overwrites_other_file(pdf, tmp_path, monkeypatch):
    target = tmp_path / 'raced.pdf'

    def raced(*_):
        target.write_bytes(b'other-process-file')
        raise FileExistsError('Already exists')
    monkeypatch.setattr('partage_clair.core.os.link', raced)
    with Document(pdf) as doc, pytest.raises(DocumentError, match='existe'):
        doc.export(target, [])
    assert target.read_bytes() == b'other-process-file'
    assert not list(tmp_path.glob('.partage-clair-*'))


@pytest.mark.parametrize('color', ['gray', 'red'])
def test_streamed_pdf_pixels_match_lossless_source_exactly(tmp_path, color):
    source = tmp_path / 'source.png'
    Image.new('RGB', (201, 149), color).save(source)
    with Document(source) as doc:
        clean = cover(doc.image, [Box(1, .1, .2, .7, .6)])
    target = tmp_path / 'streamed.pdf'
    with target.open('wb') as stream:
        writer = ImagePdfWriter(stream, [(201, 149)])
        writer.page(0, clean)
        writer.finish()
    reader = PdfReader(target)
    extracted = reader.pages[0].images[0].image.convert('RGB')
    assert ImageChops.difference(extracted, clean).getbbox() is None
    with Document(target) as doc:
        rendered = doc.render(0, 72)
        assert rendered.getpixel((40, 50)) == (0, 0, 0)
        assert rendered.getpixel((190, 140)) == clean.getpixel((190, 140))
    clean.close()
    extracted.close()


def test_closed_document_has_clear_error(pdf):
    doc = Document(pdf)
    doc.close()
    doc.close()
    with pytest.raises(DocumentError, match='fermé'):
        doc.render(0)


def test_fifty_a4_pages_fit_default_export_budget(tmp_path):
    writer = PdfWriter()
    for _ in range(50):
        writer.add_blank_page(595, 842)
    path = tmp_path / 'fifty-pages.pdf'
    writer.write(path)
    with Document(path) as doc:
        assert doc.estimate(200) < 200_000_000


@pytest.mark.parametrize('dpi', [False, True, 72.5, 0, 201])
def test_invalid_resolution_is_rejected_before_staging(pdf, tmp_path, dpi):
    with Document(pdf) as doc, pytest.raises(DocumentError):
        doc.export(tmp_path / 'invalid.pdf', [], dpi=dpi)
    assert not list(tmp_path.glob('.partage-clair-*'))


def test_png_cancel_after_encoding_creates_no_file(tmp_path):
    source = tmp_path / 'source.png'
    Image.new('RGB', (40, 50), 'blue').save(source)
    cancel = Event()
    with Document(source) as doc, pytest.raises(ExportCancelled):
        doc.export(tmp_path / 'cancelled.png', [], cancel=cancel,
                   progress=lambda done, total: cancel.set() if done else None)
    assert not (tmp_path / 'cancelled.png').exists()
    assert not list(tmp_path.glob('.partage-clair-*'))
