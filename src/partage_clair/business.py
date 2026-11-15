"""Explainable business candidates, not a promise of sector-wide confidentiality."""

import re

# Values captured after explicit labels are also searched on every other page.
# Missing/invalid OCR checksums must not hide a labelled confidential account.
LABELS = (
    ('Entreprise / client', r'entreprise|soci[ée]t[ée]|raison sociale|d[ée]nomination sociale|'
     r'client(?: entreprise)?|fournisseur|partenaire|banque|assureur|courtier|b[ée]n[ée]ficiaire|'
     r'company|customer|supplier|insurer'),
    ('Donnée bancaire', r'IBAN|RIB|BIC(?:\s*/\s*SWIFT)?|SWIFT|'
     r'(?:num[ée]ro|n[°o])\s+(?:de\s+)?compte|compte bancaire|'
     r'code (?:banque|guichet|PIN)|cl[ée] RIB|cryptogramme|CVV|CVC|account number'),
    ('Identifiant entreprise', r'SIREN|SIRET|RCS|(?:num[ée]ro\s+de\s+)?TVA(?: intracommunautaire)?|LEI'),
    ('Référence métier', r'(?:num[ée]ro|n[°o]|r[ée]f[ée]rence|r[ée]f\.?)\s*(?:de |du |d[’\'])?'
     r'(?:contrat|police|sinistre|dossier|client|adh[ée]rent|soci[ée]taire|facture|devis|commande|pr[êe]t)|'
     r'(?:contrat|police|sinistre|dossier|facture|devis|commande|pr[êe]t)(?:\s+n[°o])?|'
     r'contract number|policy number|claim number'),
)
COMPILED_LABELS = tuple((kind, re.compile(
    rf'(?im)^[ \t]*(?:[-•][ \t]*)?(?:{labels})[ \t]*[:=][ \t]*'
    r'(?P<value>[^\n\r|;]{2,160})')) for kind, labels in LABELS)

BUSINESS_CONTEXT = re.compile(
    r'(?im)^[^\n\r]*(?:\b(?:primes?(?: (?:annuelle|mensuelle|d.assurance))?|cotisation|franchise|'
    r'sinistralit[ée]|provision|encours|solvabilit[ée]|taux(?: d.int[ée]r[êe]t)?|'
    r'scoring|score de cr[ée]dit|marge(?: brute| nette| commerciale)?|EBITDA|'
    r'chiffre d.affaires|co[ûu]t de revient|commission|remise|salaire|'
    r'capital|r[ée]sultat net|indemnit[ée]|garantie|risque assur[ée]|'
    r'strat[ée]gie|secret de fabrication|projet confidentiel|tarif n[ée]goci[ée])\b)[^\n\r]*')


def business_hits(text):
    for kind, pattern in COMPILED_LABELS:
        for match in pattern.finditer(text):
            start, end = match.span('value')
            yield kind, start, end, True
    for match in BUSINESS_CONTEXT.finditer(text):
        yield 'Donnée métier', *match.span(), False


def is_business_field(line):
    return any(pattern.match(line) for _, pattern in COMPILED_LABELS)
