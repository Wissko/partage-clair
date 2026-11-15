# Détection locale et validation groupée

Les propositions ne modifient jamais les masques par elles-mêmes. Le worker analyse le
document entier avant de renvoyer les groupes à l'interface. Le texte, les coordonnées,
les valeurs proposées et les validations restent en mémoire ; aucun rapport contenant
ces valeurs n'est écrit sur disque ni envoyé à un service.

## Texte et coordonnées

- PDF : caractères Unicode et rectangles PDFium, transformés dans l'espace de la page
  rendue. La conversion tient compte de la rotation et du recadrage.
- OCR : RapidOCR 3.10.0 et ONNX Runtime CPU. Les modèles fournis dans le paquet sont
  sélectionnés par chemins locaux explicites et vérifiés par SHA-256. Une absence ou une
  différence d'empreinte provoque un refus, sans téléchargement. La télémétrie ONNX Runtime
  est désactivée avant la création des sessions. L'entrée OCR est une image Pillow en mémoire.
- Les rectangles OCR couvrent les mots entiers, avec une marge conservatrice. Si un mot
  n'est pas alignable, la ligne entière est proposée. Les coordonnées ne sont pas estimées
  par une simple répartition proportionnelle de la largeur des caractères.
- Les rectangles qui se recouvrent entre extraction PDF et OCR sont regroupés de façon
  conservatrice. Le nombre affiché est un nombre de zones, pas une mesure d'exhaustivité.

## Types proposés

