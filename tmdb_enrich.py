#!/usr/bin/env python3
"""
Enrichit une liste de films (un titre par ligne) avec les données TMDB :
date de sortie, réalisateur(s), ID TMDB.

Usage :
    python3 tmdb_enrich.py liste_film.md

Clé TMDB (clé v3 ou "API Read Access Token" v4), lue dans cet ordre :
    1. la variable d'environnement TMDB_API_KEY ;
    2. le fichier config.ini à côté de ce script :
           [tmdb]
           api_key = ta_clé
       (modèle : config.ini.example ; créé aussi par « ./films.sh config »)

Sorties :
    liste_film_tmdb.md   tableau Markdown (ordre d'origine conservé)
    liste_film_tmdb.csv  même contenu en CSV (séparateur ;)
    liste_film_tmdb_OK.md / _A_VERIFIER.md / _INTROUVABLE.md (+ .csv)
                         un tableau par statut
    .tmdb_cache.json     cache : relancer le script reprend là où il s'était arrêté

Colonne "Statut" :
    OK         titre TMDB identique (titre FR ou original) au titre de la liste,
               ou titre « À VÉRIFIER » validé dans film_viewer.py (validations.json)
    À VÉRIFIER correspondance approximative (premier résultat TMDB retenu)
    INTROUVABLE aucun résultat

Aucune dépendance externe (stdlib uniquement).
"""
import configparser
import http.client
import json
import os
import re
import socket
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import urllib.error

import tmdb_export

API = "https://api.themoviedb.org/3"
LANG = "fr-FR"
CACHE_FILE = ".tmdb_cache.json"
SLEEP = 0.05  # TMDB tolère ~40-50 req/s

# IPv4 d'abord : sur une connexion où l'IPv6 ne passe pas, Python essaie
# chaque adresse IPv6 jusqu'au délai d'attente avant de basculer en IPv4
# (plusieurs minutes par requête). L'IPv6 reste utilisée en secours.
_getaddrinfo = socket.getaddrinfo


def _getaddrinfo_ipv4_first(*args, **kwargs):
    return sorted(_getaddrinfo(*args, **kwargs), key=lambda a: a[0] != socket.AF_INET)


socket.getaddrinfo = _getaddrinfo_ipv4_first

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini")


class TmdbError(Exception):
    """Erreur à montrer telle quelle (clé absente ou refusée…)."""


def load_key():
    """Clé TMDB : variable TMDB_API_KEY, sinon [tmdb] api_key dans config.ini."""
    key = os.environ.get("TMDB_API_KEY", "").strip()
    if key:
        return key
    if os.path.exists(CONFIG_FILE):
        config = configparser.ConfigParser(interpolation=None)
        try:
            config.read(CONFIG_FILE, encoding="utf-8")
        except configparser.Error as e:
            raise TmdbError(f"{CONFIG_FILE} illisible : {e}")
        key = config.get("tmdb", "api_key", fallback="").strip().strip("\"'")
        if key:
            return key
    raise TmdbError("Clé TMDB absente. Lance « ./films.sh config », ou copie\n"
             f"config.ini.example en {CONFIG_FILE} et renseigne api_key.")


_KEY = None


def get_key():
    """Clé chargée à la première requête (l'import du module n'en a pas besoin)."""
    global _KEY
    if _KEY is None:
        _KEY = load_key()
    return _KEY

# Suffixes d'édition à retirer pour la recherche
EDITION_RE = re.compile(
    r"\b(ultimate\s*(cut|[ée]dition)|special\s*edition|version\s*int[ée]grale|"
    r"director'?s\s*cut|3\s*d)\b",
    re.I,
)
YEAR_RE = re.compile(r"[\s:]((?:19|20)\d\d)\s*$")


def api_get(path, **params):
    key = get_key()
    use_bearer = key.startswith("eyJ")  # jeton v4 = JWT
    if not use_bearer:
        params["api_key"] = key
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    if use_bearer:
        req.add_header("Authorization", f"Bearer {key}")
    last_err = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                time.sleep(SLEEP)
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise TmdbError("Clé TMDB refusée (401).")
            if e.code != 429 and e.code < 500:  # 429 = rate limit, 5xx = serveur
                raise
            last_err = e
        except (urllib.error.URLError, TimeoutError, ConnectionError,
                http.client.HTTPException) as e:
            last_err = e
        time.sleep(2 * (attempt + 1))
    # Pas d'URL complète dans le message : elle contiendrait la clé v3
    raise RuntimeError(f"Échec répété sur {path} : {last_err!r}")


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s.lower())


