"""Reproducible local demonstration. Every value is invented, never load user files."""

import argparse
import json
import math
import socket
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

import requests
from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from partage_clair.assurance import audit_export, file_digest, preparation_score, zone_covered
from partage_clair.core import Box, Document
from partage_clair.detection import canonical, scan
from partage_clair.methods import MethodChoice, generalisation, redaction_plan
from partage_clair.pdf_output import ImagePdfWriter

PAGES = [
    ['Document fictif', 'Nom : Alice Dupont', 'Email : alice.dupont@example.test',
     'Telephone : 06 12 34 56 78', 'Adresse : 12 rue des Fleurs', 'Ville : Lyon',
     'Date de naissance : 12/03/1990', 'Profession : neurochirurgienne', 'Age : 36 ans',
     'IBAN : FR76 3000 6000 0112 3456 7890 189', 'Reference client : DOS-4821'],
    ['Document fictif', 'ALICE signe. DUPONT confirme.', 'Le 14 novembre 2026 a 14h30',
     'Revenu : 4200 euros', 'Diagnostic : maladie rare.',
     'Compte : https://example.test/personnes/alice', 'Repere personnel : ORION-7391'],
    ['Document fictif', 'Nom : ALICE DUPONT', 'Courriel : alice.dupont@example.test',
     'Telephone : +33 6 12 34 56 78', 'Organisme : Clinique Exemple',
     'Observation : AZUR-9284'],
]
EXPECTED = [
    ['Alice Dupont', 'alice.dupont@example.test', '06 12 34 56 78', '12 rue des Fleurs', 'Lyon',
     '12/03/1990', 'neurochirurgienne', '36 ans', 'FR76 3000 6000 0112 3456 7890 189', 'DOS-4821'],
    ['ALICE', 'DUPONT', '14 novembre 2026', '14h30', '4200 euros', 'maladie rare',
     'https://example.test/personnes/alice', 'ORION-7391'],
    ['ALICE DUPONT', 'alice.dupont@example.test', '+33 6 12 34 56 78', 'Clinique Exemple', 'AZUR-9284'],
]


