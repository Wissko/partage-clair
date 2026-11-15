"""Bounded local CSV import and multi-pattern matching, without learned models."""

import csv
import re
from collections import deque
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

from .core import DocumentError, check_cancel

MAX_ENTRIES = 20_000
MAX_CSV_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class ReferenceEntry:
    kind: str
    value: str
    source: str
    family: str = ''

    def __post_init__(self):
        if self.source not in ('clients', 'employees') or self.kind not in {
                'Nom', 'Entreprise / client', 'E-mail', 'Téléphone', 'Identifiant', 'Donnée bancaire'}:
            raise DocumentError('Type de liste ou de donnée inconnu.')
        value = ' '.join(self.value.split())
        if not 2 <= len(value) <= (100 if self.kind == 'Nom' else 160):
            raise DocumentError('Valeur de liste trop courte ou trop longue (2 à 100/160 caractères).')
        object.__setattr__(self, 'value', value)
        family = ' '.join(self.family.split())
        if family:
            from .detection import canonical
            if self.kind != 'Nom' or len(family) > 100 or canonical(family) not in canonical(value):
                raise DocumentError('Le nom complet et la colonne nom sont incohérents.')
        object.__setattr__(self, 'family', family)


def load_csv(path, source, cancel=None):
    from .detection import canonical
    path = Path(path)
    with path.open('rb') as stream:
        data = stream.read(MAX_CSV_BYTES + 1)
    if len(data) > MAX_CSV_BYTES:
        raise DocumentError('Liste trop volumineuse (5 Mo maximum).')
    try:
        text = data.decode('utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')
    except UnicodeDecodeError:
        text = data.decode('cp1252')
    if '\0' in text:
        raise DocumentError('Utilisez un fichier CSV texte, pas un classeur Excel binaire.')
    try:
        dialect = csv.Sniffer().sniff(text.splitlines()[0] if text.splitlines() else '', delimiters=';,\t')
    except csv.Error:
        dialect = csv.excel
    def safe_rows():
        try:
            yield from csv.reader(StringIO(text, newline=''), dialect, strict=True)
        except csv.Error as error:
            raise DocumentError('CSV malformé : vérifiez les guillemets et les séparateurs.') from error
    rows = safe_rows()
    try:
        headers = next(rows)
    except StopIteration as error:
        raise DocumentError('La liste est vide.') from error
    aliases = {
        'nom': 'last', 'prenom': 'first', 'nomcomplet': 'full', 'fullname': 'full',
        'prenomnom': 'full', 'nomprenom': 'full', 'salarie': 'full',
        'entreprise': 'company', 'societe': 'company', 'raisonsociale': 'company', 'client': 'company',
        'email': 'email', 'mail': 'email', 'courriel': 'email',
        'telephone': 'phone', 'tel': 'phone', 'mobile': 'phone',
        'identifiant': 'id', 'matricule': 'id', 'referenceclient': 'id',
        'iban': 'bank', 'rib': 'bank', 'comptebancaire': 'bank',
    }
    columns = [aliases.get(re.sub(r'[^a-z0-9]', '', canonical(h))) for h in headers]
    recognized = [column for column in columns if column]
    if not recognized or len(recognized) != len(set(recognized)):
        raise DocumentError('En-têtes manquants ou ambigus. Utilisez prénom;nom;entreprise;email;telephone;matricule.')
    entries = {}
    for number, row in enumerate(rows, 2):
        check_cancel(cancel)
        if not any(cell.strip() for cell in row):
            continue
        if number > MAX_ENTRIES + 1 or len(row) != len(headers):
            raise DocumentError(f'Ligne {number} : colonnes incohérentes ou limite de 20 000 lignes dépassée.')
        fields = {column: cell.strip() for column, cell in zip(columns, row) if column}
        name = fields.get('full') or ' '.join(filter(None, (fields.get('first'), fields.get('last'))))
        values = [('Nom', name), ('Entreprise / client', fields.get('company')),
                  ('E-mail', fields.get('email')), ('Téléphone', fields.get('phone')),
                  ('Identifiant', fields.get('id')), ('Donnée bancaire', fields.get('bank'))]
        for kind, value in values:
            if value:
                entry = ReferenceEntry(kind, value, source, fields.get('last', '') if kind == 'Nom' else '')
                entries.setdefault((kind, canonical(entry.value), source), entry)
        if len(entries) > MAX_ENTRIES:
            raise DocumentError('La liste dépasse 20 000 informations. Réduisez ses colonnes ou ses lignes.')
    if not entries:
        raise DocumentError('Aucune information exploitable dans les colonnes reconnues.')
    return tuple(entries.values())