def clean(title):
    t = title.replace("__", " ").strip()
    t = re.sub(r"\s+", " ", t)
    return t


def query_variants(raw):
    """Génère des couples (requête, année) du plus précis au plus large."""
    t = clean(raw)
    # Titre complet d'abord : l'année peut faire partie du titre
    # ("New York 1997", "Death race 2000", "Los Angeles 2013").
    out = [(t, None)]
    m = YEAR_RE.search(t)
    if m:  # "Dune 1984", "Jack l'éventreur:1944" -> titre + année de sortie
        base = t[: m.start()].strip(" :")
        if base:
            out.append((base, m.group(1)))
    no_ed = re.sub(r"\s+(the|le|la|les)$", "", EDITION_RE.sub("", t).strip(" :-"), flags=re.I)
    if no_ed and no_ed != t:
        out.append((no_ed, None))
    for sep in (" / ", "/", " : ", ":"):  # "The nun / la nonne", "Guinea pig : ..."
        if sep in t:
            for part in reversed(t.split(sep)):  # sous-titre d'abord
                part = part.strip()
                if len(part) > 2 and not part.isdigit():
                    out.append((part, None))
            break
    seen, uniq = set(), []
    for q in out:
        if q not in seen:
            seen.add(q)
            uniq.append(q)
    return uniq


def candidate(r):
    """Résumé d'un résultat de recherche TMDB, gardé dans le cache."""
    return {"id": r["id"], "title": r.get("title", ""),
            "original_title": r.get("original_title", ""),
            "date": r.get("release_date", ""),
            "overview": (r.get("overview") or "")[:400]}


def search(raw):
    """(film retenu, statut, homonymes).

    homonymes : liste de candidate() quand plusieurs films portent exactement
    ce titre (ex. un film et son remake) ; le film retenu est alors le premier
    et le statut « À VÉRIFIER », pour que l'utilisateur choisisse.
    """
    best = None
    for q, year in query_variants(raw):
        params = {"query": q, "language": LANG, "include_adult": "true"}
        if year:
            params["primary_release_year"] = year
        res = api_get("/search/movie", **params).get("results", [])
        if not res:
            continue
        nq = norm(q)
        exact = [r for r in res[:10]
                 if nq in (norm(r.get("title")), norm(r.get("original_title")))]
        if len(exact) > 1:
            return exact[0], "À VÉRIFIER", [candidate(r) for r in exact]
        if exact:
            return exact[0], "OK", []
        if best is None:
            best = res[0]
    return (best, "À VÉRIFIER", []) if best else (None, "INTROUVABLE", [])


_COUNTRY_NAMES = None


def country_names():
    """{code ISO: nom du pays en français}, demandé une fois à TMDB."""
    global _COUNTRY_NAMES
    if _COUNTRY_NAMES is None:
        try:
            data = api_get("/configuration/countries", language=LANG)
            _COUNTRY_NAMES = {c["iso_3166_1"]: c.get("native_name") or c.get("english_name")
                              or c["iso_3166_1"] for c in data}
        except (urllib.error.HTTPError, RuntimeError):
            _COUNTRY_NAMES = {}  # à défaut, les codes (JP, HK…) sont affichés
    return _COUNTRY_NAMES


def details(movie_id):
    """(réalisateur(s), pays) d'un film, en une seule requête."""
    d = api_get(f"/movie/{movie_id}", language=LANG, append_to_response="credits")
    crew = (d.get("credits") or {}).get("crew", [])
    directors = [c["name"] for c in crew if c.get("job") == "Director"]
    # Pays d'origine ; à défaut, pays de production.
    codes = d.get("origin_country") or [c["iso_3166_1"] for c in d.get("production_countries", [])]
    names = country_names()
    countries = [names.get(c, c) for c in codes]
    return ", ".join(dict.fromkeys(directors)), ", ".join(dict.fromkeys(countries))


