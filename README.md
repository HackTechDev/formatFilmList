# Liste de films enrichie avec TMDB

Ce dépôt contient une liste de films (`liste_film.md`) et un script Python
(`tmdb_enrich.py`). Le script cherche chaque titre sur
[TMDB](https://www.themoviedb.org/) (The Movie Database) et récupère sa date
de sortie, son ou ses réalisateurs et son identifiant TMDB.

## Prérequis

- **Python 3** : le script n'utilise que la bibliothèque standard, il n'y a
  rien à installer.
- **Une clé d'API TMDB** (gratuite) : crée un compte sur themoviedb.org, puis
  va dans *Paramètres → API*. Le script accepte au choix :
  - la « Clé d'API » (v3) ;
  - le « Jeton d'accès en lecture à l'API » (v4, il commence par `eyJ`).

## Utilisation

```bash
export TMDB_API_KEY="ta_clé"
python3 tmdb_enrich.py liste_film.md
```

Sans argument, le script lit `liste_film.md`. Pour tester sur quelques titres
avant de lancer toute la liste, mets-les dans un autre fichier :

```bash
python3 tmdb_enrich.py test_films.md
```

### Format de la liste

Un titre par ligne, les lignes vides sont ignorées. Le script reconnaît :

| Exemple | Interprétation |
|---|---|
| `Dune 1984` | « Dune » sorti en 1984 (si le titre complet ne donne rien) |
| `Jack l'éventreur:1944` | « Jack l'éventreur » sorti en 1944 |
| `New York 1997` | cherché d'abord tel quel : l'année peut faire partie du titre |
| `Blade Runner Director's cut` | la mention d'édition est retirée en dernier recours |
| `The nun / la nonne` | chaque partie est essayée séparément |

## Résultats

Le script crée deux fichiers à côté de la liste, en gardant l'ordre d'origine :

- `liste_film_tmdb.md` : un tableau Markdown, avec un lien vers chaque fiche
  TMDB et une section **Doublons probables** ;
- `liste_film_tmdb.csv` : le même contenu en CSV (séparateur `;`), lisible
  directement dans Excel avec les accents ;
- un tableau par statut, en Markdown et en CSV :
  `liste_film_tmdb_OK`, `liste_film_tmdb_A_VERIFIER` et
  `liste_film_tmdb_INTROUVABLE` (`.md` et `.csv`). Ils sont réécrits à chaque
  exécution, même vides, pour ne jamais garder une ancienne liste.

Chaque film reçoit un statut :

| Statut | Signification |
|---|---|
| `OK` | le titre TMDB (français ou original) correspond à celui de la liste |
| `À VÉRIFIER` | correspondance approximative : le premier résultat TMDB a été retenu |
| `INTROUVABLE` | aucun résultat, souvent une faute de frappe dans la liste |

Pendant l'exécution, chaque ligne affiche le film retenu :

```
[1/1446] OK           New York 1997 → New-York 1997 (1981) [Escape from New York]
[8/1446] INTROUVABLE  Le hyene intrépide → —
```

Pense à relire à la main les lignes `À VÉRIFIER` et `INTROUVABLE`.

## Interface graphique

`film_viewer.py` affiche les films traités dans une fenêtre (nécessite PyQt6) :

```bash
python3 film_viewer.py                # liste_film.md
python3 film_viewer.py test_films.md  # une autre liste
```

- **Filtre par statut** (`OK`, `À VÉRIFIER`, `INTROUVABLE`, `NON TRAITÉ`),
  avec le nombre de films pour chacun ;
- **recherche** dans les titres et les réalisateurs ;
- **tri** en cliquant sur l'en-tête d'une colonne ;
- **double-clic** sur une ligne : ouvre la fiche TMDB dans le navigateur ;
- **Exporter…** : enregistre les films affichés (statut et recherche
  appliqués, dans l'ordre du tri) en Markdown ou en CSV.

L'interface lit la liste et le cache : elle fonctionne même avant la fin du
traitement, et se met à jour toute seule pendant que `tmdb_enrich.py` tourne.

## Cache et reprise

Les résultats sont enregistrés au fur et à mesure dans `.tmdb_cache.json`
(ignoré par Git). Si le script est interrompu (Ctrl+C, coupure réseau), il
suffit de le relancer : il reprend là où il s'était arrêté, et les titres déjà
traités sont marqués `(cache)`.

Un titre reste dans le cache même s'il était `INTROUVABLE`. Après avoir
corrigé une faute dans la liste, le nouveau titre sera bien recherché ; mais
pour relancer toutes les recherches (par exemple après une modification du
script), supprime le cache :

```bash
rm .tmdb_cache.json
```

## Problèmes connus

- **Le script semble bloqué** : sur une connexion où l'IPv6 ne fonctionne pas,
  chaque requête pouvait attendre plusieurs minutes. Le script essaie
  désormais l'IPv4 en premier ; si le problème réapparaît, vérifie ta
  connexion à `api.themoviedb.org`.
- **`Clé TMDB refusée (401)`** : la variable `TMDB_API_KEY` est absente,
  incomplète ou invalide.
- **Titres homonymes** : pour un titre comme « Carrie », le script retient le
  film qui correspond exactement, pas forcément la version voulue. Ajoute
  l'année dans la liste (`Carrie 2013`) pour lever l'ambiguïté.
