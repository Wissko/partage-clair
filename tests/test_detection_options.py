"""Synthetic banking, insurance and business documents; no real company data."""

from dataclasses import replace

import pytest

from partage_clair.assurance import preparation_score
from partage_clair.core import Document, DocumentError
from partage_clair.detection import DetectionIndex, ScanReport, scan
from partage_clair.detection_options import ALL_CATEGORIES, DetectionOptions, category_for
from tests.test_detection import make_pdf, simple_layer

SAMPLES = (
    ('names', 'Nom : Alice Dupont', 'Nom'),
    ('addresses', 'Adresse : 12 rue des fleurs', 'Adresse'),
    ('emails', 'alice@example.test', 'E-mail'),
    ('phones', '06 12 34 56 78', 'Téléphone'),
    ('dates', '12/03/1990', 'Date précise'),
    ('banking', 'IBAN : FR76 3000 6000 0112 3456 7890 189', 'IBAN'),
    ('companies', 'Entreprise : orion fictif', 'Entreprise / client'),
    ('amounts', '12 500 EUR', 'Montant'),
    ('references', 'Police : AX-482601', 'Référence métier'),
    ('business', 'Marge brute : 24 %', 'Donnée métier'),
    ('context', 'Diagnostic : suivi médical', 'Contexte sensible'),
    ('custom', 'projet albatros', 'Texte ajouté'),
)


@pytest.mark.parametrize(('category', 'text', 'kind'), SAMPLES)
def test_selected_categories_reach_the_engine_and_disabled_categories_are_absent(category, text, kind):
    options = DetectionOptions((category,), ('projet albatros',))
    index = DetectionIndex([simple_layer(text)])
    findings = index.suggest(options=options)
    assert any(f.kind == kind for f in findings)
    assert all(category_for(f.kind) == category for f in findings)
    assert not index.approved_zones([])
    other = DetectionOptions(tuple(k for k in ALL_CATEGORIES if k != category), options.terms)
    assert not any(f.kind == kind for f in index.suggest(options=other))


def test_default_is_all_categories_and_options_reject_empty_or_unknown_scope():
    assert DetectionOptions().full_scope
    assert DetectionOptions().categories == ALL_CATEGORIES
    for categories in [(), ('unknown',)]:
        with pytest.raises(DocumentError):
            DetectionOptions(categories)
    with pytest.raises(DocumentError):
        DetectionOptions(terms=('x',))
    with pytest.raises(DocumentError):
        DetectionOptions(terms=('a' * 161,))
    with pytest.raises(DocumentError):
        DetectionOptions(terms=('orion',) * 201)
    assert DetectionOptions(terms=('  projet   orion ', '', 'projet orion')).terms == ('projet orion',)


def test_bank_insurance_and_business_values_propagate_without_splitting_companies():
    lines = ['Client : Orion Fictif', 'orion fictif et orion seulement',
             'BIC : ABCDFRPPXXX', 'Compte bancaire : 01234567890',
             'IBAN : FR00 3000 6000 0112 3456 7890 189',  # Bad OCR/checksum: still a labelled candidate.
             'SIRET : 12345678900012', 'TVA : FR00123456789',
             'Numéro de sinistre : SIN-482601', 'Police : POL-760023',
             'Prime annuelle : 1200 EUR', 'Franchise : 500 EUR',
             'Marge brute : 24 %', 'Chiffre d’affaires : 800000 EUR',
             'sin-482601 et POL-760023']
    index = DetectionIndex([simple_layer(line, i + 1) for i, line in enumerate(lines)])
    findings = index.suggest()
    company = next(f for f in findings if f.kind == 'Entreprise / client')
    assert company.value == 'Orion Fictif' and company.pages == (1, 2)
    assert len(company.zones) == 2
    assert not any(f.kind == 'Nom' and f.value == 'Orion Fictif' for f in findings)
    assert {f.value for f in findings if f.kind == 'Donnée bancaire'} >= {
        'ABCDFRPPXXX', '01234567890', 'FR00 3000 6000 0112 3456 7890 189'}
    assert len([f for f in findings if f.kind == 'Identifiant entreprise']) == 2
    references = [f for f in findings if f.kind == 'Référence métier']
    assert len(references) == 2 and all(14 in f.pages for f in references)
    assert len([f for f in findings if f.kind == 'Donnée métier']) == 4
    assert not index.approved_zones([])