class MultiMatcher:
    """Aho–Corasick trie. Outputs follow failure links without quadratic suffix copies."""

    def __init__(self, terms):
        self.edges, self.fail, self.output = [{}], [0], [None]
        for term in terms:
            node = 0
            for char in term:
                if char not in self.edges[node]:
                    self.edges[node][char] = len(self.edges)
                    self.edges.append({})
                    self.fail.append(0)
                    self.output.append(None)
                node = self.edges[node][char]
            self.output[node] = term
        queue = deque(self.edges[0].values())
        while queue:
            node = queue.popleft()
            for char, child in self.edges[node].items():
                fallback = self.fail[node]
                while fallback and char not in self.edges[fallback]:
                    fallback = self.fail[fallback]
                self.fail[child] = self.edges[fallback].get(char, 0)
                queue.append(child)

    def matches(self, text, cancel=None):
        node = 0
        for end, char in enumerate(text, 1):
            if end % 1024 == 0:
                check_cancel(cancel)
            while node and char not in self.edges[node]:
                node = self.fail[node]
            node = self.edges[node].get(char, 0)
            current = node
            while current:
                term = self.output[current]
                if term:
                    start = end - len(term)
                    before = text[start - 1] if start else ''
                    after = text[end] if end < len(text) else ''
                    if not (before.isalnum() or before == '_' or after.isalnum() or after == '_'):
                        yield term, start, end
                current = self.fail[current]


def reference_findings(index, entries, categories, cancel=None):
    from .detection import MAX_FINDINGS, Finding, canonical, identifier, merge_zones, name_terms
    from .detection_options import category_for
    terms, selected, entry_terms = set(), {}, {}
    for entry in entries:
        check_cancel(cancel)
        if category_for(entry.kind) not in categories:
            continue
        key = identifier(entry.kind, entry.value)
        previous = selected.get(key)
        if previous and (previous.family or not entry.family):
            continue
        selected[key] = entry
        entry_terms[key] = name_terms(entry.value) if entry.kind == 'Nom' else (canonical(entry.value),)
        if entry.family:
            entry_terms[key] = tuple(dict.fromkeys((*entry_terms[key], canonical(entry.family))))
        terms.update(entry_terms[key])
    matcher, found, count = MultiMatcher(terms), {}, 0
    for layer, (text, positions) in zip(index.layers, index.normalized):
        for term, start, end in matcher.matches(text, cancel):
            zones = layer.zones(positions[start], positions[end - 1] + 1)
            if not zones:
                continue
            found.setdefault(term, []).extend(zones)
            count += 1
            if count > 100_000:
                raise DocumentError('Trop d’occurrences dans les listes ; analyse arrêtée sans masque.')
    emitted = 0
    for key, entry in selected.items():
        check_cancel(cancel)
        terms = entry_terms[key]
        # A shared first name alone must not nominate thousands of employees.
        # Once full name or surname is found, still cover every component.
        if entry.kind == 'Nom' and not (terms[0] in found or (canonical(entry.family) if entry.family else terms[-1]) in found):
            continue
        zones = [zone for term in terms for zone in found.get(term, ())]
        if not zones:
            continue
        emitted += 1
        if emitted > MAX_FINDINGS:
            raise DocumentError('Trop de correspondances dans les listes ; analyse arrêtée sans masque.')
        reason = ('Liste salariés' if entry.source == 'employees' else 'Liste clients') + ' : correspondance à vérifier.'
        if entry.kind == 'Nom':
            reason += ' Nom complet ou nom de famille repéré ; les composants sont regroupés ensuite.'
        yield Finding(key, entry.kind, entry.value, merge_zones(zones), terms, reason)
