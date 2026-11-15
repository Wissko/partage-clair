"""Local suggestions and whole-document name propagation. Never applies masks itself."""

import hashlib
import re
import unicodedata
from dataclasses import dataclass

from .core import Box, DocumentError, ExportCancelled, check_cancel
from .detection_options import ALL_CATEGORIES, DetectionOptions, category_for

MAX_CHARACTERS = 500_000
MAX_FINDINGS = 2000
PARTICLES = {'de', 'du', 'des', 'le', 'la', 'les', 'd', 'van', 'von', 'da', 'di'}
NOT_NAMES = set('nom prénom prenom name client titulaire adresse email mail téléphone telephone '
                'document fictif aucune donnee donnée réelle reelle exemple page bonjour monsieur '
                'madame docteur reference référence information informations sensibles france '
                'date naissance numéro numero dossier facture total merci cordialement'.split())
TRANSLATION = str.maketrans({'’': "'", '‐': '-', '‑': '-', '–': '-',
                            'œ': 'oe', 'Œ': 'oe', 'æ': 'ae', 'Æ': 'ae'})


def normalize(text):
    """Canonical text plus a map back to original character offsets."""
    output, positions = [], []
    for index, char in enumerate(text):
        char = char.translate(TRANSLATION)
        for part in unicodedata.normalize('NFKD', char.casefold()):
            if unicodedata.combining(part):
                continue
            if part.isspace():
                part = ' '
                if output and output[-1] == ' ':
                    continue
            output.append(part)
            positions.append(index)
    return ''.join(output), positions


def canonical(text):
    return normalize(text)[0].strip()


@dataclass(frozen=True)
class TextLayer:
    page: int
    text: str
    boxes: tuple[Box | None, ...]
    origin: str

    def __post_init__(self):
        if len(self.text) != len(self.boxes):
            raise ValueError('Text/geometry length mismatch')

    def zones(self, start, end):
        """Join characters on the same visual line, not across unrelated lines."""
        result = []
        for box in self.boxes[start:end]:
            if box is None:
                continue
            if result and same_line(result[-1], box):
                result[-1] = union(result[-1], box)
            else:
                result.append(box)
        return tuple(result)


def union(a, b):
    return Box(a.page, min(a.x0, b.x0), min(a.y0, b.y0), max(a.x1, b.x1), max(a.y1, b.y1))


def same_line(a, b):
    overlap = min(a.y1, b.y1) - max(a.y0, b.y0)
    return (a.page == b.page and overlap > .45 * min(a.y1 - a.y0, b.y1 - b.y0)
            and b.x0 <= a.x1 + .025 and b.x1 >= a.x0 - .025)


def merge_zones(zones):
    """Coalesce overlapping native/OCR geometry conservatively."""
    result = []
    for box in zones:
        for index, other in enumerate(result):
            if box.page != other.page:
                continue
            overlap = max(0, min(box.x1, other.x1) - max(box.x0, other.x0)) * max(
                0, min(box.y1, other.y1) - max(box.y0, other.y0))
            smaller = min((box.x1 - box.x0) * (box.y1 - box.y0),
                          (other.x1 - other.x0) * (other.y1 - other.y0))
            if overlap >= .45 * smaller:
                result[index] = union(other, box)
                break
        else:
            result.append(box)
    return tuple(sorted(result, key=lambda b: (b.page, b.y0, b.x0)))


@dataclass(frozen=True)
class Finding:
    id: str
    kind: str
    value: str
    zones: tuple[Box, ...]
    terms: tuple[str, ...] = ()
    reason: str = 'Motif local'

    @property
    def pages(self):
        return tuple(sorted({box.page for box in self.zones}))


