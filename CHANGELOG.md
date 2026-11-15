# Changelog

## 0.7.0 — 2026-11-15

- Reconnaissance du contexte français avec NERmemberta (CATIE), ONNX sur CPU, sans libellé requis.
- Propositions de personnes, organisations et lieux sur le texte PDF et OCR, y compris certains noms en minuscules.
- Blocs de 512 tokens avec chevauchement ; seconde lecture par phrases des couches longues.
- Propagation des noms et recherche des organisations/lieux dans les autres pages, sous validation explicite.
- Modèle et tokenizer vérifiés par taille et SHA-256 ; aucun téléchargement pendant l'analyse.
- Couverture du modèle visible ; avertissement et score limité à 49 en cas de modèle absent/échec.
- Portable incluant les poids dans models/ner à côté de l'exécutable pour éviter leur extraction à chaque lancement.
- Tests sans libellés, minuscules, longues séquences, accents, panne locale, absence de réseau et validation avant export.

## 0.6.0 — 2026-11-15

- Sélection de 12 catégories de détection, toutes cochées par défaut, avant ou après ouverture.
- Règles locales pour banque, assurance, PME/ETI : entreprises, comptes/BIC/RIB, SIRET/TVA,
  contrats, polices, sinistres, montants et passages métier potentiellement confidentiels.
- Expressions confidentielles en mémoire, une par ligne, recherchées sur toutes les pages.
- Valeurs après libellés métier propagées intégralement dans le document, sans découper les entreprises.
- Conservation des masques déjà approuvés après filtrage, aucune validation automatique nouvelle.
- Score rendu caduc lors d'un changement et plafonné à 49 pour une sélection partielle.
- Contrôle final de copie non filtré ; tests de sélection, propagation, score et export.

## 0.5.1 — 2026-11-15

- Analyse locale automatique après ouverture réussie d'un document, y compris au lancement avec un fichier.
- Validation humaine conservée avant tout masque, généralisation ou pseudonyme.
- Annulation et relance manuelle ; navigation et zoom sans réanalyse automatique.
- Tests d'ouverture PDF/image, absence de validation transférée, ouverture échouée et annulation sans boucle.
- Auto-test du portable vérifiant le parcours ouverture → OCR automatique → propositions non validées.

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