def complete(entry):
    """Ajoute le pays à une entrée de cache qui date d'avant cette colonne."""
    if not entry.get("id") or "country" in entry:
        return False
    director, country = details(entry["id"])
    entry["country"] = country
    if not entry.get("director"):
        entry["director"] = director
    return True


def movie_entry(c):
    """Champs de cache d'un film (c au format candidate()), avec réalisateur et pays.

    Si c contient déjà le réalisateur et le pays (homonymes), aucune requête.
    """
    if "director" in c and "country" in c:
        director, country = c["director"], c["country"]
    else:
        director, country = details(c["id"])
    return {"id": c["id"], "title": c.get("title", ""),
            "original_title": c.get("original_title", ""), "date": c.get("date", ""),
            "director": director, "country": country}


def lookup(raw):
    """Cherche un titre sur TMDB et retourne son entrée de cache.

    S'il y a des homonymes, l'entrée garde la liste dans « candidates » (le
    premier film est retenu en attendant le choix, voir choose()).
    """
    movie, status, candidates = search(raw)
    entry = {"status": status}
    if candidates:
        # Réalisateur (et pays) de chaque homonyme, pour aider à choisir.
        for c in candidates:
            c["director"], c["country"] = details(c["id"])
        entry.update(movie_entry(candidates[0]))
        entry["candidates"] = candidates
    elif movie:
        entry.update(movie_entry(candidate(movie)))
    return entry


def choose(entry, movie_id):
    """Entrée de cache après le choix d'un des homonymes : statut OK."""
    if movie_id == entry.get("id"):  # le film déjà retenu : rien à recharger
        chosen = {k: v for k, v in entry.items() if k != "candidates"}
    else:
        c = next(c for c in entry["candidates"] if c["id"] == movie_id)
        chosen = movie_entry(c)
    chosen["status"] = "OK"
    return chosen


def found_label(e):
    """Titre TMDB retenu, avec l'année et le titre original s'il diffère."""
    if not e.get("id"):
        return "—"
    label = e.get("title") or e.get("original_title", "")
    if e.get("date"):
        label += f" ({e['date'][:4]})"
    if e.get("original_title") and norm(e["original_title"]) != norm(e.get("title")):
        label += f" [{e['original_title']}]"
    if e.get("candidates"):
        label += f" — {len(e['candidates'])} films portent ce titre, à choisir dans l'interface"
    return label


def save_cache(cache):
    """Écriture atomique : un plantage pendant l'écriture ne corrompt pas le cache."""
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    os.replace(tmp, CACHE_FILE)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "liste_film.md"
    get_key()  # clé absente : arrêt immédiat, avant de lire quoi que ce soit
    with open(src, encoding="utf-8") as f:
        titles = [l.strip() for l in f if l.strip()]
    cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, encoding="utf-8") as f:
            cache = json.load(f)

    validations = tmdb_export.load_validations(src)  # validés dans film_viewer.py
    rows, counts = [], {}
    new = 0
    try:
        for i, raw in enumerate(titles, 1):
            if raw not in cache:
                cache[raw] = lookup(raw)
                source = ""
            elif complete(cache[raw]):  # cache d'avant la colonne « Pays »
                source = " (pays ajouté)"
            else:
                source = " (cache)"
            if source != " (cache)":
                new += 1
                if new % 25 == 0:
                    save_cache(cache)
            e = cache[raw]
            status = tmdb_export.effective_status(raw, e, validations)
            if tmdb_export.is_validated(raw, e, validations):
                source += " (validé)"
            print(f"[{i}/{len(titles)}] {status:12} {raw} → {found_label(e)}{source}",
                  file=sys.stderr)
            counts[status] = counts.get(status, 0) + 1
            rows.append([
                i, raw, e.get("title", ""), e.get("original_title", ""),
                e.get("date", ""), e.get("director", ""), e.get("country", ""),
                e.get("id", ""), status,
            ])
    finally:  # sauvegarde même en cas de plantage ou de Ctrl+C
        save_cache(cache)

    base = tmdb_export.default_name(src)
    written = tmdb_export.write_all(base, rows)
    print(f"\nTerminé — {counts}", file=sys.stderr)
    for path in written:
        print(f"  {path}", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except TmdbError as e:
        sys.exit(str(e))
