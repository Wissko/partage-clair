# Mesure reproductible — 14 novembre 2026

Scénario : PDF synthétique de 20 pages A4, contenant une image de bruit gris déterministe
de 1000 × 1400 pixels par page. Export à 150 ppp, sans masque. Le document ne contient
aucune donnée personnelle. Ce scénario représente un cas de pages raster lourdes ; il
ne prédit pas les performances de tous les documents.

Machine de développement Windows 11 x64, Python 3.13.2. Mesure d'un seul passage par
version, après installation, avec observation toutes les 20 ms du RSS du processus et
de ses enfants. Le lanceur Python d'environnement virtuel Windows crée un sous-processus,
qui doit être inclus dans la mesure. Les temps varient avec la machine et les caches.

| Version | Durée | Pic RSS observé | Fichier de sortie |
| --- | ---: | ---: | ---: |
| 0.1.0, commit b0f2e17 | 16,379 s | 280,1 Mio | 60 373 556 octets |
| Moteur 0.2.0, écriture progressive et canal gris | 1,897 s | 144,9 Mio | 41 284 772 octets |

Sur ce cas : environ 8,6 fois plus rapide, 48 % de mémoire en moins et 32 % de taille en
moins. La compression reste sans perte. Les tests comparent aussi directement les
pixels reconstruits au canevas masqué sur des pages grises et colorées.

Pour reproduire, installez `python -m pip install -e ".[benchmark]"` puis lancez
`python scripts/benchmark.py nom-unique`. Le script génère sa fixture dans `tmp/benchmark/`,
exécute le CLI dans un processus séparé et enregistre durée, RSS et taille dans un JSON.
Pour comparer des versions, exécutez le script avec la même fixture sur chaque checkout.
Il refuse de remplacer une sortie existante. Le résultat de la mesure 0.2 a été relevé
pendant le développement du moteur, avant la finalisation de l'interface et du packaging.
