# Changelog

## 0.5.0 — 2026-11-15

- Choix de méthode avant validation : occultation, généralisation déterministe, pseudonyme.
- Remplacements inscrits dans les pixels après suppression de la zone originale ; contrôle des pixels attendus.
- Conservation d'indices généralisés/pseudonymisés dans le score, plafonné à 69 ; priorité aux masques complets.
- Corrections de détection sur un document annoté de trois pages : organismes et références structurées.
- Réduction de confusions entre noms de personnes, adresses et références ; variantes OCR avec chiffres conservées entières.
- Script reproductible hors ligne, PDF natif + page scannée, sorties comparatives et scores par étape.

## 0.4.0 — 2026-11-14

- Suggestions locales d'indices indirects, références et passages contextuels ; recherche exacte globale.
- Revue humaine de l'individualisation, corrélation et inférence, utilité et destinataires de la copie.
- Score de préparation explicable /100 plafonné à 95, sans allégation de certification CNIL.
- Vérification locale de la copie : empreinte, structure, pixels masqués et seconde lecture OCR.
- Validations de revue et contrôle de copie rendus caducs après les changements concernés.
- Bilan JSON facultatif sans valeurs reconnues, texte OCR, chemins ni empreinte de l'original.
- Tests de couverture géométrique, plafonds du score, OCR résiduel et invalidation des validations.

## 0.3.0 — 2026-11-14

- Propositions locales de données sensibles à vérifier avant tout masquage.
- Texte PDF et OCR CPU des scans et images ; modèles embarqués vérifiés par SHA-256.
- Validation de noms sur toutes les pages, incluant prénom/nom séparés, casse et accents.
- Ajout manuel de noms à rechercher globalement, sans rapprochement flou implicite.
- Couche de groupes validés distincte des masques manuels ; retrait et historique groupés.
- Export des zones résolu dans l'index du worker ; aucune validation automatique.
- Ancienne copie désactivée dans l'interface quand de nouvelles modifications attendent l'export.
- Tests de propagation, rotations/recadrages, OCR sans HTTP et masques non relisibles après export.

## 0.2.0 — 2026-11-14

- Traitement et export en arrière-plan, progression, annulation et nettoyage des temporaires.
- Écriture PDF page par page, compression sans perte et canal gris lorsque les pixels le permettent.
- Zoom jusqu'à 400 %, défilement et liste des pages consultées avec compte des masques.
- Sélection/suppression, annuler/rétablir et raccourcis clavier ; avertissement avant perte des masques.
- Vérification de l'export avant publication exclusive ; repli pour systèmes sans liens physiques.
- Exécutable Windows portable avec licences, autotest hors ligne et workflow de construction.
- Tests d'interruption, conflits de fichiers, fidélité des pixels, worker et vraie boucle Tk.

## 0.1.0 — 2026-11-14

- Application locale en français pour PDF, PNG, JPEG et WebP statique.
- Masquage manuel opaque, navigation multipage et annulation du dernier masque.
- Reconstruction des PDF depuis les pixels et sortie image PNG sans métadonnées intégrées.
- Interface Tk et ligne de commande ; conservation des originaux.
- Tests sur fixtures synthétiques, CI Windows/Linux et documentation des limites.
