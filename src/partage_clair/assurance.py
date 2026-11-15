"""Local preparation controls. These scores are not reidentification probabilities."""

import hashlib
import math
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageChops
from pypdf import PdfReader

from .context import DIRECT, INFERENCE, LINKABLE
from .core import Document, DocumentError, check_cancel, label_bounds, label_patch

CRITERIA = {
    'individualisation': ('Individualisation',
        'Puis-je reconnaître une personne par un détail unique ou une combinaison '
        '(âge, lieu, métier, événement), même sans son nom ?'),
    'correlation': ('Corrélation',
        'Un destinataire pourrait-il relier cette copie à un autre document, une publication '
        'ou une source publique grâce aux dates, références, liens ou lieux ?'),
    'inference': ('Inférence',
        'Ce qui reste permet-il de déduire une information sur une personne connue '
        '(santé, revenus, situation familiale ou judiciaire) ?'),
}


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while data := stream.read(1024 * 1024):
            digest.update(data)
    return digest.hexdigest()


def zone_covered(zone, masks):
    """Exact union coverage: overlapping masks cannot double-count an exposed hole."""
    rectangles = []
    for box in masks:
        if box.page != zone.page:
            continue
        x0, x1 = max(box.x0, zone.x0), min(box.x1, zone.x1)
        y0, y1 = max(box.y0, zone.y0), min(box.y1, zone.y1)
        if x0 < x1 and y0 < y1:
            if (x0, y0, x1, y1) == (zone.x0, zone.y0, zone.x1, zone.y1):
                return True
            rectangles.append((x0, y0, x1, y1))
    area = 0
    edges = sorted({x for r in rectangles for x in (r[0], r[2])})
    for left, right in zip(edges, edges[1:]):
        intervals = sorted((y0, y1) for x0, y0, x1, y1 in rectangles if x0 <= left and x1 >= right)
        length, end = 0, -1
        for low, high in intervals:
            length += max(0, high - max(low, end))
            end = max(end, high)
        area += (right - left) * length
    return area >= (zone.x1 - zone.x0) * (zone.y1 - zone.y0) * (1 - 1e-9)


@dataclass(frozen=True)
class ExportAudit:
    sha256: str
    pages: int
    structure_ok: bool
    masks_ok: bool
    ocr_complete: bool
    approved_residuals: int
    residual_groups: int
    warnings: tuple[str, ...]
    file_stamp: tuple[int, ...] = ()
    labels_ok: bool = True
    mode: str = 'assisted'

    @property
    def passed(self):
        return (self.structure_ok and self.masks_ok and self.labels_ok and (self.ocr_complete or self.mode == 'rules')
                and not self.approved_residuals)


