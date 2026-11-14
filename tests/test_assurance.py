import json

import pytest

from partage_clair.assurance import (
    ExportAudit,
    anonymous_summary,
    audit_export,
    file_digest,
    preparation_score,
    zone_covered,
)
from partage_clair.core import Box, Document, DocumentError
from partage_clair.detection import DetectionIndex, Finding, ScanReport, scan
from tests.test_detection import make_pdf, simple_layer


def report_fixture():
    name = Finding('name', 'Nom', 'Alice Dupont', (Box(1, .1, .1, .4, .2),))
    town = Finding('town', 'Lieu', 'Lyon', (Box(1, .1, .3, .4, .4),))
    return ScanReport((name, town), (), 1, 1)


def good_audit(**changes):
    fields = dict(sha256='a' * 64, pages=1, structure_ok=True, masks_ok=True,
                  ocr_complete=True, approved_residuals=0, residual_groups=0, warnings=())
    fields.update(changes)
    return ExportAudit(**fields)


def test_union_coverage_never_double_counts_an_exposed_gap():
    zone = Box(1, .1, .1, .9, .9)
    assert zone_covered(zone, [Box(1, .1, .1, .5, .9), Box(1, .5, .1, .9, .9)])
    assert not zone_covered(zone, [Box(1, .1, .1, .6, .9)] * 3)
    assert not zone_covered(zone, [Box(2, .1, .1, .9, .9)])
    assert not zone_covered(zone, [Box(1, .1, .1, .499, .9), Box(1, .5, .1, .9, .9)])


def test_score_requires_analysis_and_no_motifs_is_not_proof_of_anonymity():
    assert preparation_score(None, []).value is None
    empty = ScanReport((), (), 1, 1)
    assert preparation_score(empty, []).value == 15
    assert preparation_score(empty, [], criteria_reviewed=True).value <= 69


def test_score_increases_only_with_full_coverage_and_current_review_and_copy():
    report = report_fixture()
    all_masks = [box for f in report.findings for box in f.zones]
    before = preparation_score(report, [])
    masked = preparation_score(report, all_masks)
    assert before.direct_remaining == before.indirect_remaining == 1
    assert masked.direct_remaining == masked.indirect_remaining == 0
    assert before.value < masked.value <= 69
    complete = preparation_score(report, all_masks, criteria_reviewed=True,
                                 copy_reviewed=True, audit=good_audit())
    assert complete.value == 95
    assert any('non mesurés' in b for b in complete.blockers)
    # A partial mask must not earn any points for a direct identifier.
    partial = preparation_score(report, [Box(1, .1, .1, .39, .2)])
    assert partial.direct_remaining == 1 and partial.components[1][1] == 0


@pytest.mark.parametrize('failure', ['incomplete', 'pixels', 'residual', 'new_signal'])
def test_incomplete_or_failed_controls_limit_score(failure):
    report = report_fixture()
    masks = [box for f in report.findings for box in f.zones]
    audit = good_audit()
    cap = 49
    if failure == 'incomplete':
        report = ScanReport(report.findings, ('OCR incomplet',), 1, 0)
    elif failure == 'pixels':
        audit, cap = good_audit(masks_ok=False), 39
    elif failure == 'residual':
        audit, cap = good_audit(approved_residuals=1), 39
    else:
        audit, cap = good_audit(residual_groups=1), 69
    assert preparation_score(report, masks, criteria_reviewed=True,
                             copy_reviewed=True, audit=audit).value <= cap


def test_context_suggestions_and_combinations_never_apply_masks():
    lines = ['Profession : neurochirurgienne', 'Ville : Lyon', 'Le 12 novembre 2020 à 14h30',
             'Elle a 103 ans et un revenu de 12000 euros.', 'Diagnostic : maladie rare.',
             'Référence client : AB-1234', 'https://example.test/profil/alice',
             'IP : 192.0.2.1 et 2001:db8::1']
    index = DetectionIndex([simple_layer(line) for line in lines])
    findings = index.suggest()
    kinds = {f.kind for f in findings}
    assert {'Profession / organisme', 'Lieu', 'Date précise', 'Horaire', 'Âge', 'Montant',
            'Contexte sensible', 'Contexte singulier', 'Identifiant', 'Lien / compte', 'Adresse IP'} <= kinds
    assert index.approved_zones([]) == ()
    score = preparation_score(ScanReport(findings, (), 1, 1), [])
    assert set(score.flags) == {'individualisation', 'correlation', 'inference'}
    assert any('Combinaisons' in b for b in score.blockers)


def test_custom_context_phrase_propagates_exact_phrase_only():
    index = DetectionIndex([simple_layer('Paris Technologies', 1), simple_layer('PARIS TECHNOLOGIES', 2),
                            simple_layer('Paris seulement', 3)])
    finding = index.add_term('Paris Technologies')
    assert finding.pages == (1, 2)
    assert finding.kind == 'Texte ajouté' and not index.approved_zones([])


def test_summary_excludes_recognized_values_and_never_claims_certification():
    report = report_fixture()
    payload = anonymous_summary(preparation_score(report, []), good_audit())
    text = json.dumps(payload)
    assert 'Alice' not in text and 'Dupont' not in text and 'Lyon' not in text
    assert payload['cnil_certification'] is False
    assert payload['score_kind'] == 'preparation_not_probability'


def test_real_export_audit_checks_pixels_structure_and_offline_ocr(tmp_path, monkeypatch):
    pytest.importorskip('rapidocr')
    import requests
    monkeypatch.setattr(requests.sessions.Session, 'request',
                        lambda *_args, **_kwargs: pytest.fail('Audit must remain offline'))
    path = make_pdf(tmp_path / 'source.pdf', ['Nom : Alice Dupont'])
    target = tmp_path / 'shared.pdf'
    with Document(path) as source:
        index, _ = scan(source, use_ocr=False)
        finding = index.add_name('Alice Dupont')
        source.export(target, list(finding.zones))
        audit = audit_export(source, target, finding.zones, [finding], file_digest(target))
        assert audit.passed and not audit.approved_residuals
        # The same valid raster PDF with the name exposed must be rejected.
        exposed = tmp_path / 'exposed.pdf'
        source.export(exposed, [])
        failed = audit_export(source, exposed, finding.zones, [finding], file_digest(exposed))
        assert not failed.masks_ok and failed.approved_residuals == 1 and not failed.passed
        with pytest.raises(DocumentError, match='changé'):
            audit_export(source, exposed, [], [], audit.sha256)