Depuis 0.7, scan() complète les règles avec un modèle de reconnaissance d'entités
français exécuté localement : [NERmemberta, CATIE](https://huggingface.co/CATIE-AQ/NERmemberta-4entities),
dans sa [conversion ONNX](https://huggingface.co/julienkilo/onnx_NERmemberta-4entities).
Il propose personnes, organisations et lieux dans les phrases, sans libellés obligatoires.
Il ne classe pas automatiquement toutes les formes de secrets commerciaux. Le modèle
ne s'entraîne pas sur les documents et ne remplace pas les détecteurs de formats.

Les sous-mots sont regroupés avant seuil de proposition (moyenne des sorties ≥ 0,5),
puis étendus aux mots entiers pour éviter de masquer seulement un morceau de mot.
Ces sorties ne sont pas des probabilités calibrées de confidentialité ou d'anonymat.
Les blocs ont 512 tokens et 64 tokens de chevauchement ; les couches sont aussi
relues par phrases. Les spans sont ramenés aux caractères d'origine, puis à la géométrie
PDFium/OCR. Les doublons chevauchants de même type sont réunis. Les noms propagent leurs
composants ; organisations/lieux propagent seulement leur expression entière.

Toutes ces propositions respectent les catégories cochées et requièrent une validation.
La revue indique combien de pages ont été traitées par le modèle. Les fichiers manquants,
altérés ou les erreurs d'inférence sont signalés ; les règles restent disponibles et le
score ne peut dépasser 49. Les tests avec des phrases fictives ne constituent pas un
benchmark représentatif de l'ensemble des documents d'entreprise.

L'installation explicite est `python scripts/fetch_ner_model.py` après installation de
`.[ocr,ner]`. Le script est réservé à l'installation/construction. L'analyse utilise
uniquement des chemins locaux. Le portable distribue le modèle à côté de l'exécutable.

| Fichier local | SHA-256 |
| --- | --- |
| model.onnx | 77454f580606e61c7e2aca67f220030547d6c7fc033318d156cddc5c091bd82f |
| tokenizer.json | 9a73847b1816a4ba8f99a11e602fc983d717b3cc393696239b2a57d32adbedca |
| config.json | a8d4eaade4e37245507b2f6ce955b794c7bd0c5a154a05223914f6a8f19a8a27 |

Voir [la notice et la licence du modèle](NER_MODEL_LICENSE.txt). Les poids ne sont pas
quantifiés : les variantes allégées évaluées ne conservaient pas les résultats requis.

Depuis 0.6, **Choisir les données…** donne accès à 12 catégories, toutes actives par défaut.
Le filtre s'applique dans le moteur aux règles de texte PDF et d'OCR, sur toutes les pages.
Une nouvelle sélection relance l'analyse sans masquer automatiquement ; les anciennes
validations restent exportables et visibles, même si leur catégorie a été désactivée.
Les nouvelles propositions excluent les familles décochées. Des familles différentes
peuvent couvrir des pixels communs ; ce ne sont pas des classes sémantiques exclusives.

Des règles de libellés métier proposent entreprises/clients, comptes/BIC/RIB, identifiants
d'entreprise, contrats, polices, sinistres, devis et factures. Les valeurs repérées sont
recherchées en entier ailleurs dans le document, sans découper les entreprises en mots.
Le compte libellé est proposé même avec une somme de contrôle invalide : il peut s'agir
d'une erreur OCR. Ces candidats ne certifient ni la validité d'un compte ni sa nature.
Des mots contextuels proposent aussi des lignes financières ou commerciales à relire.

La liste d'expressions confidentielles accepte jusqu'à 200 entrées (2 à 160 caractères),
une par ligne. Elle utilise les mêmes recherches de mots entiers, casse/accents ignorés.
Elle reste en mémoire pendant la session ; une entrée non trouvée ne bloque pas l'analyse
et ne prouve pas l'absence du secret. La recherche manuelle reste possible après analyse.
Le score plafonné à 49 signale toute sélection partielle. Le contrôle de l'export refait
une analyse de toutes les catégories et recherche les valeurs précédemment approuvées.
Les tests synthétiques couvrent ces catégories ; ils ne constituent pas une mesure de
rappel sur tous les documents de banque, d'assurance, de PME ou d'ETI.

E-mails, téléphones français, IBAN (modulo 97), numéros de carte (Luhn), adresses françaises,
dates de naissance explicitement libellées. Les noms sont proposés à partir de libellés
et de suites de mots avec des indices de capitalisation. Il ne s'agit pas d'une reconnaissance
universelle des personnes : des noms peuvent être manqués et des intitulés pris pour des noms.
Les e-mails tolèrent les espaces horizontaux ajoutés par l'OCR autour de `@` et des points
du domaine ; la zone proposée couvre aussi ces espaces.

## Noms validés

Un groupe de nom recherche le nom complet et ses composants significatifs sur toutes les
couches de texte du document. Les particules courantes ne sont pas propagées seules.
Les recherches ignorent casse et accents, normalisent espaces, tirets et apostrophes,
et imposent des frontières de mots. Elles ne font pas de rapprochement flou entre des
orthographes différentes : une correction ou variante peut être ajoutée explicitement.

La validation ajoute le groupe complet, et non seulement la zone visible. Les groupes
validés sont une couche distincte des rectangles manuels. En retirer une zone retire la
validation du groupe entier après confirmation. Annuler/rétablir restaure l'état complet.
Un export transmet les identifiants validés au worker, qui résout lui-même la géométrie
complète ; un identifiant inconnu provoque un refus. Réanalyser le même instantané conserve
les groupes déjà connus. Ouvrir un autre document efface l'index et les validations.

Toutes les occurrences **reconnues** sont couvertes. Une erreur OCR, une forme abrégée,
une image illisible ou une autre orthographe peut échapper à la recherche. Les avertissements
de couverture incomplète restent visibles. Les PDF exportés sont toujours reconstruits à
partir de pixels déjà masqués, sans texte caché, pièces jointes ni métadonnées d'origine.
Les originaux et les copies créées auparavant ne sont pas modifiés.

## Modèles et attributions

Les modèles proviennent du paquet RapidOCR 3.10.0. Ils sont redistribués sans modification,
avec les licences et notices du paquet. Copyright des poids : Baidu et/ou titulaires
PaddleOCR concernés ; code RapidOCR : RapidOCR Authors. Licence Apache-2.0 pour le code
et les modèles couverts. [Notice officielle et provenance des modèles](https://rapidai.github.io/RapidOCRDocs/main/en/model_licenses/).

| Modèle | SHA-256 |
| --- | --- |
| PP-OCRv6_det_small.onnx | 090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f |
| PP-OCRv6_rec_small.onnx | 6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884 |
| ch_ppocr_mobile_v2.0_cls_mobile.onnx | e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c |

L'installation et la construction téléchargent les dépendances. L'analyse des documents
n'effectue pas ce téléchargement. Les tests bloquent les requêtes HTTP et les connexions
Python pendant un véritable traitement OCR de données synthétiques. Aucun appel à une API
IA distante ni outil de télémétrie applicative n'est ajouté.
