"""Synthetic lists and documents only. Strict mode must never call OCR or NER."""

import json
import os
import subprocess
import sys
from dataclasses import replace
from threading import Event

import pytest
from PIL import Image
from pypdf import PdfReader

from partage_clair.assurance import audit_export, file_digest, preparation_score
from partage_clair.batch import BatchSession
from partage_clair.core import Box, Document, DocumentError, ExportCancelled
from partage_clair.detection import canonical, scan
from partage_clair.detection_options import DetectionOptions
from partage_clair.references import MultiMatcher, ReferenceEntry, load_csv
from tests.test_detection import make_pdf


@pytest.fixture(autouse=True)
def no_models_or_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail('Strict mode must never load AI models or contact a network')
    monkeypatch.setattr('partage_clair.ocr.LocalOcr.__init__', forbidden)
    monkeypatch.setattr('partage_clair.ner.LocalNer.__init__', forbidden)
    monkeypatch.setattr('socket.socket.connect', forbidden)
    monkeypatch.setattr('urllib.request.urlopen', forbidden)


@pytest.fixture
def options():
    return DetectionOptions(mode='rules', references=(
        ReferenceEntry('Nom', 'Nadia Benali', 'employees'),
        ReferenceEntry('Entreprise / client', 'Orion Fictif', 'clients'),
    ))


def test_csv_encodings_delimiters_names_and_metadata_are_bounded(tmp_path):
    source = tmp_path / 'employees.csv'
    source.write_text('prénom;nom;email;matricule\nNadia;Bénali;nadia@example.test;EMP-2719\n', encoding='utf-8-sig')
    entries = load_csv(source, 'employees')
    assert {(e.kind, e.value) for e in entries} == {
        ('Nom', 'Nadia Bénali'), ('E-mail', 'nadia@example.test'), ('Identifiant', 'EMP-2719')}
    source.write_bytes('entreprise\tiban\n"Orion, Fictif"\tFR0033334444\n'.encode('utf-16'))
    assert {e.kind for e in load_csv(source, 'clients')} == {'Entreprise / client', 'Donnée bancaire'}
    source.write_bytes('nom_complet\nÉlodie Martin\n'.encode('cp1252'))
    assert load_csv(source, 'employees')[0].value == 'Élodie Martin'
    source.write_text('inconnu\nSECRET\n', encoding='utf-8')
    with pytest.raises(DocumentError, match='En-têtes'):
        load_csv(source, 'clients')
    source.write_text('nom;prenom\nDupont;Alice;EXTRA\n', encoding='utf-8')
    with pytest.raises(DocumentError, match='colonnes'):
        load_csv(source, 'employees')
    source.write_bytes(b'x' * (5 * 1024 * 1024 + 1))
    with pytest.raises(DocumentError, match='5 Mo'):
        load_csv(source, 'clients')


def test_multi_matcher_handles_suffixes_whole_words_and_unicode():
    matcher = MultiMatcher(('benali', 'ali', 'orion fictif', 'fictif'))
    hits = list(matcher.matches('benali ali benalix orion fictif'))
    assert [(term, start, end) for term, start, end in hits] == [
        ('benali', 0, 6), ('ali', 7, 10), ('orion fictif', 19, 31), ('fictif', 25, 31)]


def test_common_firstname_alone_does_not_nominate_entire_employee_list(tmp_path):
    entries = tuple(ReferenceEntry('Nom', f'Nadia Personne{i}', 'employees') for i in range(2500))
    source = make_pdf(tmp_path / 'source.pdf', ['nadia attend personne1974.'])
    with Document(source) as document:
        _, report = scan(document, options=DetectionOptions(mode='rules', references=entries))
    people = [f for f in report.findings if f.kind == 'Nom']
    assert len(people) == 1 and people[0].value == 'Nadia Personne1974'


def test_csv_preserves_composite_family_name_for_nomination(tmp_path):
    catalog = tmp_path / 'people.csv'
    catalog.write_text('prenom;nom\nNadia;de la Tour\n', encoding='utf-8')
    entries = load_csv(catalog, 'employees')
    assert entries[0].family == 'de la Tour'
    for body, expected in [('La tour est visible.', False), ('de la tour a signé.', True)]:
        source = make_pdf(tmp_path / 'doc.pdf', [body])
        with Document(source) as doc:
            _, report = scan(doc, options=DetectionOptions(mode='rules', references=entries))
        assert any(f.value == 'Nadia de la Tour' for f in report.findings) is expected


