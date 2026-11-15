# Modèle de confidentialité

## Objectif

Créer une copie de partage qui ne contient pas les objets PDF d'origine, les métadonnées
intégrées des fichiers pris en charge, ni les pixels des zones explicitement masquées.
L'original reste sur disque. L'application ne fait aucune requête réseau.

## Chaîne de traitement

PDF : instantané en mémoire → PDFium → pixels RGB → masques opaques → nouveau PDF
avec un unique XObject image par page et un flux de placement. Aucun objet source n'est
importé. Compression Flate avec prédiction PNG sans perte. Les pages strictement grises
sont stockées sur un canal sans modifier leurs pixels. Le PDF est rouvert pour vérifier le nombre de
pages et l'absence de métadonnées, texte extractible et annotations.

Les pages sont écrites progressivement dans un fichier temporaire du dossier de sortie.
Ce fichier ne contient que des pixels déjà masqués. Après vérification, une création
exclusive par lien physique publie le résultat sans écrasement sur les systèmes compatibles.
Sur FAT/exFAT ou un partage sans liens physiques, une copie exclusive est utilisée ; elle
préserve le refus d'écrasement et supprime la copie partielle en cas d'erreur gérée.
Le temporaire est nettoyé en fin d'opération, y compris lors d'une annulation. Un arrêt
brutal peut laisser un temporaire, et une interruption brutale pendant la copie de repli
peut laisser une sortie incomplète. Aucun effacement sécurisé n'est revendiqué.

L'interface communique avec un worker par files de messages ; aucun appel Tk n'est fait
depuis le worker. Les appels PDFium sont sérialisés, y compris entre plusieurs documents.
Le cache d'aperçus est borné et n'est jamais enregistré sur disque. La fermeture attend
la fin du traitement natif en cours avant de libérer les documents.

Image : Pillow → correction d'orientation EXIF → nouveau canevas RGB → masques opaques
→ PNG sans paramètres EXIF, ICC ou texte. La transparence est aplatie sur blanc pour
ne pas conserver de valeurs RGB cachées sous un canal alpha nul.

Les rectangles utilisent des coordonnées normalisées. Les bornes sont arrondies vers
l'extérieur, avec une marge d'au moins un pixel à l'export. Les masques ne sont jamais
enregistrés dans le PDF comme des objets réversibles. Le CLI permet de garder une liste
JSON de masques : ce fichier décrit les positions, pas le contenu du document.

## Analyse locale avant masquage

Depuis la version 0.5.1, ouvrir un document dans l'interface déclenche l'analyse locale
automatiquement, après ouverture réussie. Cela inclut un fichier fourni au lancement de
l'application. Cette analyse peut être annulée et ne valide jamais de zone ni de méthode.
Une ouverture échouée et la navigation ne déclenchent pas de réanalyse du fichier courant.

La version 0.3 propose une détection locale soumise à validation. L'index texte/coordonnées
est en mémoire. L'OCR utilise des modèles embarqués et des chemins explicites, sans
téléchargement à l'exécution ; la télémétrie ONNX Runtime est désactivée. Les propositions
ne deviennent des masques qu'après validation. Les noms validés sont propagés sur tout
l'index du document, y compris les composants significatifs du nom et du prénom.
Voir [DETECTION.md](DETECTION.md) pour les mécanismes, licences et limites.

Depuis la version 0.4, les indices indirects et contextuels sont aussi proposés à validation.
Le score interne de préparation et la revue guidée des trois risques restent en mémoire.
Le contrôle facultatif relit la copie exportée en local ; aucun masque supplémentaire
n'est appliqué par ce contrôle. Les déclarations et résultats sont invalidés après les
changements concernés. Le bilan facultatif n'exporte que des compteurs, contrôles et
l'empreinte de la copie, jamais les valeurs reconnues, l'utilité libre, les chemins ou
l'empreinte de l'original. Voir [ANONYMISATION.md](ANONYMISATION.md).

La version 0.5 permet de choisir masquage complet, réduction de précision ou pseudonyme
avant validation. Les pixels d'origine sont retirés avant toute inscription de nouveau
texte ; ce texte devient une partie visible de la copie et non une couche PDF éditable.
Les choix et pseudonymes restent en mémoire jusqu'à l'export de la copie, sans table de
correspondance sauvegardée par l'application. Le bilan JSON ne les inclut pas. Le contrôle
local compare aussi les pixels des remplacements à ceux attendus. Ils conservent un risque
de recoupement explicitement pris en compte dans les limites du score.

## Hors périmètre

- Garantir une détection exhaustive ou une lecture OCR sans erreur des données personnelles.
- Identifier automatiquement QR, filigranes, stéganographies, visages ou écriture manuscrite.
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
et composants tiers). Leurs licences restent applicables. Le portable Windows regroupe
Python, Tcl/Tk, RapidOCR/PaddleOCR, ONNX Runtime et leurs dépendances avec leurs avis dans `licenses/`, également inclus
dans l'exécutable. Le code du moteur PDF de sortie appartient au projet sous MIT.

