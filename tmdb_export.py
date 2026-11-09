"""
Écriture des tableaux de films (Markdown et CSV), commune à tmdb_enrich.py
et film_viewer.py.

Une ligne de film est une liste :
    [#, titre (liste), titre TMDB, titre original, date, réalisateur, pays, ID TMDB, statut]
"""
import csv
import json
import os
import unicodedata

HEADER = ["#", "Titre (liste)", "Titre TMDB", "Titre original",
          "Date de sortie", "Réalisateur", "Pays", "ID TMDB", "Statut"]
I_NUM, I_RAW, I_TITLE = 0, 1, 2
I_ID, I_STATUS = HEADER.index("ID TMDB"), HEADER.index("Statut")
STATUSES = ["OK", "À VÉRIFIER", "INTROUVABLE"]
TMDB_URL = "https://www.themoviedb.org/movie/{}"

# Films « À VÉRIFIER » validés à la main dans film_viewer.py :
# {titre de la liste: ID TMDB validé}. Fichier à côté de la liste.
VALIDATIONS_FILE = "validations.json"


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
        w.writerow(HEADER + ["Lien"])
        for r in rows:
            w.writerow(list(r) + [TMDB_URL.format(r[I_ID]) if r[I_ID] else ""])


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
        f.write("| " + " | ".join(HEADER) + " |\n")
        f.write("|" + "---|" * len(HEADER) + "\n")
        for r in rows:
            r = list(r)
            if r[I_ID]:
                r[I_ID] = f"[{r[I_ID]}]({TMDB_URL.format(r[I_ID])})"
            f.write("| " + " | ".join(_md(c) for c in r) + " |\n")
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
