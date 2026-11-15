"""Local context recognition on synthetic statements, never real customer documents."""

import socket
from threading import Event

import pytest

from partage_clair.assurance import audit_export, file_digest, preparation_score
from partage_clair.core import Document, DocumentError, ExportCancelled
from partage_clair.detection import canonical, scan
from partage_clair.detection_options import DetectionOptions
from partage_clair.ner import LocalNer, aggregate, expand_word
from partage_clair.ner_assets import MODEL_FILES, model_folder
from tests.test_detection import make_pdf


@pytest.fixture
def offline(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail('Document text must never trigger a network request')
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    monkeypatch.setattr('urllib.request.urlopen', forbidden)
    import requests
    monkeypatch.setattr(requests.sessions.Session, 'request', forbidden)


@pytest.fixture
def recognizer(offline):
    pytest.importorskip('tokenizers')
    if not (model_folder() / 'model.onnx').is_file():
        pytest.skip('Install the verified model with scripts/fetch_ner_model.py; CI always does so.')
    return LocalNer()


@pytest.mark.parametrize(('text', 'expected'), [
    ('J’ai rencontré Delmas hier. Il travaille chez AXA depuis cinq ans.',
     {('Nom', 'Delmas'), ('Entreprise / client', 'AXA')}),
    ('Bonjour, je suis nadia benali et je travaille chez axa à bordeaux.',
     {('Nom', 'nadia benali'), ('Entreprise / client', 'axa'), ('Lieu', 'bordeaux')}),
    ('Camille Moreau a transmis le dossier à Allianz depuis Nantes.',
     {('Nom', 'Camille Moreau'), ('Entreprise / client', 'Allianz'), ('Lieu', 'Nantes')}),
    ('Le versement a été autorisé par Sophie Bernard pour BNP Paribas à Bordeaux.',
     {('Nom', 'Sophie Bernard'), ('Entreprise / client', 'BNP Paribas'), ('Lieu', 'Bordeaux')}),
    ('Le dossier a été signé par Zora Lemaire pour la société Orion Fictif.',
     {('Nom', 'Zora Lemaire'), ('Entreprise / client', 'Orion Fictif')}),
])
def test_real_model_recognizes_unlabelled_entities_and_lowercase(recognizer, text, expected):
    actual = {(entity.kind, text[entity.start:entity.end]) for entity in recognizer.entities(text)}
    assert expected <= actual


def test_ordinary_sentence_has_no_entities(recognizer):
    assert recognizer.entities('Nous livrerons les produits demain matin. Merci pour votre retour.') == ()


def test_aggregation_does_not_extend_into_previous_word_or_redact_only_subword():
    text = 'par Delmas chez AXA'
    assert expand_word(text, 3, 10) == (4, 10)
    assert expand_word(text, 5, 8) == (4, 10)
    entities = list(aggregate(text, [(3, 7), (7, 10), (15, 19)],
                              ['I-PER', 'I-PER', 'I-ORG'], [.95, .4, .9]))
    assert [(e.kind, text[e.start:e.end]) for e in entities] == [('Nom', 'Delmas'), ('Entreprise / client', 'AXA')]


def test_overlap_windows_cover_long_text_and_preserve_unicode_offsets(recognizer):
    sentence = 'Élodie Martin travaille chez AXA à Bordeaux. '
    text = 'Le dossier sera traité demain. ' * 90 + sentence + 'Nous attendons une réponse. ' * 90
    entities = recognizer.entities(text)
    actual = {(e.kind, text[e.start:e.end]) for e in entities}
    assert {('Nom', 'Élodie Martin'), ('Entreprise / client', 'AXA'), ('Lieu', 'Bordeaux')} <= actual
    assert all(0 <= e.start < e.end <= len(text) for e in entities)


def test_cancellation_is_checked_before_inference(recognizer):
    cancel = Event()
    cancel.set()
    with pytest.raises(ExportCancelled):
        recognizer.entities('Delmas travaille chez AXA.', cancel=cancel)


def test_missing_and_corrupted_assets_fail_locally_without_download(tmp_path, monkeypatch, offline):
    monkeypatch.setattr('partage_clair.ner.model_folder', lambda: tmp_path)
    with pytest.raises(DocumentError, match='Aucun téléchargement'):
        LocalNer()
    content = (model_folder() / 'config.json').read_bytes()
    (tmp_path / 'config.json').write_bytes(b'X' + content[1:])
    monkeypatch.setattr('partage_clair.ner.MODEL_FILES', {'config.json': MODEL_FILES['config.json']})
    with pytest.raises(DocumentError, match='Aucun téléchargement'):
        LocalNer()


def test_missing_model_is_visible_and_caps_score(tmp_path, monkeypatch, offline):
    source = make_pdf(tmp_path / 'source.pdf', ['Le dossier a été signé par Delmas chez AXA.'])
    monkeypatch.setattr('partage_clair.ner.model_folder', lambda: tmp_path / 'missing')
    with Document(source) as document:
        index, report = scan(document, use_ocr=False)
    assert report.ner_requested and report.ner_pages == 0
    assert any('Reconnaissance du contexte indisponible' in warning for warning in report.warnings)
    assert not index.approved_zones([])
    assert preparation_score(report, []).value <= 49


def test_unselected_context_categories_do_not_load_model(tmp_path, monkeypatch, offline):
    source = make_pdf(tmp_path / 'source.pdf', ['Mail : alice@example.test'])
    monkeypatch.setattr('partage_clair.ner.LocalNer.__init__', lambda *_: pytest.fail('Not requested'))
    with Document(source) as document:
        _, report = scan(document, use_ocr=False, options=DetectionOptions(('emails',)))
    assert not report.ner_requested and not report.warnings
    assert {f.kind for f in report.findings} == {'E-mail'}


def test_real_pdf_and_scan_context_detection_requires_validation_and_removes_pixels(
        tmp_path, recognizer):
    from PIL import Image
    from pypdf import PdfReader, PdfWriter

    from partage_clair.ocr import LocalOcr
    from partage_clair.pdf_output import ImagePdfWriter

    native = make_pdf(tmp_path / 'native.pdf', ['Delmas a transmis le dossier à AXA.'])
    with Document(native) as doc:
        image = doc.render(0, 150)
        with (tmp_path / 'scanned.pdf').open('wb') as stream:
            writer = ImagePdfWriter(stream, [(500, 400)])
            writer.page(0, image)
            writer.finish()
        image.close()
    writer = PdfWriter()
    writer.add_page(PdfReader(native).pages[0])
    writer.add_page(PdfReader(tmp_path / 'scanned.pdf').pages[0])
    writer.write(tmp_path / 'source.pdf')
    with Document(tmp_path / 'source.pdf') as document:
        index, report = scan(document)
        assert report.ner_pages == report.pages == report.ocr_pages == 2 and not report.warnings
        person = next(f for f in report.findings if f.kind == 'Nom' and f.value == 'Delmas')
        organization = next(f for f in report.findings if f.kind == 'Entreprise / client' and f.value == 'AXA')
        assert person.pages == organization.pages == (1, 2)
        assert 'modèle local' in person.reason and 'modèle local' in organization.reason
        assert not index.approved_zones([])
        untouched = tmp_path / 'unapproved.pdf'
        document.export(untouched, [])
        with PdfReader(untouched).pages[0].images[0].image as embedded:
            assert 'delmas' in canonical(LocalOcr().layer(embedded.convert('RGB'), 1).text)
        masks = index.approved_zones([person.id, organization.id])
        output = tmp_path / 'approved.pdf'
        document.export(output, list(masks))
        audit = audit_export(document, output, masks, [person, organization], file_digest(output))
        assert audit.passed and not audit.approved_residuals
        for page in PdfReader(output).pages:
            assert not page.extract_text() and '/Annots' not in page
            with page.images[0].image as image:
                assert isinstance(image, Image.Image)
                text = canonical(LocalOcr().layer(image.convert('RGB'), 1).text)
                assert 'delmas' not in text and 'axa' not in text