@dataclass(frozen=True)
class ScanReport:
    findings: tuple[Finding, ...]
    warnings: tuple[str, ...]
    pages: int
    ocr_pages: int
    categories: tuple[str, ...] = ALL_CATEGORIES
    ner_pages: int = 0
    ner_requested: bool = False
    mode: str = 'assisted'
    profile: str = 'general'
    text_pages: int = 0
    manual_pages: tuple[int, ...] = ()


def identifier(kind, value):
    return hashlib.sha256(f'{kind}:{canonical(value)}'.encode()).hexdigest()[:20]


def name_terms(name):
    name = canonical(name)
    words = re.findall(r"\b[^\W_]+(?:[-'][^\W_]+)*\b", name)
    parts = [word for word in words if len(word) >= 2 and not word.isdigit() and word not in PARTICLES]
    return tuple(dict.fromkeys([name, *parts]))


def valid_iban(value):
    value = re.sub(r'\s', '', value).upper()
    if not 15 <= len(value) <= 34 or not re.fullmatch(r'[A-Z]{2}\d{2}[A-Z0-9]+', value):
        return False
    number = ''.join(str(ord(c) - 55) if c.isalpha() else c for c in value[4:] + value[:4])
    return int(number) % 97 == 1


def valid_card(value):
    digits = re.sub(r'\D', '', value)
    if not 13 <= len(digits) <= 19 or len(set(digits)) < 2:
        return False
    total = 0
    for index, digit in enumerate(reversed(digits)):
        number = int(digit) * (2 if index % 2 else 1)
        total += number - 9 if number > 9 else number
    return total % 10 == 0


PATTERNS = (
    ('E-mail', re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+[ \t]*@[ \t]*[\w-]+"
                          r"(?:[ \t]*\.[ \t]*[\w-]+)+", re.UNICODE)),
    ('Téléphone', re.compile(r'(?<!\w)(?:\+33[ .\-]?[1-9]|0[1-9])(?:[ .\-]?\d{2}){4}(?!\d)')),
    ('IBAN', re.compile(r'(?<!\w)[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}(?!\w)', re.I)),
    ('Carte bancaire', re.compile(r'(?<!\d)\d(?:[ \-]?\d){12,18}(?!\d)')),
    ('Adresse', re.compile(r'(?im)\b\d{1,4}[ ,]+(?:bis[ ]+|ter[ ]+)?(?:rue|avenue|av\.|boulevard|bd\.?|'
                           r'chemin|impasse|allée|allee|route|place|quai)[ ]+[^\n\r|;]{3,90}')),
    ('Date de naissance', re.compile(r'(?im)\b(?:n[ée]e? le|date de naissance|naissance)[ :]*'
                                     r'(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})')),
)
NAME_LABEL = re.compile(r'(?im)^[ \t]*(?:nom(?: complet| d[’\']usage)?|pr[ée]nom(?: et nom)?|'
                        r'surnom|pseudonyme|name|titulaire)[ :]+([^\n\r|;:]{2,70})')
NON_PERSON_LABEL = re.compile(r'^(?:adresse|ville|profession|metier|organisme|entreprise|employeur|'
                              r'etablissement|reference(?: client)?|date(?: de naissance)?|lieu|'
                              r'iban|courriel|e-?mail|telephone|montant|revenu)\s*:', re.I)
WORD = re.compile(r"[^\W\d_]+(?:[-'’][^\W\d_]+)*", re.UNICODE)


