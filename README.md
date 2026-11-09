# Liste de films enrichie avec TMDB

Ce dépôt contient une liste de films (`liste_film.md`) et un script Python
(`tmdb_enrich.py`). Le script cherche chaque titre sur
[TMDB](https://www.themoviedb.org/) (The Movie Database) et récupère sa date
de sortie, son ou ses réalisateurs, son pays et son identifiant TMDB.

Le pays est le pays d'origine indiqué par TMDB (à défaut, les pays de
production), en français. Les films mis en cache avant l'ajout de cette
colonne reçoivent leur pays au lancement suivant de `./films.sh enrichir`,
sans refaire la recherche du titre.

## Prérequis

- **Python 3** : le script n'utilise que la bibliothèque standard, il n'y a
  rien à installer.
- **Une clé d'API TMDB** (gratuite) : crée un compte sur themoviedb.org, puis
  va dans *Paramètres → API*. Le script accepte au choix :
  - la « Clé d'API » (v3) ;
  - le « Jeton d'accès en lecture à l'API » (v4, il commence par `eyJ`).

## Configuration de la clé

La clé est rangée dans `config.ini`, à côté des scripts. Ce fichier est ignoré
par Git pour que la clé ne soit jamais commitée. Pour le créer :

```bash
./films.sh config
```

La clé est demandée sans être affichée, et le fichier n'est lisible que par
toi. On peut aussi copier le modèle et le remplir à la main :

```bash
cp config.ini.example config.ini
```

```ini
[tmdb]
api_key = ta_clé
```

Si la variable d'environnement `TMDB_API_KEY` est définie, elle est
prioritaire sur `config.ini`.

## Utilisation

```bash
python3 tmdb_enrich.py liste_film.md
```

Sans argument, le script lit `liste_film.md`. Pour tester sur quelques titres
avant de lancer toute la liste, mets-les dans un autre fichier :

```bash
python3 tmdb_enrich.py test_films.md
```

### Avec le lanceur `films.sh`

```bash
./films.sh config                  # enregistre la clé TMDB dans config.ini
./films.sh enrichir [liste.md]     # cherche les films sur TMDB
./films.sh interface [liste.md]    # ouvre l'interface graphique
./films.sh exporter [liste.md]     # régénère les résultats avec les validations
./films.sh test                    # essai rapide sur test_films.md
./films.sh vider-cache [liste.md]  # supprime le cache (avec confirmation)
./films.sh reinitialiser [--tout]  # repart de zéro (avec confirmation)
./films.sh aide
```

Sans argument, la liste utilisée est `liste_film.md`. Le lanceur vérifie
Python et PyQt6 avant de démarrer, et se place dans le dossier de la liste pour
que les résultats, le cache et `validations.json` y soient écrits.

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

Les tableaux donnent le titre trouvé sur TMDB, pas celui de la liste (le `#`
renvoie à la ligne de la liste). Pour un film introuvable ou pas encore
cherché, c'est le titre de la liste qui est repris, en *italique* dans le
Markdown.

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
- **Exporter… → Films affichés…** : enregistre les films affichés (statut et
  recherche appliqués, dans l'ordre du tri) en Markdown ou en CSV ;
- **Exporter… → Régénérer les fichiers de résultats** : voir ci-dessous ;
- **colonne « Validé »** : pour un film `À VÉRIFIER`, cocher la case valide
  le titre TMDB proposé et le film passe en `OK`. La ligne reste affichée
  jusqu'au prochain changement de filtre, ce qui permet de décocher en cas
  d'erreur. Au chargement suivant, un film validé s'affiche comme un `OK`
  normal, sans case (son infobulle indique « Validé manuellement ») ; pour
  revenir en arrière : clic droit sur sa ligne → **Annuler la validation**.

- **Quitter** (ou Ctrl+Q, ou la croix de la fenêtre) : une petite fenêtre
  demande de confirmer avant de fermer ;
- **Synchronisation** : cherche sur TMDB tous les titres encore `NON TRAITÉ`
  (après confirmation, avec le nombre de titres et une durée estimée). La
  recherche se fait en arrière-plan avec une barre de progression ; le tableau
  défile tout seul pour garder au milieu le film en cours, surligné en bleu ;
  le bouton devient « Arrêter la synchronisation » pour l'interrompre (ou
  touche **Échap**). Les résultats sont enregistrés dans le cache au fur et à
  mesure (rien n'est perdu en cas d'arrêt ou de fermeture), puis les fichiers
  de résultats sont régénérés. Un titre en erreur réseau reste `NON TRAITÉ` ;
  une clé refusée arrête tout. Revient au même que `./films.sh enrichir`, sans
  quitter l'interface ;
- **recherche immédiate** : un clic sur un statut `NON TRAITÉ` (souligné)
  cherche tout de suite ce titre sur TMDB, sans relancer tout le traitement.
  Le statut affiche `RECHERCHE…` le temps de la requête, puis le résultat ;
  il est enregistré dans le cache comme si `./films.sh enrichir` l'avait
  trouvé. Nécessite la clé TMDB (`./films.sh config`). Pratique juste après
  avoir corrigé un titre `INTROUVABLE` ;