def test_custom_dictionary_matches_whole_expressions_across_pages_and_ignores_missing_terms():
    index = DetectionIndex([simple_layer('Projet Albatros', 1), simple_layer('PROJET ALBATROS', 2),
                            simple_layer('Projet public ; albatros seulement', 3)])
    findings = index.suggest(options=DetectionOptions(('custom',), ('projet albatros', 'absent fictif')))
    assert len(findings) == 1 and findings[0].pages == (1, 2)
    assert findings[0].kind == 'Texte ajouté'
    assert not index.approved_zones([])


def test_partial_scope_cannot_raise_score_by_hiding_excluded_categories():
    from tests.test_assurance import good_audit
    index = DetectionIndex([simple_layer('alice@example.test')])
    options = DetectionOptions(('emails',))
    findings = index.suggest(options=options)
    partial = ScanReport(findings, (), 1, 1, options.categories)
    masks = [z for f in findings for z in f.zones]
    score = preparation_score(partial, masks, criteria_reviewed=True, copy_reviewed=True, audit=good_audit())
    assert score.value <= 49
    assert score.components[0][1] == 0
    assert any('Catégories désactivées' in b for b in score.blockers)
    assert not any('OCR' in b for b in score.blockers)
    full = preparation_score(replace(partial, categories=ALL_CATEGORIES), masks,
                             criteria_reviewed=True, copy_reviewed=True, audit=good_audit())
    assert full.value == 95


def test_real_pdf_scan_with_selected_scope_is_local_and_unapproved(tmp_path, monkeypatch):
    import socket

    monkeypatch.setattr(socket, 'create_connection', lambda *_a, **_k: pytest.fail('Must stay local'))
    source = make_pdf(tmp_path / 'confidential.pdf', [
        'Client : Orion Fictif\nPolice : POL-760023\nEmail : alice@example.test',
        'ORION FICTIF\nPOL-760023\nProjet Albatros',
    ])
    options = DetectionOptions(('companies', 'references', 'custom'), ('projet albatros',))
    with Document(source) as doc:
        index, report = scan(doc, use_ocr=False, options=options)
        assert report.categories == options.categories
        assert not any(f.kind == 'E-mail' for f in report.findings)
        assert {f.kind for f in report.findings} >= {'Entreprise / client', 'Référence métier', 'Texte ajouté'}
        assert not index.approved_zones([])
        untouched = tmp_path / 'unapproved.pdf'
        doc.export(untouched, index.approved_zones([]))
        from pypdf import PdfReader
        with PdfReader(untouched).pages[0].images[0].image as embedded:
            expected = doc.render(0, 150)
            actual = embedded.convert('RGB')
            try:
                assert expected.tobytes() == actual.tobytes()
            finally:
                expected.close()
                actual.close()


def test_export_audit_ignores_initial_filter_and_checks_all_categories(tmp_path, monkeypatch):
    pytest.importorskip('rapidocr')
    import requests

    from partage_clair.assurance import audit_export, file_digest

    monkeypatch.setattr(requests.sessions.Session, 'request',
                        lambda *_a, **_k: pytest.fail('Document processing must stay local'))
    source = make_pdf(tmp_path / 'source.pdf', ['Client : Orion Fictif\nMail : alice@example.test'])
    observed_scopes = []

    def observe(document, **arguments):
        result = scan(document, **arguments)
        observed_scopes.append(result[1].categories)
        return result
    monkeypatch.setattr('partage_clair.detection.scan', observe)
    with Document(source) as doc:
        index, report = scan(doc, use_ocr=False, options=DetectionOptions(('emails',)))
        assert {f.kind for f in report.findings} == {'E-mail'}
        output = tmp_path / 'unapproved.pdf'
        doc.export(output, index.approved_zones([]))
        audit = audit_export(doc, output, [], [], file_digest(output))
    assert observed_scopes == [ALL_CATEGORIES]
    assert audit.ocr_complete and audit.residual_groups >= 2
