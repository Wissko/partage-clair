from dataclasses import replace

import pytest
from PIL import Image, ImageChops

from partage_clair.assurance import audit_export, file_digest, preparation_score
from partage_clair.core import (
    Box,
    Document,
    DocumentError,
    OutputLabel,
    cover,
    label_bounds,
    label_patch,
)
from partage_clair.detection import DetectionIndex, Finding, ScanReport, name_terms, scan
from partage_clair.methods import MethodChoice, generalisation, redaction_plan
from tests.test_detection import make_pdf, simple_layer


def finding(kind, value):
    return Finding('test', kind, value, (Box(1, .1, .1, .8, .3),))


@pytest.mark.parametrize(('kind', 'value', 'expected'), [
    ('Date de naissance', '12/03/1990', '1990'), ('Date précise', '2026-11-15', '2026'),
    ('Date précise', '1er février 2020', '2020'), ('Âge', '36 ans', '30-39 ans'),
    ('Âge', '9 ans', '0-9 ans'), ('Montant', '4 200,50 euros', '4 000 à <5 000 €'),
    ('Montant', '4200 USD', '4 000 à <5 000 $'), ('Date précise', '31/02/2026', None),
    ('Date précise', '12/03/90', None), ('Montant', '4.200 euros', None), ('Lieu', 'Lyon', None),
])
def test_generalisation_is_deterministic_and_refuses_ambiguous_values(kind, value, expected):
    assert generalisation(finding(kind, value)) == expected


def test_complete_masks_win_over_replacements_and_conflicts_are_black():
    age = finding('Âge', '36 ans')
    name = replace(age, id='other', kind='Nom', value='Alice Dupont')
    boxes, labels = redaction_plan([], {age.id: age}, {age.id: MethodChoice('generalise', '30-39 ans')})
    assert not boxes and len(labels) == 1
    boxes, labels = redaction_plan([age.zones[0]], {age.id: age}, {age.id: MethodChoice('generalise', '30-39 ans')})
    assert boxes and not labels
    boxes, labels = redaction_plan([], {age.id: age, name.id: name},
        {age.id: MethodChoice('generalise', '30-39 ans'), name.id: MethodChoice('pseudonym', 'Personne A')})
    assert len(boxes) == 2 and not labels
    with pytest.raises(DocumentError):
        redaction_plan([], {age.id: age}, {'unknown': MethodChoice('pseudonym', 'X')})
    with pytest.raises(DocumentError):
        redaction_plan([], {age.id: age}, {age.id: MethodChoice('generalise', '19 ans')})


def test_pseudonym_cannot_reintroduce_validated_name_components():
    index = DetectionIndex([simple_layer('Alice Dupont')])
    name = index.add_name('Alice Dupont')
    with pytest.raises(DocumentError, match='encore'):
        redaction_plan([], {name.id: name}, {name.id: MethodChoice('pseudonym', 'Alice A')})


def test_replacement_pixels_are_clipped_and_never_copy_originals():
    label = OutputLabel(Box(1, .1, .1, .9, .5), 'Personne A', 'pseudonym')
    source = Image.new('RGB', (400, 200), 'red')
    output = cover(source, [], [label])
    try:
        bounds = label_bounds(label.box, output.size)
        expected = label_patch((bounds[2] - bounds[0], bounds[3] - bounds[1]), label.text)
        region = output.crop(bounds)
        try:
            assert ImageChops.difference(region, expected).getbbox() is None
            assert output.getpixel((399, 199)) == (255, 0, 0)
            assert region.getextrema()[0] == region.getextrema()[1] == region.getextrema()[2]
        finally:
            expected.close()
            region.close()
    finally:
        source.close()
        output.close()
    with pytest.raises(DocumentError, match='petite'):
        label_patch((4, 4), 'long text')


def test_retained_information_keeps_score_prudent():
    age = finding('Âge', '36 ans')
    report = ScanReport((age,), (), 1, 1)
    _, labels = redaction_plan([], {age.id: age}, {age.id: MethodChoice('generalise', '30-39 ans')})
    score = preparation_score(report, age.zones, criteria_reviewed=True, copy_reviewed=True, labels=labels)
    assert score.indirect_remaining == 1 and score.value <= 69
    assert 'correlation' in score.flags


def test_ocr_name_variant_does_not_split_at_misrecognized_digit():
    assert name_terms('Alice Dup0nt') == ('alice dup0nt', 'alice', 'dup0nt')
    index = DetectionIndex([simple_layer('Alice Dup0nt. DUP0NT signe. DUP et NT restent.')])
    match = index.add_name('Alice Dup0nt')
    assert match.zones and not any(term in match.terms for term in ('dup', 'nt'))


def test_organisation_and_reference_regressions_from_annotated_demo():
    index = DetectionIndex([simple_layer('Organisme : Clinique Exemple'),
                            simple_layer('Repere : ORION-7391'), simple_layer('Observation : AZUR-9284')])
    findings = index.suggest()
    assert any(f.kind == 'Profession / organisme' and 'Clinique Exemple' in f.value for f in findings)
    assert {f.value for f in findings if f.kind == 'Identifiant'} >= {'ORION-7391', 'AZUR-9284'}
    assert not any(f.kind == 'Identifiant' for f in DetectionIndex([simple_layer('mai-2026')]).suggest())
    fields = DetectionIndex([simple_layer('Adresse : 12 rue des Fleurs'),
                             simple_layer('Reference client : DOS-4821'),
                             simple_layer('Organisme : Clinique Exemple')])
    assert not any(f.kind == 'Nom' for f in fields.suggest())


def test_name_after_separator_and_explicit_ocr_digit_label():
    index = DetectionIndex([simple_layer('Observation : Alice Dupont'), simple_layer('Nom : Alice Dup0nt', 2)])
    names = {f.value for f in index.suggest() if f.kind == 'Nom'}
    assert {'Alice Dupont', 'Alice Dup0nt'} <= names


def test_real_pdf_replacement_export_and_pixel_audit(tmp_path):
    pytest.importorskip('rapidocr')
    source = make_pdf(tmp_path / 'source.pdf', ['Nom : Alice Dupont\nAge : 36 ans'])
    with Document(source) as doc:
        index, _ = scan(doc, use_ocr=False)
        name = index.add_name('Alice Dupont')
        age = next(f for f in index.findings.values() if f.kind == 'Âge')
        approved = {name.id: name, age.id: age}
        choices = {name.id: MethodChoice('pseudonym', 'Personne A'),
                   age.id: MethodChoice('generalise', '30-39 ans')}
        black, labels = redaction_plan([], approved, choices)
        target = tmp_path / 'copy.pdf'
        doc.export(target, black, labels=labels)
        check = audit_export(doc, target, black, list(approved.values()), file_digest(target), labels=labels)
        assert check.passed and check.labels_ok and not check.approved_residuals
        with Document(target) as output:
            assert not output.text_layer(0).text
        bad = tmp_path / 'invalid.pdf'
        with pytest.raises(DocumentError, match='chevauche'):
            doc.export(bad, list(name.zones), labels=labels)
        assert not bad.exists()