class DetectionIndex:
    def __init__(self, layers):
        self.layers = tuple(layers)
        if sum(len(layer.text) for layer in self.layers) > MAX_CHARACTERS:
            raise DocumentError('Document trop dense pour une analyse complète (500 000 caractères).')
        self.normalized = tuple(normalize(layer.text) for layer in self.layers)
        self.findings = {}
        self.warnings = []

    def find_terms(self, terms, cancel=None):
        zones = []
        for layer, (text, positions) in zip(self.layers, self.normalized):
            check_cancel(cancel)
            for term in terms:
                pattern = re.compile(r'(?<!\w)' + re.escape(canonical(term)) + r'(?!\w)')
                for match in pattern.finditer(text):
                    zones.extend(layer.zones(positions[match.start()], positions[match.end() - 1] + 1))
        return merge_zones(zones)

    def add_name(self, value, *, cancel=None, reason='Nom ajouté par l’utilisateur'):
        value = ' '.join(value.split())
        if not 2 <= len(value) <= 100 or not any(c.isalpha() for c in value):
            raise DocumentError('Saisissez un nom de 2 à 100 caractères.')
        terms = name_terms(value)
        zones = self.find_terms(terms, cancel)
        if not zones:
            raise DocumentError('Aucune occurrence reconnue de ce nom dans le document analysé.')
        finding = Finding(identifier('Nom', value), 'Nom', value, zones, terms, reason)
        self.findings[finding.id] = finding
        return finding

    def add_term(self, value, *, cancel=None):
        value = ' '.join(value.split())
        if not 2 <= len(value) <= 160:
            raise DocumentError('Saisissez un texte de 2 à 160 caractères.')
        zones = self.find_terms((value,), cancel)
        if not zones:
            raise DocumentError('Aucune occurrence reconnue de ce texte.')
        finding = Finding(identifier('Texte ajouté', value), 'Texte ajouté', value, zones,
                          (canonical(value),), 'Texte contextuel ajouté : validation requise partout.')
        self.findings[finding.id] = finding
        return finding

    def suggest(self, cancel=None, *, options=None, entities=()):
        from .business import business_hits, is_business_field
        from .context import context_hits, explanation
        from .profiles import profile_hits
        options = options or DetectionOptions()
        enabled = set(options.categories)
        names = {}
        groups = {}
        propagated = set()
        contextual_reasons = {}
        non_persons, persons = set(), set()
        for layer, entity in entities:
            check_cancel(cancel)
            value = ' '.join(layer.text[entity.start:entity.end].split())
            key = canonical(value)
            if entity.kind != 'Nom':
                non_persons.add(key)
            else:
                persons.add(key)
            if category_for(entity.kind) not in enabled:
                continue
            if len(value) > (100 if entity.kind == 'Nom' else 160):
                self.warnings.append('Une entité de contexte trop longue demande une vérification manuelle.')
                continue
            if entity.kind == 'Nom':
                names.setdefault(key, (value, 'Nom reconnu dans la phrase par le modèle local : à vérifier.'))
            else:
                entry = groups.setdefault((entity.kind, key), [value, []])
                entry[1].extend(layer.zones(entity.start, entity.end))
                propagated.add((entity.kind, key))
                description = 'Organisation' if entity.kind == 'Entreprise / client' else 'Lieu'
                contextual_reasons[entity.kind, key] = (
                    f'{description} reconnu dans la phrase par le modèle local : à vérifier.')
        for layer in self.layers:
            check_cancel(cancel)
            for kind, pattern in PATTERNS:
                if category_for(kind) not in enabled:
                    continue
                for match in pattern.finditer(layer.text):
                    start, end = match.span(1) if kind == 'Date de naissance' else match.span()
                    value = layer.text[start:end].strip()
                    if kind == 'IBAN' and not valid_iban(value):
                        continue
                    if kind == 'Carte bancaire' and not valid_card(value):
                        continue
                    key = canonical(value)
                    if kind == 'E-mail':
                        key = re.sub(r'\s', '', key)
                    if kind in ('IBAN', 'Téléphone', 'Carte bancaire'):
                        key = re.sub(r'[ .\-]', '', key)
                    entry = groups.setdefault((kind, key), [value, []])
                    entry[1].extend(layer.zones(start, end))
            for kind, start, end in context_hits(layer.text):
                if category_for(kind) not in enabled:
                    continue
                if kind == 'Profession / organisme' and is_business_field(layer.text[start:end]):
                    continue
                value = layer.text[start:end].strip()
                entry = groups.setdefault((kind, canonical(value)), [value, []])
                entry[1].extend(layer.zones(start, end))
            for kind, start, end, propagate in business_hits(layer.text):
                if category_for(kind) not in enabled:
                    continue
                value = layer.text[start:end].strip()
                key = kind, canonical(value)
                entry = groups.setdefault(key, [value, []])
                entry[1].extend(layer.zones(start, end))
                if propagate:
                    propagated.add(key)
            for kind, start, end in profile_hits(layer.text, options.profile):
                if category_for(kind) not in enabled:
                    continue
                value = layer.text[start:end].strip()
                if kind == 'Nom':
                    names.setdefault(canonical(value), (value, 'Règle du profil métier : à vérifier.'))
                else:
                    key = kind, canonical(value)
                    groups.setdefault(key, [value, []])[1].extend(layer.zones(start, end))
                    propagated.add(key)
            if len(groups) > MAX_FINDINGS:
                raise DocumentError('Trop de suggestions. Analyse arrêtée sans validation automatique.')
            if 'names' not in enabled:
                continue
            for match in NAME_LABEL.finditer(layer.text):
                value = match.group(1).strip(' ,.-')
                if any(c.isalpha() for c in value) and 1 <= len(WORD.findall(value)) <= 5:
                    names.setdefault(canonical(value), (value, 'Libellé de nom'))
            for line in layer.text.splitlines():
                if is_business_field(line) or NON_PERSON_LABEL.match(canonical(line)):
                    continue
                tokens = list(WORD.finditer(line))
                run = []
                for token in [*tokens, None]:
                    value = token.group() if token else ''
                    key = canonical(value)
                    previous = run[-1] if run else None
                    gap = line[previous.end():token.start()] if previous and token else ' '
                    allowed = (token is not None and key not in NOT_NAMES
                               and (value[0].isupper() or key in PARTICLES))
                    if not allowed or (previous and not gap.isspace()):
                        while run and canonical(run[-1].group()) in PARTICLES:
                            run.pop()
                        if 2 <= len(run) <= 5:
                            candidate = line[run[0].start():run[-1].end()]
                            names.setdefault(canonical(candidate), (candidate, 'Nom possible : à vérifier'))
                        run = []
                    if allowed:
                        run.append(token)
            if len(names) + len(groups) > MAX_FINDINGS:
                raise DocumentError('Trop de suggestions. Analyse arrêtée sans validation automatique.')
        if 'names' in enabled:
            for key, (value, reason) in names.items():
                # A company/place identified from context is not also a person
                # merely because its words happen to start with capitals.
                if key in non_persons and key not in persons:
                    continue
                self.add_name(value, cancel=cancel, reason=reason)
        for (kind, key), (value, zones) in groups.items():
            check_cancel(cancel)
            if (kind, key) in propagated:
                zones.extend(self.find_terms((value,), cancel))
            zones = merge_zones(zones)
            if zones:
                finding = Finding(identifier(kind, key), kind, value, zones,
                                  reason=contextual_reasons.get((kind, key), explanation(kind)))
                self.findings[finding.id] = finding
        if 'custom' in enabled:
            for term in options.terms:
                check_cancel(cancel)
                # A missing expression is not a scan failure or evidence of absence.
                if self.find_terms((term,), cancel):
                    self.add_term(term, cancel=cancel)
        if options.references:
            from .references import reference_findings
            for finding in reference_findings(self, options.references, enabled, cancel):
                previous = self.findings.get(finding.id)
                if previous:
                    from dataclasses import replace
                    finding = replace(finding, zones=merge_zones((*previous.zones, *finding.zones)))
                self.findings[finding.id] = finding
        if len(self.findings) > MAX_FINDINGS:
            raise DocumentError('Trop de suggestions. Analyse arrêtée sans validation automatique.')
        return tuple(sorted((f for f in self.findings.values() if category_for(f.kind) in enabled),
                            key=lambda f: (f.kind != 'Nom', f.kind, f.value.casefold())))

    def approved_zones(self, identifiers):
        zones = []
        for key in identifiers:
            if key not in self.findings:
                raise DocumentError('Une validation ne correspond plus au document. Relancez l’analyse.')
            zones.extend(self.findings[key].zones)
        return merge_zones(zones)