- **correction des titres `INTROUVABLE` ou `NON TRAITÉ`** : double-clic
  (ou F2) sur la cellule « Titre (liste) » pour corriger le titre, puis
  Entrée. La correction est écrite directement dans la liste
  (`liste_film.md`) ; le film est (ou reste) `NON TRAITÉ` : un clic sur
  `NON TRAITÉ` le cherche tout de suite, sinon il sera recherché au prochain
  `./films.sh enrichir`. Si le nouveau titre est déjà dans le cache, son
  statut s'affiche tout de suite. Un titre en cours de recherche
  (`RECHERCHE…`) ne peut pas être modifié.

Les validations sont enregistrées dans `validations.json`, à côté de la liste
(titre de la liste → ID TMDB validé). `tmdb_enrich.py` les reprend : les films
validés apparaissent en `OK` dans tous les fichiers produits. Ce fichier est
indépendant du cache, donc supprimer `.tmdb_cache.json` ne fait pas perdre les
validations ; mais si une nouvelle recherche propose un autre film (autre ID),
la validation ne s'applique plus et le film redevient `À VÉRIFIER`.

L'interface lit la liste et le cache : elle fonctionne même avant la fin du
traitement, et se met à jour toute seule pendant que `tmdb_enrich.py` tourne.

## Régénérer les résultats avec les validations

`liste_film_tmdb.md`, le `.csv` et les listes par statut sont écrits par
`./films.sh enrichir`. Les validations faites ensuite dans l'interface n'y
apparaissent donc pas tout de suite. Pour les y intégrer sans relancer de
recherche TMDB (ni clé, ni réseau nécessaires) :

```bash
./films.sh exporter
```

ou, dans l'interface, **Exporter… → Régénérer les fichiers de résultats**.

Les fichiers sont réécrits à partir de la liste, du cache et de
`validations.json` : les films validés passent en `OK` (et quittent la liste
`À VÉRIFIER`), les corrections de titres sont prises en compte, et les titres
pas encore cherchés apparaissent en `NON TRAITÉ` dans le tableau complet.

## Films homonymes

Quand plusieurs films portent exactement le titre cherché (par exemple
« Les Maîtres de l'univers » de 1987 et de 2026), le film n'est pas classé
`OK` d'office :

- dans l'interface (recherche au clic ou **Synchronisation**), une petite
  fenêtre liste les films possibles avec leur année, leur réalisateur et leur
  résumé sur une ligne. **Choisir** (ou double-clic) retient le film et le
  passe en `OK` ; **Voir sur TMDB** ouvre sa fiche ; **Passer** le laisse
  `À VÉRIFIER`. La synchronisation attend la réponse avant de continuer.
  Au clavier :

  | Touche | Action |
  |---|---|
  | ↑ / ↓ | film précédent / suivant |
  | Entrée | choisir le film sélectionné |
  | → ou Échap | passer (le film reste `À VÉRIFIER`) |

- `./films.sh enrichir` ne peut pas poser la question : il retient le premier
  film en `À VÉRIFIER` et garde la liste des homonymes dans le cache.

Dans les deux cas, un film `À VÉRIFIER` avec des homonymes se choisit plus tard
dans l'interface : clic droit sur sa ligne → **Choisir parmi les
homonymes…**. Ajouter l'année dans la liste (`Carrie 2013`) évite la question.

## Cache et reprise

Les résultats sont enregistrés au fur et à mesure dans `.tmdb_cache.json`
(ignoré par Git). Si le script est interrompu (Ctrl+C, coupure réseau), il
suffit de le relancer : il reprend là où il s'était arrêté, et les titres déjà
traités sont marqués `(cache)`.

Un titre reste dans le cache même s'il était `INTROUVABLE`. Après avoir
corrigé une faute dans la liste, le nouveau titre sera bien recherché ; mais
pour relancer toutes les recherches (par exemple après une modification du
script), réinitialise :

```bash
./films.sh reinitialiser          # cache + fichiers de résultats
./films.sh reinitialiser --tout   # idem + validations.json
```

La commande liste les fichiers qui vont être supprimés et demande
confirmation. La liste (`liste_film.md`) et la clé (`config.ini`) ne sont
jamais supprimées ; les corrections de titres, écrites dans la liste, restent
donc en place (`git log -- liste_film.md` pour retrouver une version
antérieure). Le cache est commun à toutes les listes du dossier.

## Problèmes connus

- **Le script semble bloqué** : sur une connexion où l'IPv6 ne fonctionne pas,
  chaque requête pouvait attendre plusieurs minutes. Le script essaie
  désormais l'IPv4 en premier ; si le problème réapparaît, vérifie ta
  connexion à `api.themoviedb.org`.
- **`Clé TMDB refusée (401)`** : la clé de `config.ini` (ou de la variable
  `TMDB_API_KEY`) est incomplète ou invalide ; relance `./films.sh config`.
- **Titres homonymes** : voir « Films homonymes » ci-dessus. Ajouter l'année
  dans la liste (`Carrie 2013`) évite la question.