def audit_export(source, path, masks, approved_findings, expected_digest, *, cancel=None, progress=None, labels=(), mode='assisted'):
    """Read back only the exported file. Never create new masks or store recognized text."""
    from .detection import canonical, scan

    path = Path(path)
    check_cancel(cancel)
    if file_digest(path) != expected_digest:
        raise DocumentError('La copie a changé depuis son export. Exportez et contrôlez une nouvelle copie.')
    source._verify(path)
    masks_ok = True
    labels_ok = True
    # Decode the actual embedded raster, avoiding PDF rendering interpolation.
    reader = PdfReader(path) if source.kind == 'pdf' else None
    for number in range(source.pages):
        check_cancel(cancel)
        if reader:
            with reader.pages[number].images[0].image as embedded:
                image = embedded.convert('RGB')
        else:
            with Image.open(path) as opened:
                image = opened.convert('RGB')
        try:
            for box in masks:
                if box.page != number + 1:
                    continue
                left, top = math.floor(box.x0 * image.width), math.floor(box.y0 * image.height)
                right, bottom = math.ceil(box.x1 * image.width), math.ceil(box.y1 * image.height)
                region = image.crop((left, top, right, bottom))
                try:
                    masks_ok &= region.getextrema() == ((0, 0),) * 3
                finally:
                    region.close()
            for label in labels:
                if label.box.page != number + 1:
                    continue
                bounds = label_bounds(label.box, image.size)
                region = image.crop(bounds)
                expected = label_patch(region.size, label.text)
                try:
                    difference = ImageChops.difference(region, expected)
                    try:
                        labels_ok &= difference.getbbox() is None
                    finally:
                        difference.close()
                finally:
                    region.close()
                    expected.close()
        finally:
            image.close()
    if mode not in ('assisted', 'rules'):
        raise DocumentError('Mode de contrôle inconnu.')
    residuals, report = 0, None
    if mode != 'rules':
        with Document(path) as output:
            index, report = scan(output, cancel=cancel, progress=progress)
            for finding in approved_findings:
                check_cancel(cancel)
                terms = finding.terms or (canonical(finding.value),)
                if index.find_terms(terms, cancel):
                    residuals += 1
    check_cancel(cancel)
    if file_digest(path) != expected_digest:
        raise DocumentError('La copie a changé pendant son contrôle. Aucun résultat validé.')
    warnings = list(report.warnings) if report else [
        'Contrôle sans IA : structure et pixels vérifiés ; aucune relecture OCR du texte de la copie. '
        'Les compteurs de texte résiduel ne sont pas mesurés. Relecture humaine indispensable.']
    if not masks_ok:
        warnings.append('Des pixels de zones validées ne sont pas entièrement noirs.')
    if not labels_ok:
        warnings.append('Un remplacement ne correspond pas aux pixels attendus.')
    if residuals:
        warnings.append('Du texte validé pour masquage est encore reconnu dans la copie.')
    # A fully blacked/blank page contains no OCR text by design. It still needs visual review,
    # but lack of text alone is not an OCR engine failure on the output.
    complete = report is not None and report.ocr_pages == report.pages and not any(
        'indisponible' in w or 'impossible' in w or 'incomplet' in w for w in report.warnings)
    stat = path.stat()
    return ExportAudit(expected_digest, source.pages, True, bool(masks_ok), complete,
                       residuals, len(report.findings) if report else 0, tuple(warnings),
                       (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns), bool(labels_ok), mode)


@dataclass(frozen=True)
class PreparationScore:
    value: int | None
    components: tuple[tuple[str, int, int], ...]
    direct_remaining: int
    indirect_remaining: int
    flags: tuple[str, ...]
    blockers: tuple[str, ...]


