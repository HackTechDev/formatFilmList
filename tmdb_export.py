"""
Écriture des tableaux de films (Markdown et CSV), commune à tmdb_enrich.py
et film_viewer.py.

En ligne de commande, régénère liste_film_tmdb.md / .csv et les listes par
statut à partir de la liste, du cache et de validations.json, sans
interroger TMDB :
    python3 tmdb_export.py liste_film.md

Une ligne de film est une liste :
    [#, titre (liste), titre TMDB, titre original, date, réalisateur, pays, ID TMDB, statut]
"""
import csv
import json
import os
import sys
import unicodedata

HEADER = ["#", "Titre (liste)", "Titre TMDB", "Titre original",
          "Date de sortie", "Réalisateur", "Pays", "ID TMDB", "Statut"]
I_NUM, I_RAW, I_TITLE = 0, 1, 2
I_ID, I_STATUS = HEADER.index("ID TMDB"), HEADER.index("Statut")

# Colonnes des fichiers écrits : le titre de la liste n'y figure plus, le
# titre TMDB le remplace ; à défaut (film introuvable ou pas encore cherché),
# c'est le titre de la liste qui est repris.
OUT_HEADER = ["#", "Titre", "Titre original", "Date de sortie", "Réalisateur",
              "Pays", "ID TMDB", "Statut"]
O_TITLE, O_ID = OUT_HEADER.index("Titre"), OUT_HEADER.index("ID TMDB")


def out_row(r):
    """Ligne interne (HEADER) -> ligne écrite (OUT_HEADER)."""
    return [r[I_NUM], r[I_TITLE] or r[I_RAW]] + list(r[I_TITLE + 1:])
STATUSES = ["OK", "À VÉRIFIER", "INTROUVABLE"]
TMDB_URL = "https://www.themoviedb.org/movie/{}"

# Films « À VÉRIFIER » validés à la main dans film_viewer.py :
# {titre de la liste: ID TMDB validé}. Fichier à côté de la liste.
VALIDATIONS_FILE = "validations.json"
CACHE_FILE = ".tmdb_cache.json"  # même nom que dans tmdb_enrich.py
NOT_DONE = "NON TRAITÉ"


def validations_path(list_path):
    return os.path.join(os.path.dirname(os.path.abspath(list_path)), VALIDATIONS_FILE)


def load_validations(list_path):
    path = validations_path(list_path)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_validations(list_path, validations):
    path = validations_path(list_path)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(validations.items())), f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def is_validated(raw, entry, validations):
    """Vrai si ce film « À VÉRIFIER » a été validé avec le même ID TMDB."""
    return (entry.get("status") == "À VÉRIFIER" and bool(entry.get("id"))
            and validations.get(raw) == entry.get("id"))


def effective_status(raw, entry, validations):
    """Statut à afficher : un film validé à la main passe en « OK »."""
    return "OK" if is_validated(raw, entry, validations) else entry.get("status")


def status_slug(status):
    """« À VÉRIFIER » -> « A_VERIFIER », utilisable dans un nom de fichier."""
    s = unicodedata.normalize("NFKD", status)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return "_".join(s.upper().split())


def counts_line(rows):
    counts = {}
    for r in rows:
        counts[r[I_STATUS]] = counts.get(r[I_STATUS], 0) + 1
    return " · ".join(f"{k} : {v}" for k, v in sorted(counts.items()))


def write_csv(path, rows):
    # utf-8-sig : le BOM permet à Excel d'afficher correctement les accents
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(OUT_HEADER + ["Lien"])
        for r in rows:
            w.writerow(out_row(r) + [TMDB_URL.format(r[I_ID]) if r[I_ID] else ""])


def _md(s):
    return str(s).replace("|", "\\|")


def duplicates(rows):
    """{clé: [numéros de ligne]} pour les films présents plusieurs fois."""
    occ = {}
    for r in rows:
        occ.setdefault(r[I_ID] or r[I_RAW], []).append(r)
    return {k: v for k, v in occ.items() if len(v) > 1}