def test_strict_mode_overrides_ai_flags_and_finds_unlabelled_list_entries(tmp_path, options):
    source = make_pdf(tmp_path / 'source.pdf', [
        'nadia benali rejoint orion fictif.', 'BENALI signe ; NADIA est présente.'])
    with Document(source) as doc:
        index, report = scan(doc, options=options, use_ocr=True, use_ner=True)
    assert report.mode == 'rules' and report.text_pages == 2
    assert not report.ner_requested and report.ner_pages == report.ocr_pages == 0
    assert not report.warnings
    person = next(f for f in report.findings if f.kind == 'Nom' and canonical(f.value) == 'nadia benali')
    assert person.pages == (1, 2) and 'Liste salariés' in person.reason
    assert any(f.kind == 'Entreprise / client' and f.value == 'Orion Fictif' for f in report.findings)
    assert not index.approved_zones([])
    masks = [z for f in report.findings for z in f.zones]
    assert preparation_score(report, masks, criteria_reviewed=True).value <= 49
    selected = replace(options, categories=('emails',))
    with Document(source) as doc:
        _, filtered = scan(doc, options=selected)
    assert not filtered.findings


@pytest.mark.parametrize(('profile', 'field', 'value', 'kind'), [
    ('bank', 'Solde disponible', '12000', 'Donnée métier'),
    ('bank', 'Conseiller bancaire', 'Nadia Benali', 'Nom'),
    ('insurance', 'Numéro de sociétaire', 'SOC-28179', 'Référence métier'),
    ('insurance', 'Adresse du risque', 'lieu confidentiel', 'Adresse'),
])
def test_profiles_add_specific_rules(tmp_path, options, profile, field, value, kind):
    source = make_pdf(tmp_path / 'profile.pdf', [f'{field} : {value}'])
    with Document(source) as doc:
        _, report = scan(doc, options=replace(options, profile=profile, references=()))
    assert report.profile == profile
    assert any(f.kind == kind and f.value == value for f in report.findings)


def test_image_and_mixed_pdf_pages_are_flagged_without_ocr(tmp_path, options):
    image = tmp_path / 'scan.png'
    Image.new('RGB', (200, 160), 'white').save(image)
    with Document(image) as doc:
        _, report = scan(doc, options=options)
    assert report.manual_pages == (1,) and not report.text_pages and report.warnings
    from pypdf import PdfWriter

    from partage_clair.pdf_output import ImagePdfWriter
    with Image.open(image) as opened, (tmp_path / 'image.pdf').open('wb') as output:
        writer = ImagePdfWriter(output, [(200, 160)])
        writer.page(0, opened)
        writer.finish()
    native = make_pdf(tmp_path / 'text.pdf', ['nadia benali signe.'])
    writer = PdfWriter()
    writer.add_page(PdfReader(native).pages[0])
    writer.add_page(PdfReader(tmp_path / 'image.pdf').pages[0])
    writer.write(tmp_path / 'mixed.pdf')
    with Document(tmp_path / 'mixed.pdf') as doc:
        _, report = scan(doc, options=options)
    assert report.text_pages == 1 and report.manual_pages == (2,)


def approve_all(session, job):
    session.candidates(job.id, [f.id for f in job.report.findings])
    for page in range(1, job.pages + 1):
        session.review_page(job.id, page)
    return session.approve_document(job.id)


def test_batch_exports_only_explicitly_validated_files_with_pixel_audit(tmp_path, options):
    first = make_pdf(tmp_path / 'private-name.pdf', ['nadia benali rejoint orion fictif.'])
    second = make_pdf(tmp_path / 'other.pdf', ['nadia benali attend.'])
    session = BatchSession()
    jobs = session.analyze([first, second], options)
    assert all(not j.approved and not j.ready for j in jobs)
    with pytest.raises(DocumentError, match='Aucun document validé'):
        session.export(tmp_path)
    with pytest.raises(DocumentError, match='chaque page'):
        session.approve_document(jobs[0].id)
    first_job = approve_all(session, jobs[0])
    result = session.export(tmp_path)
    assert result[0].output and result[1].output is None
    assert 'private-name' not in result[0].output.name
    assert first.read_bytes() and second.read_bytes()
    with Document(first) as source:
        audit = audit_export(source, result[0].output, first_job.masks,
            [f for f in first_job.report.findings if f.id in first_job.approved], file_digest(result[0].output), mode='rules')
    assert audit.passed and audit.mode == 'rules' and not audit.ocr_complete
    assert any('aucune relecture OCR' in warning for warning in audit.warnings)
    assert PdfReader(result[0].output).metadata is None
    assert not PdfReader(result[0].output).pages[0].extract_text()
    from partage_clair.assurance import anonymous_summary
    summary = anonymous_summary(preparation_score(first_job.report, first_job.masks), audit)
    assert summary['export_check']['approved_residuals'] is None
    assert summary['export_check']['residual_groups'] is None


