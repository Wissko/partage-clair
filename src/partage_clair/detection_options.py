"""Explicit local analysis scope. No document content is persisted in preferences."""

from dataclasses import dataclass

from .core import DocumentError

CATEGORIES = (
    ('names', 'Noms de personnes'),
    ('addresses', 'Adresses, lieux et coordonnées GPS'),
    ('emails', 'Mails'),
    ('phones', 'Téléphones'),
    ('dates', 'Dates et horaires'),
    ('banking', 'Informations bancaires'),
    ('companies', 'Entreprises et clients'),
    ('amounts', 'Montants et prix'),
    ('references', 'Identifiants et références de contrats / dossiers'),
    ('business', 'Données métier : banque, assurance, PME / ETI'),
    ('context', 'Autres indices personnels et techniques'),
    ('custom', 'Mots et expressions confidentiels ajoutés'),
)
ALL_CATEGORIES = tuple(key for key, _ in CATEGORIES)
KINDS = {
    'Nom': 'names', 'Adresse': 'addresses', 'Lieu': 'addresses', 'Coordonnées GPS': 'addresses',
    'E-mail': 'emails', 'Téléphone': 'phones', 'Date de naissance': 'dates',
    'Date précise': 'dates', 'Horaire': 'dates', 'IBAN': 'banking', 'Carte bancaire': 'banking',
    'Donnée bancaire': 'banking', 'Entreprise / client': 'companies', 'Montant': 'amounts',
    'Identifiant': 'references', 'Référence métier': 'references',
    'Identifiant entreprise': 'references', 'Donnée métier': 'business', 'Texte ajouté': 'custom',
}


def category_for(kind):
    return KINDS.get(kind, 'context')


@dataclass(frozen=True)
class DetectionOptions:
    categories: tuple[str, ...] = ALL_CATEGORIES
    terms: tuple[str, ...] = ()

    def __post_init__(self):
        if not set(self.categories) <= set(ALL_CATEGORIES):
            raise DocumentError('Catégorie de détection inconnue.')
        if not self.categories:
            raise DocumentError('Sélectionnez au moins une catégorie à détecter.')
        if len(self.terms) > 200:
            raise DocumentError('Ajoutez au maximum 200 expressions confidentielles.')
        terms = tuple(dict.fromkeys(' '.join(term.split()) for term in self.terms if term.strip()))
        if any(not 2 <= len(term) <= 160 for term in terms):
            raise DocumentError('Chaque expression doit contenir de 2 à 160 caractères.')
        object.__setattr__(self, 'categories', tuple(k for k in ALL_CATEGORIES if k in self.categories))
        object.__setattr__(self, 'terms', terms)

    @property
    def full_scope(self):
        return self.categories == ALL_CATEGORIES
