"""User-selected rule profiles. No learned classification or automatic approval."""

import re

PROFILES = {'general': 'Général', 'bank': 'Banque', 'insurance': 'Assurance'}
FIELDS = {
    'bank': (
        ('Donnée bancaire', r'num[ée]ro de pr[êe]t|compte (?:courant|[ée]pargne|titres)|code agence'),
        ('Donnée métier', r'solde(?: disponible| du compte)?|d[ée]couvert autoris[ée]|TAEG|TEG|encours|'
         r'capacit[ée] d.emprunt|[ée]ch[ée]ance de pr[êe]t|mensualit[ée]'),
        ('Nom', r'conseiller(?: bancaire)?|co.?emprunteur|emprunteur'),
    ),
    'insurance': (
        ('Référence métier', r'num[ée]ro (?:d.assur[ée]|d.adh[ée]sion|de garantie)|num[ée]ro de soci[ée]taire'),
        ('Nom', r'assur[ée]e?|souscripteur|conducteur(?: principal)?|expert mandat[ée]'),
        ('Donnée métier', r'capital assur[ée]|montant garanti|bonus.?malus|coefficient de r[ée]duction|'
         r'indemnisation|plafond de garantie'),
        ('Adresse', r'adresse du risque|lieu du sinistre'),
    ),
}
COMPILED = {profile: tuple((kind, re.compile(
    rf'(?im)^[ \t]*(?:{labels})[ \t]*[:=][ \t]*(?P<value>[^\n\r|;]{{2,100}})'))
    for kind, labels in fields) for profile, fields in FIELDS.items()}


def profile_hits(text, profile):
    for kind, pattern in COMPILED.get(profile, ()):
        for match in pattern.finditer(text):
            yield kind, *match.span('value')