def write_md(path, rows, title, show_duplicates=False):
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n")
        if not rows:
            f.write("Aucun film.\n")
            return
        f.write(f"{len(rows)} film(s) — {counts_line(rows)}\n\n")
        f.write("| " + " | ".join(OUT_HEADER) + " |\n")
        f.write("|" + "---|" * len(OUT_HEADER) + "\n")
        for r in rows:
            o = [_md(c) for c in out_row(r)]
            if r[I_ID]:
                o[O_ID] = f"[{r[I_ID]}]({TMDB_URL.format(r[I_ID])})"
            elif o[O_TITLE]:
                o[O_TITLE] = f"*{o[O_TITLE]}*"  # pas de titre TMDB : titre de la liste
            f.write("| " + " | ".join(o) + " |\n")
        dups = duplicates(rows) if show_duplicates else {}
        if dups:
            f.write("\n## Doublons probables\n\n")
            for k, group in dups.items():
                first = group[0]
                name = first[I_TITLE] or first[I_RAW]
                ref = f"ID {k}" if first[I_ID] else "non trouvé sur TMDB"
                nums = ", ".join(str(r[I_NUM]) for r in group)
                f.write(f"- {name} ({ref}) : lignes {nums}\n")


def write_all(base, rows):
    """Tableau complet + un tableau par statut. Retourne les fichiers écrits."""
    written = []
    write_csv(base + ".csv", rows)
    write_md(base + ".md", rows, "Liste de films (données TMDB)", show_duplicates=True)
    written += [base + ".md", base + ".csv"]
    for status in STATUSES:
        sub = [r for r in rows if r[I_STATUS] == status]
        b = f"{base}_{status_slug(status)}"
        write_csv(b + ".csv", sub)
        write_md(b + ".md", sub, f"Liste de films — {status}")
        written += [b + ".md", b + ".csv"]
    return written


def default_name(list_path, status=None):
    """liste_film.md -> liste_film_tmdb[_STATUT]"""
    base = os.path.splitext(list_path)[0] + "_tmdb"
    return f"{base}_{status_slug(status)}" if status else base


def load_cache(list_path):
    path = os.path.join(os.path.dirname(os.path.abspath(list_path)), CACHE_FILE)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_rows(list_path, cache, validations):
    """Une ligne par titre de la liste ; les films validés passent en OK."""
    with open(list_path, encoding="utf-8") as f:
        titles = [l.strip() for l in f if l.strip()]
    rows = []
    for i, raw in enumerate(titles, 1):
        e = cache.get(raw)
        status = effective_status(raw, e, validations) if e else NOT_DONE
        e = e or {}
        rows.append([i, raw, e.get("title", ""), e.get("original_title", ""),
                     e.get("date", ""), e.get("director", ""), e.get("country", ""),
                     e.get("id", ""), status])
    return rows


def regenerate(list_path):
    """Réécrit les fichiers de résultats depuis le cache et validations.json.

    Retourne (fichiers écrits, {statut: nombre}, nombre de films validés).
    Lève ValueError si aucun film n'a encore été traité.
    """
    cache = load_cache(list_path)
    if not cache:
        raise ValueError("aucun film traité : lance d'abord « ./films.sh enrichir ».")
    validations = load_validations(list_path)
    rows = build_rows(list_path, cache, validations)
    counts = {}
    for r in rows:
        counts[r[I_STATUS]] = counts.get(r[I_STATUS], 0) + 1
    n_validated = sum(is_validated(r[I_RAW], cache.get(r[I_RAW], {}), validations) for r in rows)
    return write_all(default_name(list_path), rows), counts, n_validated


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "liste_film.md"
    try:
        written, counts, n_validated = regenerate(src)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        sys.exit(f"Erreur : {e}")
    print(f"Fichiers régénérés, {n_validated} film(s) validé(s) en OK — {counts}")
    for path in written:
        print(f"  {path}")
