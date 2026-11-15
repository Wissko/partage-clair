"""Explainable context signals, not entity resolution or a rarity estimator."""

import ipaddress
import re

DIRECT = {'Nom', 'E-mail', 'Téléphone', 'IBAN', 'Carte bancaire', 'Adresse',
          'Date de naissance', 'Identifiant', 'Lien / compte', 'Adresse IP', 'Donnée bancaire',
          'Entreprise / client', 'Identifiant entreprise', 'Référence métier', 'Texte ajouté'}
INFERENCE = {'Contexte sensible', 'Montant', 'Âge', 'Profession / organisme', 'Contexte singulier',
             'Donnée métier'}
LINKABLE = {'Date précise', 'Horaire', 'Lieu', 'Profession / organisme', 'Identifiant',
            'Lien / compte', 'Adresse IP', 'Coordonnées GPS', 'Contexte singulier'}
MONTH = (r'janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[ée]cembre')
PATTERNS = (
    ('Date précise', r'\b(?:\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}-\d{2}-\d{2}|'
     rf'\d{{1,2}}(?:er)?\s+(?:{MONTH})\s+\d{{4}})\b'),
    ('Horaire', r'\b(?:[01]?\d|2[0-3])\s*[h:]\s*[0-5]\d\b'),
    ('Âge', r'\b\d{1,3}\s+ans\b|\bcentenaire[s]?\b'),
    ('Montant', r'(?<!\w)\d[\d .\u202f,]{0,18}\s*(?:€|euros?\b|EUR\b|dollars?\b|USD\b)'),
    ('Lieu', r'(?<![\w-])\d{5}[ \t]+[A-ZÀ-ÖØ-Þ][^\n\r;|]{1,65}'),
    ('Lieu', r'\b(?:ville|commune|domicile|r[ée]sidence|lieu(?: de naissance)?|n[ée]e? [àa])\s*[:=]\s*[^\n\r;|]{2,90}'),
    ('Lieu', r'\b(?:habite|r[ée]side|domicili[ée]e? [àa]|n[ée]e? [àa])\s+[^\n\r;|]{2,90}'),
    ('Lieu', r'\b(?:Paris|Marseille|Lyon|Toulouse|Nice|Nantes|Montpellier|Strasbourg|Bordeaux|Lille|'
     r'Rennes|Reims|Toulon|Saint-[ÉE]tienne|Le Havre|Grenoble|Dijon|Angers|N[îi]mes|Villeurbanne|'
     r'Clermont-Ferrand|Aix-en-Provence|Brest|Tours|Limoges|Amiens|Annecy|Perpignan|Besançon|'
     r'Metz|Orl[ée]ans|Rouen|Mulhouse|Caen|Nancy|Argenteuil|Montreuil|Saint-Denis|Avignon|Poitiers)\b'),
    ('Coordonnées GPS', r'(?<!\d)[+-]?\d{1,2}[.,]\d{4,}\s*[,;]\s*[+-]?\d{1,3}[.,]\d{4,}(?!\d)'),
    ('Profession / organisme', r'\b(?:profession|m[ée]tier|poste|employeur|entreprise|organisme|[ée]tablissement|'
     r'[ée]cole|universit[ée]|association|service)\s*[:=]\s*[^\n\r;|]{2,100}'),
    ('Profession / organisme', r'\b(?:chirurgien(?:ne)?|neurochirurgien(?:ne)?|maire|notaire|avocat(?:e)?|'
     r'enseignant(?:e)?|infirmi(?:er|ère)|ing[ée]nieur(?:e)?|direct(?:eur|rice)|pr[ée]sident(?:e)?|'
     r'chercheur|chercheuse|pilote|agriculteur|agricultrice|artisan|journaliste|policier|policière)\b'),
    ('Identifiant', r'\b(?:NIR|s[ée]curit[ée] sociale|num[ée]ro fiscal|passeport|CNI|carte d.identit[ée]|'
     r'num[ée]ro de dossier|r[ée]f[ée]rence(?: client)?|matricule|identifiant|immatriculation)'
     r'\s*(?:n[°o]\s*)?[:=#]?\s*[A-Z0-9][A-Z0-9 /.-]{3,45}\b'),
    ('Lien / compte', r'https?://[^\s<>]+|\bwww\.[^\s<>]+|(?<![\w@])@[\w.-]{2,}'),
    ('Adresse IP', r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])'),
    ('Adresse IP', r'(?<![\w:])(?:[A-F0-9]{0,4}:){2,7}[A-F0-9]{0,4}(?![\w:])'),
    ('Téléphone', r'(?<!\w)\+\d{1,3}[ .-]?(?:\d[ .-]?){6,13}\d(?!\d)'),
    ('Identifiant', r'(?<!\d)[12](?: ?\d){14}(?!\d)'),
    ('Identifiant', r'(?<![\w-])(?-i:[A-Z]{2,12})-\d{3,12}(?![\w-])'),
    # Entire lines are proposed so the identity-bearing relationship is not ignored.
    ('Contexte sensible', r'^[^\n\r]*(?:diagnostic|pathologie|maladie|hospitalis|traitement m[ée]dical|'
     r'handicap|cancer|VIH|s[ée]roposit|grossesse|religion|syndicat|orientation sexuelle|'
     r'condamnation|casier judiciaire|d[ée]tention|revenu|endettement)[^\n\r]*'),
    ('Contexte singulier', r'^[^\n\r]*(?:seul(?:e)?\s+(?:de|du|dans)|unique|rare|record|'
     r'accident|[ée]v[ée]nement|victime|t[ée]moin|conjoint|[ée]poux|[ée]pouse)[^\n\r]*'),
)
COMPILED = tuple((kind, re.compile(pattern, re.I | re.M)) for kind, pattern in PATTERNS)


def context_hits(text):
    for kind, pattern in COMPILED:
        for match in pattern.finditer(text):
            start, end = match.span()
            if kind == 'Adresse IP':
                try:
                    ipaddress.ip_address(match.group())
                except ValueError:
                    continue
            if end > start:
                yield kind, start, end


def explanation(kind):
    if kind in {'Entreprise / client', 'Identifiant entreprise', 'Référence métier', 'Donnée bancaire'}:
        return 'Valeur après un libellé métier ; occurrences exactes recherchées partout. À vérifier.'
    if kind == 'Donnée métier':
        return 'Passage métier potentiellement confidentiel : vérifier la ligne entière avant validation.'
    if kind in DIRECT:
        return 'Identifiant possible : peut identifier ou relier des documents. À vérifier.'
    if kind == 'Contexte sensible':
        return 'Contexte à relire pour le risque d’inférence ; aucune conclusion sur une personne.'
    if kind == 'Contexte singulier':
        return 'Détail potentiellement distinctif ; sa rareté réelle n’est pas mesurée.'
    return 'Indice indirect : peut réidentifier par combinaison ou recoupement. À vérifier.'