def scan(document, *, use_ocr=True, progress=None, cancel=None, options=None, use_ner=True):
    options = options or DetectionOptions()
    strict = options.mode == 'rules'
    if strict:
        use_ocr = use_ner = False
    layers, warnings, ocr_pages = [], [], 0
    text_pages, manual_pages = set(), set()
    engine = None
    if use_ocr:
        try:
            from .ocr import LocalOcr
            engine = LocalOcr()
        except Exception:
            warnings.append('OCR local indisponible : images, scans et texte dans les images non analysés.')
    total_chars = 0
    for page in range(document.pages):
        check_cancel(cancel)
        if progress:
            progress(page, document.pages)
        if document.kind == 'pdf':
            try:
                layer = document.text_layer(page)
                layers.append(layer)
                total_chars += len(layer.text)
                if layer.text.strip():
                    text_pages.add(page + 1)
                if strict and (not layer.text.strip() or document.has_visual_objects(page)
                               or any(c.isalpha() and b is None for c, b in zip(layer.text, layer.boxes))):
                    manual_pages.add(page + 1)
            except Exception:
                warnings.append(f'Page {page + 1} : extraction du texte PDF impossible.')
                manual_pages.add(page + 1)
        elif strict:
            manual_pages.add(page + 1)
        if engine:
            image = document.render(page, 150)
            try:
                layer = engine.layer(image, page + 1)
                layers.append(layer)
                total_chars += len(layer.text)
                ocr_pages += 1
                if not layer.text.strip():
                    warnings.append(f'Page {page + 1} : aucun texte OCR reconnu ; visuels à vérifier manuellement.')
            except Exception:
                warnings.append(f'Page {page + 1} : OCR incomplet ou impossible.')
            finally:
                image.close()
        if total_chars > MAX_CHARACTERS:
            raise DocumentError('Document trop dense pour une analyse complète (500 000 caractères).')
    check_cancel(cancel)
    index = DetectionIndex(layers)
    entities, ner_pages = [], set()
    ner_requested = not strict and bool({'names', 'companies', 'addresses'} & set(options.categories))
    if progress:
        progress(document.pages, document.pages)
    if ner_requested:
        try:
            if not use_ner:
                raise DocumentError('Context recognition disabled')
            from .ner import LocalNer
            recognizer = LocalNer()
        except Exception:
            warnings.append('Reconnaissance du contexte indisponible : noms, organisations et lieux '
                            'peuvent manquer. Réinstallez le modèle local ; aucun téléchargement lancé.')
        else:
            for layer in layers:
                check_cancel(cancel)
                try:
                    entities.extend((layer, entity) for entity in recognizer.entities(layer.text, cancel=cancel))
                    ner_pages.add(layer.page)
                except ExportCancelled:
                    raise
                except Exception:
                    warnings.append(f'Page {layer.page} : reconnaissance du contexte incomplète.')
    findings = index.suggest(cancel, options=options, entities=entities)
    warnings.extend(index.warnings)
    if strict and manual_pages:
        warnings.append('Sans IA : pages avec images, éléments graphiques ou texte inexploitable à vérifier '
                        'manuellement : ' + ', '.join(map(str, sorted(manual_pages))) + '.')
    if progress:
        progress(document.pages, document.pages)
    report = ScanReport(findings, tuple(dict.fromkeys(warnings)), document.pages, ocr_pages,
                        options.categories, len(ner_pages), ner_requested, options.mode, options.profile,
                        len(text_pages), tuple(sorted(manual_pages)))
    return index, report
