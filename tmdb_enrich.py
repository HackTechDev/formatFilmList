#!/usr/bin/env python3
"""
Enrichit une liste de films (un titre par ligne) avec les données TMDB :
date de sortie, réalisateur(s), ID TMDB.

Usage :
    export TMDB_API_KEY="ta_clé_v3"        # ou le "API Read Access Token" (v4)
    python3 tmdb_enrich.py liste_film.md

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

KEY = os.environ.get("TMDB_API_KEY", "").strip()
if not KEY:
    sys.exit("Définis TMDB_API_KEY (clé v3 ou jeton v4) avant de lancer le script.")
USE_BEARER = KEY.startswith("eyJ")  # jeton v4 = JWT

# Suffixes d'édition à retirer pour la recherche
EDITION_RE = re.compile(
    r"\b(ultimate\s*(cut|[ée]dition)|special\s*edition|version\s*int[ée]grale|"
    r"director'?s\s*cut|3\s*d)\b",
    re.I,
)
YEAR_RE = re.compile(r"[\s:]((?:19|20)\d\d)\s*$")


def api_get(path, **params):
    if not USE_BEARER:
        params["api_key"] = KEY
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    if USE_BEARER:
        req.add_header("Authorization", f"Bearer {KEY}")
    last_err = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                time.sleep(SLEEP)
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                sys.exit("Clé TMDB refusée (401).")
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


def search(raw):
    best = None
    for q, year in query_variants(raw):
        params = {"query": q, "language": LANG, "include_adult": "true"}
        if year:
            params["primary_release_year"] = year
        res = api_get("/search/movie", **params).get("results", [])
        if not res:
            continue
        nq = norm(q)
        for r in res[:10]:
            if nq in (norm(r.get("title")), norm(r.get("original_title"))):
                return r, "OK"
        if best is None:
            best = res[0]
    return (best, "À VÉRIFIER") if best else (None, "INTROUVABLE")


def directors(movie_id):
    crew = api_get(f"/movie/{movie_id}/credits", language=LANG).get("crew", [])
    names = [c["name"] for c in crew if c.get("job") == "Director"]
    return ", ".join(dict.fromkeys(names))


def found_label(e):
    """Titre TMDB retenu, avec l'année et le titre original s'il diffère."""
    if not e.get("id"):
        return "—"
    label = e.get("title") or e.get("original_title", "")
    if e.get("date"):
        label += f" ({e['date'][:4]})"
    if e.get("original_title") and norm(e["original_title"]) != norm(e.get("title")):
        label += f" [{e['original_title']}]"
    return label


def save_cache(cache):
    """Écriture atomique : un plantage pendant l'écriture ne corrompt pas le cache."""
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    os.replace(tmp, CACHE_FILE)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "liste_film.md"
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
                movie, status = search(raw)
                entry = {"status": status}
                if movie:
                    entry.update(
                        id=movie["id"],
                        title=movie.get("title", ""),
                        original_title=movie.get("original_title", ""),
                        date=movie.get("release_date", ""),
                        director=directors(movie["id"]),
                    )
                cache[raw] = entry
                new += 1
                if new % 25 == 0:
                    save_cache(cache)
                source = ""
            else:
                source = " (cache)"
            e = cache[raw]
            status = tmdb_export.effective_status(raw, e, validations)
            if tmdb_export.is_validated(raw, e, validations):
                source += " (validé)"
            print(f"[{i}/{len(titles)}] {status:12} {raw} → {found_label(e)}{source}",
                  file=sys.stderr)
            counts[status] = counts.get(status, 0) + 1
            rows.append([
                i, raw, e.get("title", ""), e.get("original_title", ""),
                e.get("date", ""), e.get("director", ""), e.get("id", ""), status,
            ])
    finally:  # sauvegarde même en cas de plantage ou de Ctrl+C
        save_cache(cache)

    base = tmdb_export.default_name(src)
    written = tmdb_export.write_all(base, rows)
    print(f"\nTerminé — {counts}", file=sys.stderr)
    for path in written:
        print(f"  {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
