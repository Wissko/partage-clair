"""Explicit, reversible review choices; irreversible source removal only on export."""

import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_FLOOR, Decimal, InvalidOperation

from .core import DocumentError, OutputLabel


@dataclass(frozen=True)
class MethodChoice:
    method: str
    text: str

    def __post_init__(self):
        if self.method not in ('generalise', 'pseudonym'):
            raise DocumentError('Méthode de remplacement inconnue.')
        if (not isinstance(self.text, str) or not 1 <= len(self.text) <= 64
                or not self.text.strip() or any(ord(c) < 32 for c in self.text)):
            raise DocumentError('Le remplacement doit tenir sur une ligne de 1 à 64 caractères.')


def generalisation(finding):
    """Deterministic proposals, never invented facts, no geographic lookup."""
    from .detection import canonical
    value = canonical(finding.value)
    if finding.kind in ('Date précise', 'Date de naissance'):
        match = re.fullmatch(r'(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})', value)
        iso = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})', value)
        try:
            if match:
                day, month, year = map(int, match.groups())
                date(year, month, day)
                return str(year)
            if iso:
                year, month, day = map(int, iso.groups())
                date(year, month, day)
                return str(year)
        except ValueError:
            return None
        months = ('janvier', 'fevrier', 'mars', 'avril', 'mai', 'juin', 'juillet', 'aout',
                  'septembre', 'octobre', 'novembre', 'decembre')
        written = re.fullmatch(r'(\d{1,2})(?:er)?\s+(' + '|'.join(months) + r')\s+(\d{4})', value)
        if written:
            try:
                date(int(written[3]), months.index(written[2]) + 1, int(written[1]))
                return written[3]
            except ValueError:
                return None
    if finding.kind == 'Âge':
        match = re.fullmatch(r'(\d{1,3})\s+ans', value)
        if match and 0 <= int(match[1]) <= 130:
            base = int(match[1]) // 10 * 10
            return f'{base}-{base + 9} ans'
    if finding.kind == 'Montant':
        match = re.fullmatch(r'([\d .\u202f,]+)\s*(euros?|eur|€|dollars?|usd)', value)
        if match:
            try:
                # French decimal comma; reject ambiguous decimal-point inputs.
                numeric = match[1].strip()
                if '.' in numeric:
                    return None
                amount = Decimal(numeric.replace(' ', '').replace('\u202f', '').replace(',', '.'))
                base = int((amount / 1000).to_integral_value(rounding=ROUND_FLOOR)) * 1000
                currency = '$' if match[2] in ('dollar', 'dollars', 'usd') else '€'
                return f'{base:,} à <{base + 1000:,} {currency}'.replace(',', ' ')
            except (InvalidOperation, ValueError, OverflowError):
                return None
    return None


def overlaps(a, b):
    return (a.page == b.page and min(a.x1, b.x1) > max(a.x0, b.x0)
            and min(a.y1, b.y1) > max(a.y0, b.y0))


def redaction_plan(manual, approved, choices):
    if set(choices) - set(approved):
        raise DocumentError('Un remplacement ne correspond pas à une validation du document.')
    black, proposed = list(manual), []
    for key, finding in approved.items():
        choice = choices.get(key)
        if choice is None:
            black.extend(finding.zones)
            continue
        if not isinstance(choice, MethodChoice):
            raise DocumentError('Choix de méthode invalide.')
        if choice.method == 'generalise' and choice.text != generalisation(finding):
            raise DocumentError('La généralisation ne correspond plus à la valeur reconnue.')
        if choice.method == 'pseudonym':
            from .detection import canonical
            for term in finding.terms or (finding.value,):
                if re.search(r'(?<!\w)' + re.escape(canonical(term)) + r'(?!\w)', canonical(choice.text)):
                    raise DocumentError('Le pseudonyme contient encore une valeur à retirer. Choisissez un autre texte.')
        proposed.extend(OutputLabel(box, choice.text, choice.method) for box in finding.zones)
    proposed = list(dict.fromkeys(proposed))
    conflicts = {i for i, label in enumerate(proposed) if any(overlaps(label.box, b) for b in black)}
    for i, label in enumerate(proposed):
        for j in range(i + 1, len(proposed)):
            if overlaps(label.box, proposed[j].box):
                conflicts.update((i, j))
    # Complete black masks win. Ambiguous overlapping replacements are blacked out too.
    black.extend(label.box for i, label in enumerate(proposed) if i in conflicts)
    return black, tuple(label for i, label in enumerate(proposed) if i not in conflicts)
