# Partage Clair

**Préparez vos PDF et images avant de les partager. Vos fichiers restent sur votre ordinateur.**

Partage Clair permet de masquer un nom, une adresse ou une référence sur un document,
et de créer une copie sans reprendre ses métadonnées intégrées. Le projet est libre,
sans compte, sans abonnement, sans API et sans télémétrie.

**Version 0.1 : prototype fonctionnel pour des fichiers de confiance.** Aucun audit de
sécurité indépendant n'a encore été réalisé. Le programme ne détecte pas automatiquement
les informations personnelles et n'est pas un antivirus ni une sandbox.

## Utilisation avec une fenêtre

Prérequis : Python 3.11 ou plus, avec Tkinter. Sur Windows, utilisez l'installateur
Python officiel avec Tcl/Tk. Sur Debian/Ubuntu, installez aussi `python3-tk` et `python3-venv`.
Sur macOS, la distribution de python.org inclut Tkinter.

```sh
git clone https://github.com/Wissko/partage-clair.git
cd partage-clair
python -m venv .venv
```

Windows (PowerShell) :

```powershell
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\partage-clair-gui.exe
```

macOS / Linux :

```sh
.venv/bin/python -m pip install .
.venv/bin/partage-clair-gui
```

L'installation télécharge les dépendances. **Le traitement des documents fonctionne
ensuite sans réseau.** Aucun exécutable autonome n'est encore distribué.

1. Ouvrez un PDF ou une image.
2. Parcourez **toutes** les pages. Tracez un rectangle sur chaque information à masquer.
3. Exportez vers un nouveau fichier. L'original et les fichiers existants ne sont jamais remplacés.
4. Ouvrez la copie exportée et vérifiez chaque page avant de la transmettre.

![Rendu d'une copie exportée à partir d'un document entièrement fictif](docs/export-demo.png)

Pensez aussi aux codes QR, codes-barres, signatures manuscrites, photos et identifiants
visibles. Élargissez les masques pour englober entièrement les caractères.
Le nom du fichier peut lui-même être sensible : le nom proposé est `document-a-partager`.

## Ce que l'export fait

| Entrée | Sortie | Transformation |
| --- | --- | --- |
| PDF non chiffré | PDF en images | Les pages sont rendues, les masques noirs sont appliqués aux pixels, un nouveau PDF est créé |
| PNG, JPEG, WebP statique | PNG RGB | L'orientation EXIF est appliquée, la transparence est aplatie sur fond blanc, les pixels sont recopiés sans métadonnées |

Le PDF exporté ne reprend ni couche de texte, ni pièces jointes, ni formulaires,
ni commentaires éditables, ni JavaScript, ni métadonnées Info/XMP du document source.
Les annotations et champs visibles peuvent apparaître dans le rendu : **masquez aussi
leur contenu si nécessaire**. Un rectangle noir est inscrit dans les pixels, pas
simplement placé comme une annotation au-dessus du texte original.

Le PDF perd le texte sélectionnable, la recherche, les liens, les fonctionnalités
accessibles d'un PDF balisé et les signatures numériques. Le fichier peut grossir.
Conservez votre original signé séparément. Le contenu visible non masqué reste récupérable,
y compris par OCR. Le texte invisible ou les métadonnées ne sont pas copiés dans la sortie,
mais des filigranes visuels, des stéganographies ou des indices d'identification dans les
pixels ne sont pas détectés ni systématiquement supprimés.

## Ligne de commande

```sh
partage-clair document.pdf -o document-a-partager.pdf
partage-clair photo.jpg -o image-a-partager.png
partage-clair document.pdf -o document-masque.pdf --masks masques.json --dpi 150
```

Exemple de `masques.json` (données fictives) :

```json
[{"page": 1, "x0": 0.10, "y0": 0.20, "x1": 0.65, "y1": 0.30}]
```

Les pages commencent à 1. Les coordonnées vont de 0 à 1 dans la page **telle qu'affichée**,
avec l'origine en haut à gauche. Sans masque, les métadonnées et objets non rendus ne
sont pas recopiés, mais toutes les informations visibles restent lisibles.

## Limites explicites

- PDF : 50 pages maximum, 100 Mo à l'entrée, 24 millions de pixels par page rendue,
  80 millions de pixels pour l'export total. Résolution de 72 à 200 ppp (150 par défaut).
- Images : 100 Mo à l'entrée, 24 mégapixels maximum. Images animées et multipages refusées.
- PDF chiffrés, documents Office, HEIC et autres formats non pris en charge.
- L'interface peut attendre pendant un export volumineux ; aucun traitement en arrière-plan.
- Pas d'effacement sécurisé du disque, de la mémoire virtuelle ou des sauvegardes.
- Pas de conversion de couleur ICC : des couleurs peuvent différer de l'original.
- Ce logiciel n'isole pas les bibliothèques de décodage. N'ouvrez pas un fichier suspect.

Pour convertir des documents potentiellement malveillants dans un environnement isolé,
consultez [Dangerzone](https://github.com/freedomofpress/dangerzone). Pour un nettoyage de
métadonnées couvrant davantage de formats, consultez [mat2](https://0xacab.org/jvoisin/mat2).
Partage Clair privilégie ici un parcours simple en français et un masquage manuel explicite.

## Développement

```sh
python -m pip install -e ".[dev]"
python -m pytest -q
python -m ruff check .
python -m pip_audit -r requirements.txt
```

Les fixtures sont synthétiques. Les tests vérifient les pixels masqués, le contenu
PDF extractible, les objets embarqués, EXIF/XMP, la rotation, les refus d'entrée et
la conservation des originaux. La CI exécute ces contrôles sur Windows et Linux,
avec Python 3.11 et 3.13. Ils ne remplacent pas une revue de sécurité indépendante.

Architecture : [modèle de confidentialité](docs/PRIVACY.md).
Contribuer : [CONTRIBUTING.md](CONTRIBUTING.md). Licence : [MIT](LICENSE).
Le nom et les visuels de tiers ne sont pas utilisés dans les exemples.

