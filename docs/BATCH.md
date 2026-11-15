# Listes d'entreprise, profils et traitement par lots

Le lot analyse plusieurs fichiers, puis attend votre choix des masques et votre validation
de chaque document. Il ne déclare pas automatiquement un document anonyme.

## Configurer avant analyse

Ouvrez **Traiter un lot…**, puis **Mode, listes et profil…**. Le mode par défaut du lot
est Sans IA ; vous pouvez choisir l'assistance locale avant analyse. Les profils Banque
et Assurance ajoutent des règles de champs à celles du profil général, sans prédire le
type du document ni promettre une couverture exhaustive du secteur.

Dans l'onglet des listes, importez vos clients et salariés (CSV UTF-8, UTF-16 avec BOM ou
Windows-1252 ; séparateur virgule, point-virgule ou tabulation). Colonnes reconnues :

| Information | En-têtes possibles |
| --- | --- |
| Personne | prenom + nom, nom_complet, salarie |
| Entreprise | entreprise, societe, raison_sociale, client |
| Courriel | email, mail, courriel |
| Téléphone | telephone, tel, mobile |
| Identifiant | identifiant, matricule, reference_client |
| Compte | iban, rib, compte_bancaire |

Les autres colonnes ne sont pas utilisées. Un fichier de plus de 5 Mo ou plus de 20 000
informations importées est refusé. Une cellule de nom doit tenir dans 100 caractères,
les autres valeurs dans 160. Une ligne incohérente refuse l'import entier, sans liste
partielle silencieuse. Les doublons sont regroupés. Les formules CSV ne sont jamais exécutées.

La colonne `nom` conserve le nom de famille composé ; préférez des colonnes `prenom` et
`nom` séparées. Avec seulement `nom_complet`, le dernier composant sert de nom de famille
présumé et doit être vérifié. Un nom complet ou nom de famille repéré propose le groupe. Un prénom seul ne suffit pas
à proposer tous les salariés qui le partagent. Une fois le groupe proposé, ses composants
sont inclus dans toutes les pages analysées, avec correspondances de mots entiers et
normalisation casse/accents. Les sociétés et autres valeurs sont recherchées entières.
Les homonymes demandent toujours votre vérification. Aucun modèle n'est entraîné sur les listes.

## Vérifier et exporter

1. Choisissez jusqu'à 100 PDF ou images (limites existantes : 50 pages / 100 Mo par fichier).
2. Analysez le lot. Une erreur de fichier reste isolée ; elle ne valide aucun autre fichier.
3. Sélectionnez un document. La liste indique les pages de chaque proposition. Sélectionner
   ou tout sélectionner n'applique rien. **Valider la sélection** ajoute les masques ;
   **Retirer les masques** les révoque. Glissez sur la page pour tracer un rectangle manuel.
4. Parcourez toutes les pages et confirmez **Cette page a été vérifiée** pour chacune.
5. Cliquez **Valider ce document pour export**. Un changement de masque annule cet accord.
6. Choisissez le dossier via **Exporter les documents validés…**. Les autres documents
   restent ignorés. Les copies portent des noms génériques, sans nom du fichier source.
7. Ouvrez et relisez les copies, particulièrement photos, signatures, graphiques et codes.

Les validations sont liées à l'empreinte du fichier réellement analysé. Un changement
refuse son aperçu/export avec les anciennes zones. Réanalyser ou changer de lot efface
les validations ; reconfigurez le lot après avoir rechargé les fichiers. Les listes et
états sont en mémoire pour la session, sans persistance ni envoi réseau.

Une annulation conserve les copies terminées. Si elle arrive pendant le contrôle d'une
copie déjà écrite, celle-ci est marquée à contrôler et non validée. Les échecs de contrôle
ne doivent pas être partagés. Les fichiers originaux et sorties existantes ne sont jamais écrasés.

## Contrôle sans IA

Ce mode n'utilise ni OCR ni modèle de reconnaissance, même pour contrôler l'export. Il
peut exploiter le texte natif d'un PDF, les règles et les listes. Une page scannée ou
comportant des objets graphiques est signalée pour contrôle manuel ; un élément non
textuel peut également échapper aux règles. Un nom absent des listes peut être manqué.

Le contrôle vérifie la structure et les pixels des zones choisies. Il ne mesure pas le
texte encore lisible dans les pixels : le bilan utilise `null` pour les résiduels, et
le score reste plafonné à 49. La validation humaine ne devient pas une certification.
L'assistance locale, si choisie explicitement, ajoute les étapes OCR/NER existantes.
