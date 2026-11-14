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