def test_cancel_export_after_first_copy_keeps_only_completed_copy(tmp_path, options):
    session, cancel = BatchSession(), Event()
    paths = [make_pdf(tmp_path / f'{i}.pdf', ['nadia benali signe.']) for i in range(2)]
    for job in session.analyze(paths, options):
        approve_all(session, job)
    with pytest.raises(ExportCancelled):
        session.export(tmp_path, cancel=cancel, progress=lambda *_: cancel.set())
    assert session.jobs['1'].output and session.jobs['2'].output is None
    assert len(list(tmp_path.glob('lot-*-masque.pdf'))) == 1
    session.clear()
    assert not session.jobs


def test_batch_revoke_and_manual_masks_invalidate_file_approval(tmp_path, options):
    path = make_pdf(tmp_path / 'doc.pdf', ['nadia benali signe.'])
    session = BatchSession()
    job = session.analyze([path], options)[0]
    approved = approve_all(session, job)
    assert approved.ready
    revised = session.candidates(job.id, list(approved.approved), approve=False)
    assert not revised.ready and not revised.approved
    session.approve_document(job.id)
    revised = session.add_box(job.id, Box(1, .1, .1, .3, .2))
    assert not revised.ready
    session.undo_box(job.id)
    assert not session.jobs[job.id].boxes and not session.jobs[job.id].ready


def test_changed_source_refuses_stale_masks_and_other_files_continue(tmp_path, options):
    first = make_pdf(tmp_path / 'first.pdf', ['nadia benali signe.'])
    second = make_pdf(tmp_path / 'second.pdf', ['orion fictif attend.'])
    session = BatchSession()
    for job in session.analyze([first, second, tmp_path / 'missing.pdf'], options):
        if job.report:
            approve_all(session, job)
    make_pdf(first, ['autre personne inconnue.'])
    result = session.export(tmp_path)
    assert result[0].output is None and not result[0].ready
    assert result[1].output and result[2].report is None


def test_cancellation_preserves_completed_jobs_and_never_validates_pending_files(tmp_path, options):
    paths = [make_pdf(tmp_path / f'{i}.pdf', ['nadia benali signe.']) for i in range(3)]
    cancel, session = Event(), BatchSession()
    with pytest.raises(ExportCancelled):
        session.analyze(paths, options, cancel=cancel,
                        progress=lambda *_: cancel.set())
    assert len([j for j in session.jobs.values() if j.report]) == 1
    assert not any(j.ready for j in session.jobs.values())


def test_strict_pipeline_in_clean_interpreter_does_not_import_ai_packages(tmp_path):
    source = make_pdf(tmp_path / 'source.pdf', ['nadia benali signe.'])
    script = '''
import sys,json
from pathlib import Path
from partage_clair.batch import BatchSession
from partage_clair.detection_options import DetectionOptions
from partage_clair.references import ReferenceEntry
s=BatchSession()
j=s.analyze([sys.argv[1]],DetectionOptions(mode='rules',references=(ReferenceEntry('Nom','Nadia Benali','employees'),)))[0]
s.candidates(j.id,[f.id for f in j.report.findings]);s.review_page(j.id,1);s.approve_document(j.id)
s.export(Path(sys.argv[1]).parent)
assert not any(n.split('.')[0] in {'onnxruntime','rapidocr','tokenizers','torch','transformers'} for n in sys.modules)
print(json.dumps({'no_ai_imported':True}))
'''
    result = subprocess.run([sys.executable, '-c', script, str(source)], capture_output=True, text=True,
                            timeout=30, env=os.environ.copy())
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['no_ai_imported']