def preparation_score(report, masks, *, criteria_reviewed=False, copy_reviewed=False, audit=None, labels=()):
    if report is None:
        return PreparationScore(None, (), 0, 0, tuple(CRITERIA), ('Analyse locale requise.',))
    covered = {f.id for f in report.findings if f.zones and all(zone_covered(z, masks) for z in f.zones)}
    direct = [f for f in report.findings if f.kind in DIRECT]
    indirect = [f for f in report.findings if f.kind not in DIRECT]
    remaining = [f for f in report.findings if f.id not in covered]
    # Replacement content is still disclosed. Covering its source pixels does not
    # demonstrate that the retained information or pseudonym cannot be linked.
    from .detection import Finding
    retained = [Finding(f'retained-{i}', 'Pseudonyme' if label.method == 'pseudonym'
                        else 'Information généralisée', '', (label.box,)) for i, label in enumerate(labels)]
    indirect += retained
    remaining += retained
    direct_left = sum(f.id not in covered for f in direct)
    indirect_left = len(remaining) - direct_left
    from .detection_options import ALL_CATEGORIES
    full_scope = set(report.categories) == set(ALL_CATEGORIES)
    strict = report.mode == 'rules'
    ocr_complete = (report.pages > 0 and not report.warnings and
                    (report.text_pages == report.pages if strict else report.ocr_pages == report.pages))
    complete = ocr_complete and full_scope

    def points(findings, maximum):
        if not findings:
            return maximum if complete and criteria_reviewed else 0
        return math.floor(maximum * sum(f.id in covered for f in findings) / len(findings))

    export_ok = audit is not None and audit.passed
    components = (('Couverture de l’analyse locale', 15 if complete else 0, 15),
                  ('Zones d’identifiants directs couvertes', points(direct, 30), 30),
                  ('Zones d’indices indirects couvertes', points(indirect, 20), 20),
                  ('Revue humaine des trois risques', 15 if criteria_reviewed else 0, 15),
                  ('Relecture déclarée de la copie', 5 if copy_reviewed and export_ok else 0, 5),
                  ('Contrôle technique de la copie', 10 if export_ok else 0, 10))
    flags = []
    if remaining:
        flags.append('individualisation')
    if any(f.kind in LINKABLE or f.kind in DIRECT for f in remaining):
        flags.append('correlation')
    if any(f.kind in INFERENCE for f in remaining):
        flags.append('inference')
    blockers, cap = [], 95
    if strict:
        blockers.append('Mode sans IA : texte natif et règles uniquement ; pas de reconnaissance contextuelle '
                        'ni de relecture OCR de la copie. Score plafonné à 49, revue visuelle nécessaire.')
        cap = min(cap, 49)
    if not full_scope:
        blockers.append('Catégories désactivées : analyse partielle, même si toutes les suggestions sont masquées.')
        cap = min(cap, 49)
    by_page = {}
    for finding in remaining:
        if finding.kind not in DIRECT:
            for page in finding.pages:
                by_page.setdefault(page, set()).add(finding.kind)
    combinations = [str(p) for p, kinds in sorted(by_page.items()) if len(kinds) >= 2]
    if combinations:
        blockers.append('Combinaisons d’indices indirects à examiner page(s) ' + ', '.join(combinations)
                        + ' ; aucune association à une personne n’est déduite automatiquement.')
    if retained:
        flags = list(dict.fromkeys([*flags, 'correlation']))
        blockers.append('Des généralisations ou pseudonymes sont conservés : leur risque de recoupement n’est pas mesuré.')
    if not ocr_complete:
        blockers.append('Analyse incomplète ou page sans texte reconnu : contrôle manuel indispensable.')
        cap = min(cap, 49)
    if direct_left:
        blockers.append(f'{direct_left} groupe(s) d’identifiants directs restent exposés.')
        cap = min(cap, 49)
    if indirect_left:
        blockers.append(f'{indirect_left} groupe(s) d’indices indirects restent exposés.')
        cap = min(cap, 69)
    if not criteria_reviewed:
        blockers.append('Revue des trois risques non validée pour cet état du document.')
        cap = min(cap, 69)
    if not export_ok or not copy_reviewed:
        blockers.append('Copie actuelle à exporter, contrôler et relire.')
        cap = min(cap, 69)
    if audit and (not audit.masks_ok or not audit.labels_ok or audit.approved_residuals or not audit.structure_ok):
        blockers.append('Anomalie du contrôle de la copie : ne pas partager cet export.')
        cap = min(cap, 39)
    if audit and audit.residual_groups:
        blockers.append(f'{audit.residual_groups} groupe(s) encore proposés par l’OCR de la copie : relire.')
        cap = min(cap, 69)
    blockers.append('Recoupements externes et rareté dans la population non mesurés ; 5 points non attribués.')
    return PreparationScore(min(cap, sum(p[1] for p in components)), components,
                            direct_left, indirect_left, tuple(flags), tuple(blockers))


def anonymous_summary(score, audit=None):
    """A deliberate allowlist: no names, OCR text, purpose, paths or source hashes."""
    export_check = asdict(audit) if audit else None
    if export_check:
        export_check.pop('file_stamp')
        if audit.mode == 'rules':
            export_check['approved_residuals'] = None
            export_check['residual_groups'] = None
    return {'schema': 'partage-clair.preparation.v1', 'score_kind': 'preparation_not_probability',
            'score': score.value, 'maximum_tool': 95, 'cnil_certification': False,
            'components': [{'control': name, 'points': value, 'maximum': maximum}
                           for name, value, maximum in score.components],
            'direct_remaining': score.direct_remaining if score.value is not None else None,
            'indirect_remaining': score.indirect_remaining if score.value is not None else None,
            'criteria_to_review': list(score.flags), 'limitations': list(score.blockers),
            'export_check': export_check}
