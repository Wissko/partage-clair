# Modèle de confidentialité

## Objectif

Créer une copie de partage qui ne contient pas les objets PDF d'origine, les métadonnées
intégrées des fichiers pris en charge, ni les pixels des zones explicitement masquées.
L'original reste sur disque. L'application ne fait aucune requête réseau.

## Chaîne de traitement

PDF : instantané en mémoire → PDFium → pixels RGB → masques opaques → nouveau PDF
avec un unique XObject image par page et un flux de placement. Aucun objet source n'est
importé. Compression Flate sans perte. Le PDF est rouvert pour vérifier le nombre de
pages et l'absence de métadonnées, texte extractible et annotations.

Image : Pillow → correction d'orientation EXIF → nouveau canevas RGB → masques opaques
→ PNG sans paramètres EXIF, ICC ou texte. La transparence est aplatie sur blanc pour
ne pas conserver de valeurs RGB cachées sous un canal alpha nul.

Les rectangles utilisent des coordonnées normalisées. Les bornes sont arrondies vers
l'extérieur, avec une marge d'au moins un pixel à l'export. Les masques ne sont jamais
enregistrés dans le PDF comme des objets réversibles. Le CLI permet de garder une liste
JSON de masques : ce fichier décrit les positions, pas le contenu du document.

## Hors périmètre

- Identifier automatiquement les données personnelles, QR, filigranes ou stéganographies.
- Préserver les signatures, l'accessibilité d'origine ou un PDF interrogeable.
- Garantir l'anonymat d'un document dont le contenu visible permet une réidentification.
- Résister à des fichiers malveillants exploitant PDFium/Pillow : pas de sandbox.
- Contrôler les sauvegardes, swap, logiciels tiers, services de synchronisation et
  métadonnées de système de fichiers. Choisir un dossier local adapté.
- Réduire les risques liés à une dépendance compromise lors de l'installation.

Les limites de taille réduisent certaines consommations de mémoire sans constituer
une protection complète contre le déni de service. Le décodage reste effectué dans le
processus utilisateur. Ne publiez jamais un document original dans une issue de bug.

## Dépendances

Pillow (HPND), pypdf (BSD-3-Clause), pypdfium2 (Apache-2.0/BSD-3-Clause avec avis PDFium
et composants tiers). Leurs licences restent applicables. Aucun binaire regroupant ces
dépendances n'est distribué par ce dépôt ; une future distribution devra inclure leurs avis.