def make_fixture(folder):
    writer = PdfWriter()
    for lines in PAGES:
        page = writer.add_blank_page(600, 800)
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({
            NameObject('/F1'): DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica'),
                NameObject('/Encoding'): NameObject('/WinAnsiEncoding')})})})
        commands = ['BT /F1 16 Tf 40 745 Td']
        commands += [f'<{line.encode("cp1252").hex()}> Tj 0 -47 Td' for line in lines]
        commands.append('ET')
        stream = DecodedStreamObject()
        stream.set_data('\n'.join(commands).encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
    native = folder / 'fixture-native.pdf'
    writer.write(native)
    truth = []
    with Document(native) as doc:
        for page, values in enumerate(EXPECTED):
            layer = doc.text_layer(page)
            raster = doc.render(page, 150)
            try:
                for value in values:
                    start = layer.text.index(value)
                    ink_zones = []
                    for box in layer.zones(start, start + len(value)):
                        left, top = math.floor(box.x0 * raster.width), math.floor(box.y0 * raster.height)
                        region = raster.crop((left, top, math.ceil(box.x1 * raster.width), math.ceil(box.y1 * raster.height)))
                        try:
                            foreground = region.convert('L').point(lambda p: 255 if p < 230 else 0)
                            try:
                                ink = foreground.getbbox()
                            finally:
                                foreground.close()
                        finally:
                            region.close()
                        assert ink is not None
                        ink_zones.append(Box(page + 1, (left + ink[0]) / raster.width,
                                             (top + ink[1]) / raster.height, (left + ink[2]) / raster.width,
                                             (top + ink[3]) / raster.height))
                    truth.append({'page': page + 1, 'value': value, 'zones': tuple(ink_zones)})
            finally:
                raster.close()
        image = doc.render(2, 150)
        try:
            with (folder / 'fixture-scan.pdf').open('wb') as stream:
                scanned = ImagePdfWriter(stream, [(600, 800)])
                scanned.page(0, image)
                scanned.finish()
        finally:
            image.close()
    mixed = PdfWriter()
    native_reader, scan_reader = PdfReader(native), PdfReader(folder / 'fixture-scan.pdf')
    for page in native_reader.pages[:2]:
        mixed.add_page(page)
    mixed.add_page(scan_reader.pages[0])
    source = folder / 'document-fictif.pdf'
    mixed.write(source)
    return source, truth


def exercise(folder):
    folder.mkdir(parents=True, exist_ok=True)
    if any(folder.iterdir()):
        raise ValueError('Choisissez un dossier neuf ou vide pour ne remplacer aucun résultat existant.')
    source, truth = make_fixture(folder)
    states = []

    def record(name, report, masks, **options):
        score = preparation_score(report, masks, **options)
        states.append({'stage': name, **asdict(score)})
        return score

    record('Avant analyse', None, [])
    with Document(source) as doc:
        index, report = scan(doc)
        assert report.ocr_pages == 3 and not report.warnings
        record('Après détection, aucune validation', report, [])
        name = next(f for f in report.findings if f.kind == 'Nom' and canonical(f.value) == 'alice dupont')
        name_masks = index.approved_zones([name.id])
        record('Après validation du nom sur toutes les pages', report, name_masks)
        approved = dict(index.findings)
        masks, _ = redaction_plan([], approved, {})
        record('Après validation des suggestions automatiques', report, masks)
        missed = [row for row in truth if not all(zone_covered(z, masks) for z in row['zones'])]
        # This controlled exercise knows the expected values and their physical boxes.
        # A real document needs the user's review instead of this ground truth.
        manual = []
        supplements = []
        for row in missed:
            try:
                finding = index.add_term(row['value'])
                approved[finding.id] = finding
                supplements.append({'page': row['page'], 'value': row['value'], 'via': 'recherche exacte'})
            except ValueError:
                manual.extend(row['zones'])
                supplements.append({'page': row['page'], 'value': row['value'], 'via': 'rectangle manuel'})
        report = replace(report, findings=tuple(index.findings.values()))
        masks, _ = redaction_plan(manual, approved, {})
        record('Après compléments manuels validés', report, masks)
        record('Après revue des trois risques (déclaration simulée)', report, masks, criteria_reviewed=True)
        target = folder / 'copie-masquee.pdf'
        doc.export(target, masks)
        audit = audit_export(doc, target, masks, tuple(approved.values()), file_digest(target))
        assert audit.passed and not audit.approved_residuals
        record('Après contrôle technique de la copie', report, masks, criteria_reviewed=True, audit=audit)
        final = record('Après relecture de la copie (déclaration simulée)', report, masks,
                       criteria_reviewed=True, copy_reviewed=True, audit=audit)
        remaining = [(row['page'], row['value']) for row in truth
                     if not all(zone_covered(z, masks) for z in row['zones'])]
        assert not remaining, remaining
        alternatives = []
        age = next(f for f in report.findings if f.kind == 'Âge')
        for method, finding, text, filename in (
                ('generalise', age, generalisation(age), 'copie-generalisee.pdf'),
                ('pseudonym', name, 'Personne A', 'copie-pseudonymisee.pdf')):
            black, labels = redaction_plan(manual, approved, {finding.id: MethodChoice(method, text)})
            assert labels, 'This example must visibly retain the replacement.'
            path = folder / filename
            doc.export(path, black, labels=labels)
            check = audit_export(doc, path, black, tuple(approved.values()), file_digest(path), labels=labels)
            assert check.passed
            score = preparation_score(report, [*black, *(label.box for label in labels)],
                                      criteria_reviewed=True, copy_reviewed=True, audit=check, labels=labels)
            assert score.value <= 69
            alternatives.append({'method': method, 'replacement': text, 'labels': len(labels),
                                 'score': asdict(score), 'audit': asdict(check), 'pdf': filename})
        for page in (0, 2):
            image = doc.render(page, 100)
            image.save(folder / f'avant-page-{page + 1}.png')
            image.close()
    for filename in ('copie-masquee', 'copie-generalisee', 'copie-pseudonymisee'):
        with Document(folder / (filename + '.pdf')) as output:
            for page in range(output.pages):
                image = output.render(page, 100)
                try:
                    image.save(folder / f'{filename}-page-{page + 1}.png')
                finally:
                    image.close()
                assert not output.text_layer(page).text
    # Every expected source region of the fully masked copy must be black, not just unreadable by OCR.
    with Document(target) as output:
        for row in truth:
            image = output.render(row['page'] - 1, 150)
            try:
                for box in row['zones']:
                    region = image.crop((int(box.x0 * image.width) + 2, int(box.y0 * image.height) + 2,
                                         int(box.x1 * image.width) - 1, int(box.y1 * image.height) - 1))
                    try:
                        assert region.getextrema() == ((0, 0),) * 3, row['value']
                    finally:
                        region.close()
            finally:
                image.close()
    # A document layout comparison, rendered from the actual source and actual export.
    comparison = PdfWriter()
    page = comparison.add_blank_page(1100, 870)
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({
        NameObject('/Heading'): DictionaryObject({NameObject('/Type'): NameObject('/Font'),
            NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica'),
            NameObject('/Encoding'): NameObject('/WinAnsiEncoding')})})})
    texts = [(40, 825, 'Avant validation - score 15/100'),
             (580, 825, 'Masques valides - score 65/100'),
             (40, 48, 'Document entierement fictif. Score de preparation : pas une probabilite d anonymat.'),
             (40, 26, '95/100 apres revue et relecture simulees ; controles techniques reels et locaux.')]
    content = DecodedStreamObject()
    content.set_data('\n'.join(f'BT /Heading {19 if y > 800 else 12} Tf {x} {y} Td <{text.encode("cp1252").hex()}> Tj ET'
                               for x, y, text in texts).encode())
    page[NameObject('/Contents')] = comparison._add_object(content)
    source_reader, output_reader = PdfReader(source), PdfReader(target)
    page.merge_transformed_page(source_reader.pages[0], Transformation().scale(.8).translate(28, 125))
    page.merge_transformed_page(output_reader.pages[0], Transformation().scale(.8).translate(568, 125))
    comparison.write(folder / 'comparaison.pdf')
    with Document(folder / 'comparaison.pdf') as layout:
        image = layout.render(0, 90)
        try:
            image.save(folder / 'comparaison.png')
        finally:
            image.close()
    result = {'synthetic_only': True, 'pages': 3, 'scanned_pages': 1,
              'expected_sensitive_regions': len(truth), 'automatic_covered_regions': len(truth) - len(missed),
              'automatic_groups': len(approved) - len(supplements),
              'manual_supplements': supplements, 'states': states, 'alternatives': alternatives,
              'final_score': final.value, 'audit': asdict(audit),
              'limits': 'Un cas fictif, pas un taux de précision général. Déclarations humaines simulées pour le calcul.'}
    (folder / 'resultats-demo.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'folder': str(folder), 'expected_regions': len(truth), 'supplements': supplements,
                      'scores': [(row['stage'], row['value']) for row in states],
                      'alternatives': [(row['method'], row['score']['value']) for row in alternatives]},
                     ensure_ascii=False, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('tmp/demo-anonymisation'))
    args = parser.parse_args()
    # Any attempted network access fails this demonstration; only generated local data is used.
    with (patch.object(requests.sessions.Session, 'request', side_effect=AssertionError('Offline test')),
          patch.object(socket, 'create_connection', side_effect=AssertionError('Offline test'))):
        exercise(args.output.resolve())


if __name__ == '__main__':
    main()
