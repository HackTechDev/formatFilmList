#!/usr/bin/env bash
# Lanceur pour l'enrichissement TMDB de la liste de films.
# Lancer « ./films.sh aide » pour la liste des commandes.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_LIST="$DIR/liste_film.md"
TEST_LIST="$DIR/test_films.md"
CACHE=".tmdb_cache.json"   # même nom que dans tmdb_enrich.py

if [[ -t 1 ]]; then
    ROUGE=$'\e[31m'; VERT=$'\e[32m'; JAUNE=$'\e[33m'; GRAS=$'\e[1m'; RAZ=$'\e[0m'
else
    ROUGE=""; VERT=""; JAUNE=""; GRAS=""; RAZ=""
fi

erreur() { echo "${ROUGE}Erreur :${RAZ} $*" >&2; exit 1; }
info()   { echo "${VERT}→${RAZ} $*" >&2; }

aide() {
    cat <<EOF
${GRAS}Usage :${RAZ} ./films.sh <commande> [liste.md]

${GRAS}Commandes :${RAZ}
  config                  enregistre ta clé TMDB dans config.ini
  enrichir [liste.md]     cherche les films sur TMDB (par défaut : liste_film.md)
  interface [liste.md]    ouvre l'interface graphique
  test                    essai rapide sur une dizaine de titres (test_films.md)
  vider-cache [liste.md]  supprime le cache TMDB pour relancer toutes les
                          recherches (les validations sont conservées)
  aide                    affiche cette aide

${GRAS}Clé TMDB :${RAZ} fichier config.ini (créé par « ./films.sh config »,
  ignoré par Git). La variable TMDB_API_KEY, si elle est définie, est prioritaire.

Les résultats, le cache et validations.json sont écrits à côté de la liste.
EOF
}

# Chemin absolu de la liste (argument ou liste par défaut), qui doit exister.
liste() {
    local f="${1:-$DEFAULT_LIST}"
    [[ -f "$f" ]] || erreur "liste introuvable : $f"
    echo "$(cd "$(dirname "$f")" && pwd)/$(basename "$f")"
}

verifier_python() {
    command -v python3 >/dev/null || erreur "python3 n'est pas installé."
}

CONFIG="$DIR/config.ini"

# Crée ou remplace config.ini avec la clé saisie (sans l'afficher).
config() {
    if [[ -f "$CONFIG" ]]; then
        read -r -p "$CONFIG existe déjà. Remplacer la clé ? [o/N] " rep
        [[ "$rep" =~ ^[oOyY]$ ]] || { info "Annulé."; return; }
    fi
    echo "Clé TMDB : « Clé d'API » (v3) ou « Jeton d'accès en lecture » (v4),"
    echo "sur themoviedb.org → Paramètres → API."
    local cle
    read -r -s -p "Colle ta clé (elle ne s'affiche pas) : " cle
    echo
    cle="${cle//[[:space:]]/}"
    [[ -n "$cle" ]] || erreur "clé vide, rien n'a été enregistré."
    ( umask 077
      : > "$CONFIG"
      chmod 600 "$CONFIG"   # aussi quand le fichier existait déjà
      printf '# Configuration de tmdb_enrich.py (ne pas commiter)\n[tmdb]\napi_key = %s\n' "$cle" > "$CONFIG" )
    info "Clé enregistrée dans $CONFIG (lisible par toi seul)."
}

# Les scripts Python écrivent le cache dans le dossier courant : on se place
# dans le dossier de la liste pour que tout reste au même endroit.
enrichir() {
    verifier_python
    local f; f="$(liste "${1:-}")"
    info "Enrichissement de $(basename "$f")…"
    cd "$(dirname "$f")"
    python3 "$DIR/tmdb_enrich.py" "$(basename "$f")"
}

interface() {
    verifier_python
    python3 -c "import PyQt6.QtWidgets" 2>/dev/null \
        || erreur "PyQt6 n'est pas installé (paquet python3-pyqt6 ou « pip install PyQt6 »)."
    local f; f="$(liste "${1:-}")"
    cd "$(dirname "$f")"
    python3 "$DIR/film_viewer.py" "$(basename "$f")"
}

test_rapide() {
    if [[ ! -f "$TEST_LIST" ]]; then
        info "Création de $(basename "$TEST_LIST")"
        cat > "$TEST_LIST" <<'EOF'
Dune 1984
New York 1997
Death race 2000
Jack l'éventreur:1944
Godzilla 1954
Rashomon
In the mood for love
Le hyene intrépide
Carrie
Carrie
Titre qui n'existe pas xyz
EOF
    fi
    enrichir "$TEST_LIST"
}

vider_cache() {
    local f; f="$(liste "${1:-}")"
    local c; c="$(dirname "$f")/$CACHE"
    if [[ ! -f "$c" ]]; then
        info "Pas de cache à supprimer ($c)."
        return
    fi
    local n
    n="$(grep -o '"status"' "$c" | wc -l)"
    echo "${JAUNE}Le cache contient $n film(s). Toutes les recherches TMDB seront refaites.${RAZ}"
    read -r -p "Supprimer $c ? [o/N] " rep
    if [[ "$rep" =~ ^[oOyY]$ ]]; then
        rm -f -- "$c"
        info "Cache supprimé (validations.json conservé)."
    else
        info "Annulé."
    fi
}

commande="${1:-aide}"
shift || true
case "$commande" in
    config)                config ;;
    enrichir)              enrichir "$@" ;;
    interface)             interface "$@" ;;
    test)                  test_rapide ;;
    vider-cache)           vider_cache "$@" ;;
    aide|-h|--help|help)   aide ;;
    *) echo "${ROUGE}Commande inconnue :${RAZ} $commande" >&2; echo >&2; aide >&2; exit 1 ;;
esac
