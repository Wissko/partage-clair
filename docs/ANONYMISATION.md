# Préparer une anonymisation : contrôles locaux et limites

Partage Clair aide à occulter un document. Il ne certifie pas l'anonymat du résultat.
La CNIL décrit les risques d'individualisation, de corrélation et d'inférence, recommande
de définir les informations utiles, de supprimer les identifiants et valeurs rares et de
choisir une précision adaptée aux informations conservées.
[Source CNIL consultée le 14 novembre 2026](https://www.cnil.fr/fr/technologies/lanonymisation-de-donnees-personnelles).

Notre traduction de ces principes en contrôles documentaires et **toutes les pondérations
ci-dessous appartiennent au projet**. La CNIL ne définit ni ne valide ce score. Il ne
constitue ni une probabilité de réidentification, ni une mesure de conformité au RGPD.

## Parcours

1. Analyser localement toutes les pages, texte PDF et OCR. Examiner les avertissements.
2. Inspecter les identifiants directs et les indices indirects ; ne valider que les zones
   réellement à masquer. Un groupe validé couvre toutes ses zones reconnues dans le document.
3. Ajouter les détails oubliés avec la recherche de texte exact, puis les inspecter et
   les valider. Cette recherche ne propage pas séparément les composants d'une phrase.
4. Dans **Score et revue des risques**, décrire l'utilité de la copie et choisir ses
   destinataires. Examiner les trois questions, compte tenu des connaissances que ces
   destinataires pourraient avoir, puis déclarer cette revue explicitement.
5. Exporter une nouvelle copie. **Contrôler la copie en local** relit effectivement ce fichier.
6. Ouvrir cette copie, examiner toutes ses pages et déclarer cette relecture.

La revue des risques et la relecture sont des déclarations humaines, distinctes du contrôle
technique. L'ouverture d'une page ou la détection d'un motif ne valent pas validation.
Une modification de masque (même suivie d'une annulation), une nouvelle recherche ou une
réanalyse rendent les validations de revue caduques. Un nouvel export doit être contrôlé
et relu. Le score n'empêche pas d'exporter : il expose les contrôles manquants.

## Ce qui est proposé

En plus des noms et coordonnées, des motifs locaux cherchent les dates numériques et
dates françaises écrites, horaires, âges, montants, codes postaux, lieux libellés et une
liste limitée de villes françaises, professions et organismes libellés, références,
identifiants potentiels, liens/comptes, IPv4/IPv6 et coordonnées GPS. Les lignes contenant
certains termes de santé, situation financière/judiciaire, famille ou événements distinctifs
sont proposées comme **contexte à examiner**. Cela n'attribue aucune caractéristique à une
personne et ne mesure pas la rareté d'une information dans la population.

Plusieurs catégories d'indices indirects encore visibles sur une même page déclenchent
une alerte de combinaison. Des personnes différentes peuvent être concernées : aucune
résolution d'identité ni corrélation avec des bases externes n'est effectuée. Les heuristiques
peuvent manquer des indices ou produire des faux positifs. La recherche manuelle et les
rectangles restent nécessaires. Les photos, signatures, QR, codes-barres et filigranes
ne sont pas reconnus automatiquement.

## Score de préparation /100, plafonné à 95

| Contrôle | Points maximum | Condition |
| --- | ---: | --- |
| Couverture locale | 15 | OCR exécuté sur toutes les pages, sans avertissement d'analyse |
| Identifiants directs | 30 | Proportion des groupes proposés dont toutes les zones sont couvertes |
| Indices indirects | 20 | Même calcul pour les autres groupes proposés |
| Revue des trois risques | 15 | Utilité, destinataires et trois examens déclarés pour l'état actuel |
| Relecture de la copie | 5 | Déclarée pour la copie actuelle ayant passé son contrôle technique |
| Contrôle technique | 10 | Structure, pixels et seconde lecture OCR de la copie contrôlés sans anomalie détectée |

Les deux proportions sont arrondies vers le bas. Un groupe ne gagne aucun crédit s'il
reste une de ses zones non couverte. La couverture tient compte de l'union des masques
manuels et validés, sans compter deux fois les surfaces qui se recouvrent. Si une catégorie
ne comporte aucune proposition, ses points ne sont accordés qu'après revue humaine et
analyse complète : l'absence de détection seule n'est pas une preuve.

Le résultat est le minimum entre la somme des points et les plafonds applicables :

- 49 si l'analyse est incomplète, une page n'a aucun texte OCR reconnu ou des identifiants
  directs proposés restent exposés ;
- 69 si des indices indirects restent exposés, la revue est manquante, la copie n'est pas
  contrôlée/relue ou l'OCR de sortie propose encore un groupe ;
- 39 si le contrôle détecte du texte validé encore reconnu, des pixels de masque non noirs
  ou une anomalie de structure ; un contrôle interrompu/échoué n'apporte aucun point d'export ;
- 95 dans tous les cas : 5 points restent non attribuables, car la connaissance extérieure,
  la rareté réelle et les capacités de recoupement ne sont pas mesurées.

Sans analyse, le score est **indisponible**, pas zéro ni cent. Les contrôles non applicables
ou non démontrés n'impliquent aucune conclusion favorable. Les faux positifs et les indices
conservés volontairement peuvent diminuer le score ; il n'est pas nécessaire ni toujours
utile de viser 95. Un score élevé signifie seulement que les contrôles définis ici ont été
remplis. Un détail non détecté peut toujours réidentifier quelqu'un, même à 95.

## Contrôle technique de la copie

Le worker mémorise à l'export la liste réellement appliquée et le SHA-256 de la copie.
Le contrôle refuse un fichier ayant changé depuis. Il vérifie les objets PDF attendus
(pages raster, absence de texte caché, métadonnées d'origine, annotations et objets annexes),
ou le PNG RGB sans métadonnées. Il décode les images réellement intégrées au PDF et vérifie
que les rectangles appliqués contiennent des pixels noirs. Il relance l'OCR local et cherche
les textes validés encore reconnus, ainsi que de nouvelles propositions.

L'empreinte est revérifiée après le contrôle. Dans l'interface, une modification détectée
de taille ou de dates système rend le résultat caduc. Le bilan reste lié à son SHA-256 :
il faut refaire le contrôle après toute modification, même extérieure à l'application.
La seconde lecture utilise le même OCR : ses erreurs peuvent être corrélées à celles de
l'analyse initiale. Elle ne constitue pas une preuve indépendante d'exhaustivité.
Une page de sortie sans texte reconnu peut simplement être entièrement masquée ; elle
est signalée pour relecture, sans être considérée comme un échec du moteur OCR.

## Confidentialité et bilan

Le score, l'utilité saisie, l'index, les masques et les déclarations restent en mémoire.
Le bilan JSON est facultatif et écrit seulement à la demande dans un nouveau fichier.
Il contient les compteurs, points, limites, résultats techniques et SHA-256 de la **copie**,
sans valeurs reconnues, extraits OCR, coordonnées de masques, noms de fichiers, chemins,
dates système, utilité libre saisie ou empreinte de l'original. Ce bilan n'est pas signé
et ne constitue ni un certificat ni une preuve d'audit indépendant. Aucun service réseau
n'est appelé par l'analyse ou le contrôle. La synchronisation éventuelle du dossier par
un autre logiciel reste hors du contrôle de Partage Clair.

La généralisation sémantique et la randomisation automatiques ne sont pas implémentées.
Le programme ne calcule pas de k-anonymat, l-diversité, t-proximité ou confidentialité
différentielle sur un PDF libre. Une évaluation de réidentification adaptée au contexte,
aux destinataires et aux sources externes reste nécessaire pour conclure à une anonymisation.
