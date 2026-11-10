#!/usr/bin/env python3
"""
Visualiseur des films traités par tmdb_enrich.py (PyQt6).

Usage :
    python3 film_viewer.py                 # liste_film.md + .tmdb_cache.json
    python3 film_viewer.py autre_liste.md

Lit la liste de films et le cache TMDB : les films pas encore traités
apparaissent avec le statut « NON TRAITÉ ». L'affichage se met à jour
automatiquement quand le cache change (pendant un traitement en cours).

Double-clic sur une ligne : ouvre la fiche TMDB du film dans le navigateur.
Bouton « Exporter… » :
  - « Films affichés… » : enregistre les films affichés (filtre et recherche
    appliqués) en Markdown ou en CSV ;
  - « Régénérer les fichiers de résultats » : réécrit liste_film_tmdb.md, le
    .csv et les listes par statut en y intégrant validations.json, sans
    interroger TMDB.

Colonne « Validé » : cocher un film « À VÉRIFIER » valide le titre TMDB
proposé ; il passe en « OK ». Au chargement suivant, un film validé
s'affiche comme un « OK » normal, sans case ; clic droit sur sa ligne →
« Annuler la validation » pour revenir en arrière. Les validations sont enregistrées dans
validations.json (à côté de la liste) et reprises par tmdb_enrich.py.

Titre d'un film : double-clic (ou F2) sur « Titre (liste) » pour le corriger,
quel que soit son statut (pas pendant sa recherche). La correction est écrite
dans la liste. Un film « OK » ou « À VÉRIFIER » garde son film TMDB et passe
(ou reste) « À VÉRIFIER » ; les autres repassent « NON TRAITÉ » : le nouveau
titre sera cherché au
prochain lancement de tmdb_enrich.py, ou tout de suite par un clic sur
« NON TRAITÉ ».

Films « NON TRAITÉ » : un clic sur « NON TRAITÉ » cherche tout de suite ce
titre sur TMDB (en arrière-plan) et enregistre le résultat dans le cache.

Films « À VÉRIFIER » : un clic sur « À VÉRIFIER » ouvre la fenêtre de choix
du film (homonymes déjà connus, sinon films possibles cherchés sur TMDB).
Bouton « Corriger… » → « Introuvables… » ou « À vérifier… » : tous les titres
de ce statut dans une zone de texte, un par ligne, à corriger puis enregistrer
d'un coup ; les titres corrigés sont ensuite cherchés sur TMDB.
Films « INTROUVABLE » : un clic sur « INTROUVABLE » ouvre la même fenêtre et
y cherche le titre ; le texte de recherche se modifie (puis Entrée).

Homonymes : quand plusieurs films portent exactement le titre cherché (ex.
« Les Maîtres de l'univers » de 1987 et de 2026), une petite fenêtre propose
de choisir le bon pendant la recherche (la synchronisation attend le choix).
« Passer » laisse le film « À VÉRIFIER » ; clic droit → « Choisir parmi les
homonymes… » pour choisir plus tard.

Bouton « Synchronisation » : cherche sur TMDB tous les titres encore « NON
TRAITÉ », en arrière-plan avec une barre de progression (bouton « Arrêter »
ou touche Échap pour interrompre), puis régénère les fichiers de résultats.
"""
import json
import os
import sys
import threading

from PyQt6.QtCore import (QEvent, QFileSystemWatcher, QSortFilterProxyModel, Qt,
                          QThread, QTimer, QUrl, pyqtSignal)
from PyQt6.QtGui import (QColor, QDesktopServices, QFontDatabase, QFontMetrics, QKeySequence, QShortcut,
                         QStandardItem, QStandardItemModel)
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                             QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                             QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
                             QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
                             QTableView, QVBoxLayout, QWidget)

import tmdb_enrich
import tmdb_export

CACHE_FILE = ".tmdb_cache.json"  # même nom que dans tmdb_enrich.py
NOT_DONE = "NON TRAITÉ"
STATUSES = ["OK", "À VÉRIFIER", "INTROUVABLE", NOT_DONE]
EDITABLE = ("OK", "À VÉRIFIER", "INTROUVABLE", NOT_DONE)  # statuts dont le titre se corrige
STATUS_COLORS = {
    "OK": QColor("#2e9e44"),
    "À VÉRIFIER": QColor("#d98a00"),
    "INTROUVABLE": QColor("#d43c3c"),
    NOT_DONE: QColor("#888888"),
    "RECHERCHE…": QColor("#2f6fd6"),
}
SEARCHING = "RECHERCHE…"
SYNC_ROW_COLOR = QColor("#cfe2ff")  # fond bleu de la ligne en cours de synchronisation
COLUMNS = ["#", "Statut", "Validé", "Titre (liste)", "Titre TMDB", "Titre original",
           "Date de sortie", "Réalisateur", "Pays", "ID TMDB"]
COL_STATUS = COLUMNS.index("Statut")
COL_CHECK = COLUMNS.index("Validé")
COL_RAW = COLUMNS.index("Titre (liste)")
COL_ID = COLUMNS.index("ID TMDB")
COL_TITLES = [COLUMNS.index(c) for c in ("Titre (liste)", "Titre TMDB", "Titre original")]
COL_SEARCH = COL_TITLES + [COLUMNS.index("Réalisateur"), COLUMNS.index("Pays")]
# Statut utilisé par le filtre : figé jusqu'au prochain changement de filtre,
# pour qu'une ligne cochée ne disparaisse pas sous le curseur.
FILTER_ROLE = Qt.ItemDataRole.UserRole + 1
RAW_ROLE = Qt.ItemDataRole.UserRole + 2  # titre tel qu'il est dans le fichier


def film_row(i, raw, e, validations):
    """Ligne suivant COLUMNS pour le titre n° i de la liste et son entrée de cache.

    La colonne « Validé » vaut None si le film ne peut pas être validé
    (statut autre que « À VÉRIFIER »), sinon True/False.
    """
    checkable = e.get("status") == "À VÉRIFIER" and bool(e.get("id"))
    validated = tmdb_export.is_validated(raw, e, validations) if checkable else None
    status = tmdb_export.effective_status(raw, e, validations) if e else NOT_DONE
    return [i, status, validated, raw, e.get("title", ""), e.get("original_title", ""),
            e.get("date", ""), e.get("director", ""), e.get("country", ""), e.get("id", "")]


def rename_in_list(list_path, num, old, new):
    """Remplace le titre n° num (lignes non vides comptées) de la liste."""
    with open(list_path, encoding="utf-8", newline="") as f:  # garde \r\n tel quel
        lines = f.read().splitlines(keepends=True)
    count = 0
    for idx, line in enumerate(lines):
        if not line.strip():
            continue
        count += 1
        if count == num:
            if line.strip() != old:
                raise ValueError(f"la ligne {num} de la liste a changé "
                                 f"(« {line.strip()} » au lieu de « {old} »)")
            end = line[len(line.rstrip("\r\n")):]  # retour à la ligne d'origine
            lines[idx] = new + end
            break
    else:
        raise ValueError(f"la liste n'a plus de ligne {num}")
    tmp = list_path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write("".join(lines))
    os.replace(tmp, list_path)


def load_films(list_path):
    """Une ligne (voir film_row) par titre de la liste, complétée par le cache."""
    with open(list_path, encoding="utf-8") as f:
        titles = [l.strip() for l in f if l.strip()]
    cache = {}
    cache_path = os.path.join(os.path.dirname(os.path.abspath(list_path)), CACHE_FILE)
    if os.path.exists(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass  # cache illisible : tout apparaît comme non traité
    validations = tmdb_export.load_validations(list_path)
    films = [film_row(i, raw, cache.get(raw, {}), validations)
             for i, raw in enumerate(titles, 1)]
    return films, cache_path, validations, cache


def store_in_cache(cache_path, raw, entry):
    store_entries(cache_path, {raw: entry})


def store_entries(cache_path, entries):
    """Ajoute des entrées au cache sur disque (relu juste avant, écrit d'un coup)."""
    cache = {}
    if os.path.exists(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    cache.update(entries)
    tmp = cache_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    os.replace(tmp, cache_path)


_search_threads = set()  # recherches encore actives (fenêtre fermée entre-temps)


class CandidatesThread(QThread):
    """Cherche sur TMDB les films possibles pour un texte, hors de l'interface."""
    done = pyqtSignal(object)   # liste de films (format tmdb_enrich.candidate)
    failed = pyqtSignal(str)

    def __init__(self, query):
        super().__init__()
        self.query = query

    def run(self):
        try:
            self.done.emit(tmdb_enrich.add_details(tmdb_enrich.search_candidates(self.query)))
        except Exception as e:  # réseau, clé…
            self.failed.emit(f"{type(e).__name__} : {e}")


class ChooseFilmDialog(QDialog):
    """Petite fenêtre pour choisir le bon film, avec une recherche TMDB libre.

    candidates : films proposés d'emblée (homonymes, films possibles). Vide
    (film INTROUVABLE) : la recherche du titre est lancée à l'ouverture.
    Après exec() : choice = ID choisi (ou None), candidates = films affichés.
    """

    def __init__(self, raw, candidates, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choisir le film")
        self.setMinimumWidth(560)
        self.choice = None
        self.candidates = list(candidates)
        self.thread = None
        layout = QVBoxLayout(self)
        intro = (f"Films possibles pour « {raw} » (le premier est celui retenu)."
                 if candidates else f"Aucun film retenu pour « {raw} » : cherche-le sur TMDB.")
        layout.addWidget(QLabel(
            intro + "\nChoisis le bon : ↑/↓ puis Entrée (ou double-clic) ; → pour passer.\n"
            "Autre recherche : modifie le texte ci-dessous, puis Entrée."))
        search_row = QHBoxLayout()
        self.query = QLineEdit(raw)
        self.query.setClearButtonEnabled(True)
        self.query.setPlaceholderText("Titre à chercher sur TMDB (avec l'année si besoin)")
        self.query.installEventFilter(self)  # Entrée : rechercher ; ↓ : aller à la liste
        search_btn = QPushButton("Rechercher")
        search_btn.setAutoDefault(False)
        search_btn.clicked.connect(self.run_search)
        search_row.addWidget(self.query, 1)
        search_row.addWidget(search_btn)
        layout.addLayout(search_row)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _: self.pick())
        layout.addWidget(self.list)
        buttons = QDialogButtonBox()
        tmdb_btn = buttons.addButton("Voir sur TMDB", QDialogButtonBox.ButtonRole.HelpRole)
        self.choose_btn = buttons.addButton("Choisir", QDialogButtonBox.ButtonRole.AcceptRole)
        skip_btn = buttons.addButton("Passer (→)",
                                     QDialogButtonBox.ButtonRole.RejectRole)
        tmdb_btn.clicked.connect(self.open_tmdb)
        self.choose_btn.clicked.connect(self.pick)
        skip_btn.clicked.connect(self.reject)  # Échap fait de même
        skip_btn.setToolTip("Ne rien changer pour l'instant (touche → ou Échap)")
        self.choose_btn.setToolTip("Choisir le film sélectionné (Entrée)")
        layout.addWidget(buttons)
        # Entrée = « Choisir ». Le bouton par défaut doit être désigné une fois
        # rattaché à la fenêtre, sinon Qt prend le premier (« Voir sur TMDB »).
        tmdb_btn.setAutoDefault(False)
        skip_btn.setAutoDefault(False)
        self.choose_btn.setDefault(True)
        # Clavier : ↑/↓ parcourent la liste, Entrée choisit, → passe (dans le
        # champ de recherche, → déplace le curseur comme d'habitude).
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, activated=self.reject)
        if self.candidates:
            self.fill_list(self.candidates)
            self.list.setFocus()
        else:
            self.query.setFocus()
            self.query.selectAll()
            self.run_search()
        self.adjustSize()  # la fenêtre prend la hauteur de sa liste

    def fill_list(self, candidates, message=""):
        """Affiche les films ; sans film, une ligne grisée avec le message."""
        self.list.clear()
        fm = QFontMetrics(self.list.font())
        for c in candidates:
            # Titre (année) — réalisateur, puis le résumé sur une seule ligne.
            year = c.get("date", "")[:4] or "année inconnue"
            text = f"{c.get('title') or c.get('original_title')} ({year})"
            if c.get("director"):
                text += f" — {c['director']}"
            overview = " ".join((c.get("overview") or "").split())
            if overview:
                text += "\n    " + fm.elidedText(overview, Qt.TextElideMode.ElideRight, 500)
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, c["id"])
            item.setToolTip(overview or "Pas de résumé sur TMDB")
            self.list.addItem(item)
        if not candidates:
            item = QListWidgetItem(message)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(item)
        else:
            self.list.setCurrentRow(0)
        self.choose_btn.setEnabled(bool(candidates))
        self.fit_list_height()

    def fit_list_height(self, max_height=420):
        """Hauteur de la liste = hauteur de ses films (défilement au-delà)."""
        rows = sum(self.list.sizeHintForRow(i) for i in range(self.list.count()))
        height = rows + 2 * self.list.frameWidth() + 4
        self.list.setFixedHeight(min(height, max_height))
        self.adjustSize()

    def eventFilter(self, obj, event):
        if obj is self.query and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.run_search()  # et pas « Choisir »
                return True
            if event.key() == Qt.Key.Key_Down and self.choose_btn.isEnabled():
                self.list.setFocus()
                return True
        return super().eventFilter(obj, event)

    def run_search(self):
        query = " ".join(self.query.text().split())
        if not query or self.thread:
            return
        self.fill_list([], f"Recherche de « {query} » sur TMDB…")
        thread = CandidatesThread(query)
        _search_threads.add(thread)  # gardé en vie même si la fenêtre se ferme
        thread.finished.connect(lambda: _search_threads.discard(thread))
        thread.done.connect(self.on_results)
        thread.failed.connect(self.on_failed)
        self.thread = thread
        thread.start()

    def on_results(self, candidates):
        self.thread = None
        if candidates:
            self.candidates = candidates
            self.fill_list(candidates)
            self.list.setFocus()
        else:
            self.fill_list([], "Aucun film trouvé — modifie la recherche puis Entrée")
            self.query.setFocus()

    def on_failed(self, message):
        self.thread = None
        self.fill_list([], f"Recherche impossible : {message}")
        self.query.setFocus()

    def current_id(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def open_tmdb(self):
        if self.current_id():
            QDesktopServices.openUrl(QUrl(tmdb_export.TMDB_URL.format(self.current_id())))

    def pick(self):
        if self.current_id() is None:
            return
        self.choice = self.current_id()
        self.accept()


class FixTitlesDialog(QDialog):
    """Corrige d'un coup les titres des films d'un statut, un par ligne.

    À gauche, en lecture seule : n° de ligne et titre actuel. À droite, les
    titres à modifier, dans le même ordre. Une ligne vidée garde son titre.
    Après exec() : changes = [(ligne du tableau, ancien, nouveau)].
    """

    def __init__(self, rows, status="INTROUVABLE", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Corriger les titres « INTROUVABLE »" if status == "INTROUVABLE"
                            else "Corriger les titres « À VÉRIFIER »")
        self.resize(900, 560)
        self.rows = rows  # [(ligne du tableau, n° dans la liste, titre)]
        self.changes = []
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"{len(rows)} film(s) {status}. Corrige les titres dans la colonne de "
            "droite, une ligne par film, sans ajouter ni supprimer de ligne.\n"
            "Une ligne laissée vide garde son titre. Les corrections sont écrites dans "
            "la liste à l'enregistrement."))
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        panes = QHBoxLayout()
        self.before = QPlainTextEdit()
        self.before.setReadOnly(True)
        self.before.setPlainText("\n".join(f"{num:>5}  {raw}" for _, num, raw in rows))
        self.after = QPlainTextEdit()
        self.after.setPlainText("\n".join(raw for _, _, raw in rows))
        for edit in (self.before, self.after):
            edit.setFont(mono)
            edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        # Défilement synchronisé : chaque ligne reste en face de son titre d'origine.
        self.before.verticalScrollBar().valueChanged.connect(
            self.after.verticalScrollBar().setValue)
        self.after.verticalScrollBar().valueChanged.connect(
            self.before.verticalScrollBar().setValue)
        self.after.textChanged.connect(self.update_info)
        left, right = QVBoxLayout(), QVBoxLayout()
        left.addWidget(QLabel("Ligne et titre actuel"))
        left.addWidget(self.before)
        right.addWidget(QLabel("Titre corrigé"))
        right.addWidget(self.after)
        panes.addLayout(left, 2)
        panes.addLayout(right, 3)
        layout.addLayout(panes)
        self.info = QLabel()
        layout.addWidget(self.info)
        self.search_after = QCheckBox("Chercher les titres corrigés sur TMDB après l'enregistrement")
        self.search_after.setChecked(True)
        layout.addWidget(self.search_after)
        buttons = QDialogButtonBox()
        self.save_btn = buttons.addButton("Enregistrer", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_btn = buttons.addButton("Annuler", QDialogButtonBox.ButtonRole.RejectRole)
        self.save_btn.clicked.connect(self.save)
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(buttons)
        self.save_btn.setAutoDefault(False)  # Entrée = nouvelle ligne dans le texte
        cancel_btn.setAutoDefault(False)
        self.after.setFocus()
        self.update_info()

    def new_titles(self):
        lines = self.after.toPlainText().split("\n")
        while len(lines) > len(self.rows) and not lines[-1].strip():
            lines.pop()  # lignes vides ajoutées en fin de texte : ignorées
        return lines

    def pending_changes(self):
        lines = self.new_titles()
        if len(lines) != len(self.rows):
            return None
        out = []
        for (r, _, old), line in zip(self.rows, lines):
            new = " ".join(line.split())
            if new and new != old:
                out.append((r, old, new))
        return out

    def update_info(self):
        changes = self.pending_changes()
        if changes is None:
            n = len(self.new_titles())
            self.info.setText(f"<b style='color:#d43c3c'>{n} ligne(s) au lieu de "
                              f"{len(self.rows)} : une ligne a été ajoutée ou supprimée.</b>")
            self.save_btn.setEnabled(False)
        else:
            self.info.setText(f"{len(changes)} titre(s) modifié(s).")
            self.save_btn.setEnabled(bool(changes))

    def save(self):
        changes = self.pending_changes()
        if not changes:
            return
        self.changes = changes
        self.accept()


class TmdbThread(QThread):
    """Fil de recherche TMDB qui peut demander de choisir parmi des homonymes."""
    ambiguous = pyqtSignal(str, object)   # titre, entrée avec « candidates »

    def resolve(self, raw, entry):
        """Homonymes : attend le choix fait dans l'interface (answer())."""
        if not entry.get("candidates"):
            return entry
        if self.isInterruptionRequested():
            return entry
        self._choice, self._candidates, self._answered = None, None, threading.Event()
        self.ambiguous.emit(raw, entry)
        # Attente du choix ; on vérifie régulièrement si l'interface ferme,
        # pour ne jamais rester bloqué sur une question sans réponse.
        while not self._answered.wait(0.1):
            if self.isInterruptionRequested():
                return entry
        if self._choice is None:  # « Passer » : reste À VÉRIFIER
            return entry
        return tmdb_enrich.choose(dict(entry, candidates=self._candidates or entry["candidates"]),
                                  self._choice)

    def answer(self, choice, candidates=None):
        """Choix fait dans la fenêtre, avec les films qu'elle affichait."""
        self._choice, self._candidates = choice, candidates
        if getattr(self, "_answered", None):
            self._answered.set()


class LookupThread(TmdbThread):
    """Recherche TMDB d'un titre, hors du fil de l'interface."""
    found = pyqtSignal(str, object)   # titre, entrée de cache
    failed = pyqtSignal(str, str)     # titre, message d'erreur

    def __init__(self, raw, parent, job=None):
        super().__init__(parent)
        self.raw = raw
        self.job = job or (lambda: tmdb_enrich.lookup(raw))

    def run(self):
        try:
            self.found.emit(self.raw, self.resolve(self.raw, self.job()))
        except tmdb_enrich.TmdbError as e:
            self.failed.emit(self.raw, str(e))
        except Exception as e:  # réseau, réponse inattendue…
            self.failed.emit(self.raw, f"{type(e).__name__} : {e}")


class SyncThread(TmdbThread):
    """Recherche TMDB de plusieurs titres à la suite, interruptible."""
    progress = pyqtSignal(int, int, str)   # titres faits, total, titre en cours
    found = pyqtSignal(str, object)        # titre, entrée de cache
    title_failed = pyqtSignal(str, str)    # titre, erreur (on passe au suivant)
    fatal = pyqtSignal(str)                # erreur bloquante (clé…) : arrêt

    def __init__(self, titles, parent, keep=None):
        super().__init__(parent)
        self.titles = titles
        # {titre: entrée} : si la recherche ne trouve rien, on garde cette
        # entrée (film déjà trouvé d'un titre À VÉRIFIER corrigé).
        self.keep = keep or {}

    def run(self):
        total = len(self.titles)
        for i, raw in enumerate(self.titles):
            if self.isInterruptionRequested():
                return
            self.progress.emit(i, total, raw)
            try:
                entry = tmdb_enrich.lookup(raw)
                if entry.get("status") == "INTROUVABLE" and raw in self.keep:
                    entry = self.keep[raw]
                entry = self.resolve(raw, entry)
            except tmdb_enrich.TmdbError as e:
                self.fatal.emit(str(e))
                return
            except Exception as e:  # réseau… : ce titre reste tel quel
                self.title_failed.emit(raw, f"{type(e).__name__} : {e}")
                continue
            self.found.emit(raw, entry)
        self.progress.emit(total, total, "")


class FilmFilter(QSortFilterProxyModel):
    """Filtre par statut et par texte (titres et réalisateur)."""

    def __init__(self):
        super().__init__()
        self.status = None  # None = tous
        self.text = ""

    def set_status(self, status):
        self.status = status
        self.invalidateFilter()

    def set_text(self, text):
        self.text = text.strip().casefold()
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        m = self.sourceModel()
        if self.status and m.item(row, COL_STATUS).data(FILTER_ROLE) != self.status:
            return False
        if self.text:
            fields = (m.item(row, c).text() for c in COL_SEARCH)
            return any(self.text in f.casefold() for f in fields)
        return True


class FilmViewer(QMainWindow):
    def __init__(self, list_path):
        super().__init__()
        self.list_path = list_path
        self.resize(1400, 750)

        self.model = QStandardItemModel(0, len(COLUMNS))
        self.model.setHorizontalHeaderLabels(COLUMNS)
        self.proxy = FilmFilter()
        self.proxy.setSourceModel(self.model)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        # Titre modifiable sauf pendant sa recherche (voir fill_row et EDITABLE).
        self.table.setEditTriggers(QTableView.EditTrigger.DoubleClicked
                                   | QTableView.EditTrigger.EditKeyPressed)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        self.table.doubleClicked.connect(self.open_tmdb)
        self.table.clicked.connect(self.on_cell_clicked)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.on_context_menu)

        self.status_combo = QComboBox()
        self.status_combo.currentIndexChanged.connect(self.on_status_filter)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher un titre, un réalisateur ou un pays…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.proxy.set_text)
        open_btn = QPushButton("Ouvrir une liste…")
        open_btn.clicked.connect(self.choose_file)
        quit_btn = QPushButton("Quitter")
        quit_btn.setToolTip("Fermer l'interface (Ctrl+Q)")
        quit_btn.clicked.connect(self.close)  # confirmation dans closeEvent
        QShortcut(QKeySequence.StandardKey.Quit, self, activated=self.close)
        reload_btn = QPushButton("Recharger")
        reload_btn.clicked.connect(self.reload)
        self.sync_btn = QPushButton("Synchronisation")
        self.sync_btn.setToolTip("Chercher sur TMDB tous les titres pas encore traités")
        self.sync_btn.clicked.connect(self.toggle_sync)
        self.fix_btn = QPushButton("Corriger…")
        self.fix_btn.setToolTip("Corriger d'un coup les titres des films d'un statut")
        fix_menu = QMenu(self.fix_btn)
        fix_menu.addAction("Introuvables…", lambda: self.fix_titles("INTROUVABLE"))
        fix_menu.addAction("À vérifier…", lambda: self.fix_titles("À VÉRIFIER"))
        self.fix_btn.setMenu(fix_menu)
        export_btn = QPushButton("Exporter…")
        export_menu = QMenu(export_btn)
        export_menu.addAction("Films affichés…", self.export).setToolTip(
            "Enregistrer les films affichés en Markdown ou en CSV")
        export_menu.addAction("Régénérer les fichiers de résultats", self.regenerate_files)
        export_menu.setToolTipsVisible(True)
        export_btn.setMenu(export_menu)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Statut :"))
        bar.addWidget(self.status_combo)
        bar.addWidget(self.search, 1)
        bar.addWidget(reload_btn)
        bar.addWidget(self.sync_btn)
        bar.addWidget(self.fix_btn)
        bar.addWidget(export_btn)
        bar.addWidget(open_btn)
        bar.addWidget(quit_btn)
        layout = QVBoxLayout()
        layout.addLayout(bar)
        layout.addWidget(self.table)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        self.loading = False
        self.validations = {}
        self.cache = {}
        self.cache_path = ""
        self.lookups = {}  # titre -> LookupThread en cours
        self.sync = None          # SyncThread en cours
        self.sync_current = None  # titre en cours de synchronisation
        self.sync_highlight = None  # titre dont la ligne est surlignée en bleu
        self.pending = {}         # résultats pas encore écrits dans le cache
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(250)
        self.progress.setFormat("%v / %m")  # « 13 / 1411 » plutôt que « 0 % »
        self.progress.hide()
        self.sync_label = QLabel()
        self.statusBar().addPermanentWidget(self.sync_label)
        self.statusBar().addPermanentWidget(self.progress)
        # Échap arrête la synchronisation ; actif seulement pendant celle-ci,
        # pour ne pas gêner Échap ailleurs (annuler une correction de titre…).
        self.esc_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self,
                                      activated=self.stop_sync)
        self.esc_shortcut.setEnabled(False)
        self.stamp = None
        self.model.itemChanged.connect(self.on_item_changed)

        self.proxy.rowsInserted.connect(self.update_count)
        self.proxy.rowsRemoved.connect(self.update_count)
        self.proxy.modelReset.connect(self.update_count)
        self.proxy.layoutChanged.connect(self.update_count)

        # Rechargement auto quand la liste ou le cache change. Le cache est
        # remplacé (os.replace) : on regarde aussi le dossier, et on attend
        # un peu pour regrouper les écritures rapprochées.
        self.watcher = QFileSystemWatcher()
        self.watcher.fileChanged.connect(self.schedule_reload)
        self.watcher.directoryChanged.connect(self.schedule_reload)
        self.reload_timer = QTimer(singleShot=True, interval=500)
        self.reload_timer.timeout.connect(self.reload)

        self.reload()
        self.table.resizeColumnsToContents()
        for col in COL_TITLES:  # titres : largeur raisonnable
            self.table.setColumnWidth(col, min(self.table.columnWidth(col), 300))
        # Statut : assez large pour tous les statuts, même absents au départ.
        font = self.table.font()
        font.setBold(True)
        fm = QFontMetrics(font)
        widest = max(fm.horizontalAdvance(s) for s in STATUSES + [SEARCHING])
        self.table.setColumnWidth(COL_STATUS, max(self.table.columnWidth(COL_STATUS), widest + 20))

    def files_stamp(self):
        """Dates de modification de la liste et du cache."""
        cache = os.path.join(os.path.dirname(os.path.abspath(self.list_path)), CACHE_FILE)
        return tuple(os.path.getmtime(p) if os.path.exists(p) else None
                     for p in (self.list_path, cache))

    def schedule_reload(self, *_):
        # Le dossier est surveillé : ignorer les écritures qui ne touchent ni
        # la liste ni le cache (validations.json, exports…).
        if self.files_stamp() != self.stamp:
            self.reload_timer.start()

    def watch(self, cache_path):
        old = self.watcher.files() + self.watcher.directories()
        if old:
            self.watcher.removePaths(old)
        paths = [os.path.abspath(self.list_path), os.path.dirname(cache_path)]
        if os.path.exists(cache_path):
            paths.append(cache_path)
        self.watcher.addPaths(paths)

    def reload(self):
        self.flush_pending()  # résultats de synchronisation pas encore écrits
        try:
            films, cache_path, self.validations, self.cache = load_films(self.list_path)
        except OSError as e:
            QMessageBox.critical(self, "Erreur", f"Impossible de lire {self.list_path} :\n{e}")
            return
        self.cache_path = cache_path
        self.watch(cache_path)
        self.setWindowTitle(f"Films TMDB — {os.path.basename(self.list_path)}")

        self.stamp = self.files_stamp()
        scroll = self.table.verticalScrollBar().value()

        self.loading = True
        self.model.removeRows(0, self.model.rowCount())
        for film in films:
            row = []
            for _ in COLUMNS:
                item = QStandardItem()
                item.setEditable(False)
                row.append(item)
            self.model.appendRow(row)
            r = self.model.rowCount() - 1
            self.fill_row(r, film)
            self.model.item(r, COL_STATUS).setData(film[COL_STATUS], FILTER_ROLE)
        self.loading = False

        self.fill_status_combo()
        self.update_count()
        self.table.verticalScrollBar().setValue(scroll)
        if getattr(self, "sync_highlight", None):  # rechargé pendant une synchronisation
            self.highlight_rows(self.sync_highlight, True)

    def fill_row(self, r, film):
        """Remplit la ligne r du modèle avec les valeurs de film (voir film_row)."""
        items = [self.model.item(r, c) for c in range(len(COLUMNS))]
        for col, value in enumerate(film):
            item = items[col]
            if col == COL_CHECK:
                # Case seulement pour un film à valider. Un film déjà validé
                # s'affiche comme un OK normal (annulation : clic droit). Une
                # case cochée pendant la session reste visible jusqu'au
                # rechargement, car on_validation ne repasse pas par ici.
                to_validate = value is False
                item.setCheckable(to_validate)
                if to_validate:
                    item.setCheckState(Qt.CheckState.Unchecked)
                else:
                    item.setData(None, Qt.ItemDataRole.CheckStateRole)
                item.setToolTip("Cocher pour valider le titre TMDB proposé"
                                if to_validate else "")
            elif col == 0 or (col == COL_ID and value != ""):
                item.setData(int(value), Qt.ItemDataRole.DisplayRole)  # tri numérique
            else:
                item.setData(str(value), Qt.ItemDataRole.DisplayRole)
        self.set_status(items[COL_STATUS], film[COL_STATUS], film[COL_CHECK])
        items[COL_ID].setToolTip("Double-clic : ouvrir la fiche TMDB" if film[COL_ID] else "")
        raw_item = items[COL_RAW]
        raw_item.setData(film[COL_RAW], RAW_ROLE)
        editable = (film[COL_STATUS] in EDITABLE
                    and not self.is_searching(film[COL_RAW]))
        raw_item.setEditable(editable)
        raw_item.setToolTip("Double-clic (ou F2) pour corriger le titre" if editable else "")
        homonyms = self.cache.get(film[COL_RAW], {}).get("candidates")
        if homonyms and film[COL_STATUS] == "À VÉRIFIER":
            items[COL_STATUS].setToolTip(f"{len(homonyms)} films possibles — "
                                         "cliquer pour choisir le bon")
        if film[COL_STATUS] == NOT_DONE and self.is_searching(film[COL_RAW]):
            self.set_status(items[COL_STATUS], SEARCHING)

    def is_searching(self, raw):
        """Vrai si ce titre est en cours de recherche sur TMDB."""
        return raw in self.lookups or raw == self.sync_current

    def set_title_editable(self, raw, editable):
        """Pas de correction de titre pendant la recherche de ce titre."""
        self.loading = True
        for r in self.rows_of(raw):
            ok = editable and self.model.item(r, COL_STATUS).text() in EDITABLE
            item = self.model.item(r, COL_RAW)
            item.setEditable(ok)
            item.setToolTip("Double-clic (ou F2) pour corriger le titre" if ok else "")
        self.loading = False

    @staticmethod
    def set_status(item, status, validated=None):
        item.setText(status)
        item.setForeground(STATUS_COLORS.get(status, QColor("#888888")))
        font = item.font()
        font.setBold(True)
        font.setUnderline(status in (NOT_DONE, "À VÉRIFIER", "INTROUVABLE"))  # cliquable
        item.setFont(font)
        if status == NOT_DONE:
            item.setToolTip("Cliquer pour chercher ce film sur TMDB")
        elif status == "À VÉRIFIER":
            item.setToolTip("Cliquer pour choisir le bon film")
        elif status == "INTROUVABLE":
            item.setToolTip("Cliquer pour chercher le film sur TMDB avec un autre texte")
        else:
            item.setToolTip("Validé manuellement — clic droit pour annuler la validation"
                            if validated else "")

    def rows_of(self, raw):
        return [r for r in range(self.model.rowCount())
                if self.model.item(r, COL_RAW).data(RAW_ROLE) == raw]

    def on_cell_clicked(self, index):
        """Clic sur le statut : « NON TRAITÉ » cherche le titre sur TMDB,
        « À VÉRIFIER » et « INTROUVABLE » ouvrent la fenêtre de choix du film."""
        if index.column() != COL_STATUS:
            return
        r = self.proxy.mapToSource(index).row()
        status = self.model.item(r, COL_STATUS).text()
        raw = self.model.item(r, COL_RAW).data(RAW_ROLE)
        if raw in self.lookups or self.is_searching(raw):
            return
        if status == NOT_DONE:
            self.start_lookup(raw)
            self.statusBar().showMessage(f"Recherche de « {raw} » sur TMDB…")
        elif status == "À VÉRIFIER":
            self.choose_film(raw)
        elif status == "INTROUVABLE":
            self.choose_homonym(raw)  # sans film proposé : la fenêtre cherche le titre

    def choose_film(self, raw):
        """Fenêtre de choix pour un film À VÉRIFIER.

        Homonymes déjà dans le cache : la fenêtre s'ouvre tout de suite.
        Sinon, les films possibles sont cherchés sur TMDB en arrière-plan,
        puis proposés (et gardés dans le cache pour la fois suivante).
        """
        entry = self.cache.get(raw, {})
        if entry.get("candidates"):
            self.choose_homonym(raw)
            return
        self.start_lookup(raw, job=lambda: tmdb_enrich.with_candidates(entry, raw))
        self.statusBar().showMessage(f"Recherche des films possibles pour « {raw} »…")

    def start_lookup(self, raw, job=None):
        """Lance une recherche (ou un autre travail TMDB) pour ce titre."""
        thread = LookupThread(raw, self, job)
        thread.found.connect(self.on_lookup_found)
        thread.failed.connect(self.on_lookup_failed)
        thread.ambiguous.connect(self.on_ambiguous)
        thread.finished.connect(lambda raw=raw: self.lookups.pop(raw, None))
        self.lookups[raw] = thread
        self.loading = True
        for row in self.rows_of(raw):
            self.set_status(self.model.item(row, COL_STATUS), SEARCHING)
        self.loading = False
        self.set_title_editable(raw, False)
        thread.start()

    def on_ambiguous(self, raw, entry):
        """Un fil de recherche attend : choisir parmi les homonymes."""
        thread = self.sender()
        dialog = ChooseFilmDialog(raw, entry["candidates"], self)
        if self.sync is thread:
            self.sync_label.setText(f"Synchronisation : choix en attente pour « {raw} »")
        dialog.exec()
        thread.answer(dialog.choice, dialog.candidates)

    def choose_homonym(self, raw):
        """Fenêtre de choix avec les films gardés dans le cache (homonymes…).

        Sans film gardé (INTROUVABLE), la fenêtre cherche elle-même le titre.
        """
        entry = self.cache.get(raw, {})
        dialog = ChooseFilmDialog(raw, entry.get("candidates", []), self)
        if dialog.exec() and dialog.choice is not None:
            chosen = dict(entry, candidates=dialog.candidates)  # après une recherche libre
            self.start_lookup(raw, job=lambda: tmdb_enrich.choose(chosen, dialog.choice))
            self.statusBar().showMessage(f"« {raw} » : chargement du film choisi…")

    def apply_entry(self, raw, entry):
        """Affiche le résultat TMDB d'un titre sur toutes ses lignes."""
        self.cache[raw] = entry
        self.loading = True
        for r in self.rows_of(raw):
            num = self.model.item(r, 0).data(Qt.ItemDataRole.DisplayRole)
            self.fill_row(r, film_row(num, raw, entry, self.validations))
        self.loading = False
        self.set_title_editable(raw, True)  # recherche finie (ex. INTROUVABLE)
        self.fill_status_combo(refilter=False)

    def on_lookup_found(self, raw, entry):
        self.lookups.pop(raw, None)
        try:
            store_in_cache(self.cache_path, raw, entry)
        except OSError as e:
            QMessageBox.critical(self, "Erreur", f"Impossible d'écrire le cache :\n{e}")
        self.stamp = self.files_stamp()  # notre propre écriture : pas de rechargement
        self.apply_entry(raw, entry)
        status = tmdb_export.effective_status(raw, entry, self.validations)
        if status == "À VÉRIFIER" and not entry.get("candidates"):
            self.statusBar().showMessage(
                f"« {raw} » : TMDB ne propose pas d'autre film — corrige le titre "
                "(double-clic) ou coche « Validé » si le film proposé est le bon", 10000)
            return
        self.statusBar().showMessage(
            f"« {raw} » → {tmdb_enrich.found_label(entry)} : {status}", 10000)

    def on_lookup_failed(self, raw, message):
        self.lookups.pop(raw, None)
        if raw in self.cache:  # ex. À VÉRIFIER : on remet le film tel qu'il était
            self.apply_entry(raw, self.cache[raw])
        else:
            self.loading = True
            for r in self.rows_of(raw):
                self.set_status(self.model.item(r, COL_STATUS), NOT_DONE)
            self.loading = False
            self.set_title_editable(raw, True)
        self.statusBar().clearMessage()
        QMessageBox.warning(self, "Recherche TMDB",
                            f"Impossible de chercher « {raw} » :\n{message}")

    def on_item_changed(self, item):
        if self.loading:
            return
        if item.column() == COL_CHECK and item.isCheckable():
            self.on_validation(item)
        elif item.column() == COL_RAW:
            self.on_title_edited(item)

    def on_title_edited(self, item):
        """Titre corrigé : mise à jour de la liste.

        Un film OK ou À VÉRIFIER garde son film TMDB et passe (ou reste)
        « À VÉRIFIER », puisque le titre a changé ; les autres repassent
        « NON TRAITÉ ». Sauf si le nouveau titre est déjà dans le cache.
        """
        r = item.row()
        old = item.data(RAW_ROLE)
        new = " ".join(item.text().split())
        if self.is_searching(old):  # recherche lancée pendant la saisie
            self.loading = True
            item.setText(old)
            self.loading = False
            self.statusBar().showMessage(
                f"« {old} » est en cours de recherche : titre non modifié", 8000)
            return
        if not new or new == old:
            self.loading = True
            item.setText(old)  # rien à faire : on remet le titre d'origine
            self.loading = False
            return
        try:
            kept, e = self.rename_row(r, old, new)
        except (OSError, ValueError) as err:
            QMessageBox.critical(self, "Erreur", f"Impossible de corriger le titre :\n{err}")
            self.reload()
            return
        if kept:
            suite = ("film TMDB conservé, à vérifier : clic sur « À VÉRIFIER » pour "
                     "confirmer ou choisir un autre film")
        elif e:
            suite = f"déjà connu : {self.model.item(r, COL_STATUS).text()}"
        else:
            suite = ("clic sur « NON TRAITÉ » pour le chercher tout de suite, "
                     "ou au prochain « ./films.sh enrichir »")
        self.statusBar().showMessage(f"Titre corrigé : « {old} » → « {new} » ({suite})", 8000)

    def rename_row(self, r, old, new):
        """Renomme le titre de la ligne r dans la liste et dans le tableau.

        Retourne (film TMDB conservé ?, entrée de cache du nouveau titre).
        Lève OSError / ValueError si la liste n'a pas pu être modifiée.
        """
        num = self.model.item(r, 0).data(Qt.ItemDataRole.DisplayRole)
        rename_in_list(self.list_path, num, old, new)
        old_status = self.model.item(r, COL_STATUS).text()
        e = self.cache.get(new, {})
        kept = False
        if not e and old_status in ("OK", "À VÉRIFIER") and self.cache.get(old, {}).get("id"):
            # Film déjà trouvé : on garde le film TMDB, à vérifier avec le
            # nouveau titre. Les films possibles de l'ancien titre sont oubliés :
            # un clic sur « À VÉRIFIER » cherchera ceux du nouveau titre.
            e = {k: v for k, v in self.cache[old].items() if k != "candidates"}
            e["status"] = "À VÉRIFIER"
            try:
                store_in_cache(self.cache_path, new, e)
                self.cache[new] = e
                kept = True
            except OSError as err:
                QMessageBox.critical(self, "Erreur", f"Impossible d'écrire le cache :\n{err}")
                e = {}
        self.stamp = self.files_stamp()  # nos propres écritures : pas de rechargement
        self.loading = True
        self.fill_row(r, film_row(num, new, e, self.validations))
        self.loading = False
        self.fill_status_combo(refilter=False)
        return kept, e

    def on_validation(self, item):
        """Coche « Validé » : enregistre la validation et met à jour le statut."""
        row = item.row()
        raw = self.model.item(row, COL_RAW).text()
        movie_id = self.model.item(row, COL_ID).data(Qt.ItemDataRole.DisplayRole)
        validated = item.checkState() == Qt.CheckState.Checked
        if validated:
            self.validations[raw] = movie_id
        else:
            self.validations.pop(raw, None)
        try:
            tmdb_export.save_validations(self.list_path, self.validations)
        except OSError as e:
            QMessageBox.critical(self, "Erreur",
                                 f"Impossible d'enregistrer les validations :\n{e}")
            return
        status = "OK" if validated else "À VÉRIFIER"
        self.set_status(self.model.item(row, COL_STATUS), status, validated)
        self.set_title_editable(raw, True)  # selon le nouveau statut (OK : non modifiable)
        self.fill_status_combo(refilter=False)
        title = self.model.item(row, COL_TITLES[1]).text()
        self.statusBar().showMessage(
            f"« {raw} » → {title} : " + ("validé (OK)" if validated else "à vérifier"), 6000)

    def on_context_menu(self, pos):
        """Clic droit : choisir parmi les homonymes, annuler une validation."""
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        r = self.proxy.mapToSource(index).row()
        raw = self.model.item(r, COL_RAW).data(RAW_ROLE)
        entry = self.cache.get(raw, {})
        menu = QMenu(self)
        if entry.get("candidates") and raw not in self.lookups:
            menu.addAction("Choisir parmi les homonymes…", lambda: self.choose_homonym(raw))
        if tmdb_export.is_validated(raw, entry, self.validations):
            menu.addAction("Annuler la validation", lambda: self.unvalidate(raw))
        if menu.actions():
            menu.exec(self.table.viewport().mapToGlobal(pos))

    def unvalidate(self, raw):
        """Retire la validation : le film redevient « À VÉRIFIER », avec sa case."""
        self.validations.pop(raw, None)
        try:
            tmdb_export.save_validations(self.list_path, self.validations)
        except OSError as e:
            QMessageBox.critical(self, "Erreur",
                                 f"Impossible d'enregistrer les validations :\n{e}")
            return
        entry = self.cache.get(raw, {})
        self.loading = True
        for r in self.rows_of(raw):
            num = self.model.item(r, 0).data(Qt.ItemDataRole.DisplayRole)
            self.fill_row(r, film_row(num, raw, entry, self.validations))
        self.loading = False
        self.fill_status_combo(refilter=False)
        self.statusBar().showMessage(f"« {raw} » : validation annulée (à vérifier)", 6000)

    def on_status_filter(self):
        # Changement de filtre : on prend en compte les dernières validations.
        for r in range(self.model.rowCount()):
            item = self.model.item(r, COL_STATUS)
            item.setData(item.text(), FILTER_ROLE)
        self.proxy.set_status(self.status_combo.currentData())

    def fill_status_combo(self, refilter=True):
        counts = {}
        for r in range(self.model.rowCount()):
            s = self.model.item(r, COL_STATUS).text()
            counts[s] = counts.get(s, 0) + 1
        current = self.status_combo.currentData()
        self.status_combo.blockSignals(True)
        self.status_combo.clear()
        self.status_combo.addItem(f"Tous ({self.model.rowCount()})", None)
        for s in STATUSES:
            # le filtre courant reste proposé même s'il n'a plus de film
            if counts.get(s) or s == current:
                self.status_combo.addItem(f"{s} ({counts.get(s, 0)})", s)
        idx = self.status_combo.findData(current)
        self.status_combo.setCurrentIndex(max(idx, 0))
        self.status_combo.blockSignals(False)
        if refilter:
            self.proxy.set_status(self.status_combo.currentData())

    def update_count(self, *_):
        self.statusBar().showMessage(
            f"{self.proxy.rowCount()} film(s) affiché(s) sur {self.model.rowCount()}"
            " — double-clic sur une ligne pour ouvrir la fiche TMDB")

    def open_tmdb(self, index):
        src = self.proxy.mapToSource(index)
        if self.model.itemFromIndex(src).isEditable():
            return  # double-clic sur un titre modifiable : correction, pas la fiche
        movie_id = self.model.item(src.row(), COL_ID).text()
        if movie_id:
            QDesktopServices.openUrl(QUrl(f"https://www.themoviedb.org/movie/{movie_id}"))

    def visible_rows(self):
        """Films affichés, dans l'ordre affiché, au format de tmdb_export."""
        rows = []
        for r in range(self.proxy.rowCount()):
            src = self.proxy.mapToSource(self.proxy.index(r, 0)).row()
            film = dict(zip(COLUMNS, (self.model.item(src, c).data(Qt.ItemDataRole.DisplayRole)
                                      for c in range(len(COLUMNS)))))
            rows.append([film[h] if film[h] is not None else "" for h in tmdb_export.HEADER])
        return rows

    def export(self):
        rows = self.visible_rows()
        if not rows:
            QMessageBox.information(self, "Exporter", "Aucun film affiché à exporter.")
            return
        status = self.status_combo.currentData()
        default = tmdb_export.default_name(self.list_path, status) + ".md"
        path, chosen = QFileDialog.getSaveFileName(
            self, "Exporter les films affichés", default,
            "Markdown (*.md);;CSV (*.csv)")
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".csv" if chosen.startswith("CSV") else ".md"
        title = "Liste de films" + (f" — {status}" if status else "")
        if self.search.text().strip():
            title += f" — recherche « {self.search.text().strip()} »"
        try:
            if path.lower().endswith(".csv"):
                tmdb_export.write_csv(path, rows)
            else:
                tmdb_export.write_md(path, rows, title)
        except OSError as e:
            QMessageBox.critical(self, "Erreur", f"Impossible d'écrire {path} :\n{e}")
            return
        self.statusBar().showMessage(f"{len(rows)} film(s) exporté(s) dans {path}", 8000)

    def regenerate_files(self):
        """Réécrit liste_film_tmdb.md / .csv et les listes par statut avec les validations."""
        try:
            written, counts, n_validated = tmdb_export.regenerate(self.list_path)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            QMessageBox.critical(self, "Régénérer les fichiers", f"Impossible de régénérer :\n{e}")
            return
        summary = " · ".join(f"{k} : {v}" for k, v in sorted(counts.items()))
        files = "\n".join(f"  • {os.path.basename(p)}" for p in written)
        QMessageBox.information(
            self, "Régénérer les fichiers",
            f"Fichiers régénérés avec {n_validated} film(s) validé(s) en OK.\n\n"
            f"{summary}\n\n{files}")
        self.statusBar().showMessage("Fichiers de résultats régénérés", 8000)

    # --- Synchronisation -------------------------------------------------

    def titles_to_sync(self):
        """Titres NON TRAITÉ (sans doublon, dans l'ordre de la liste)."""
        titles = []
        for r in range(self.model.rowCount()):
            raw = self.model.item(r, COL_RAW).data(RAW_ROLE)
            if (raw not in self.cache and raw not in self.lookups
                    and raw not in titles):
                titles.append(raw)
        return titles

    def stop_sync(self):
        if self.sync and self.sync_btn.isEnabled():
            self.toggle_sync()

    def toggle_sync(self):
        if self.sync:  # déjà en cours : arrêter
            self.sync_stopped = True  # (Qt l'oublie une fois le fil terminé)
            self.sync.requestInterruption()
            self.sync_btn.setEnabled(False)
            self.sync_btn.setText("Arrêt en cours…")
            return
        titles = self.titles_to_sync()
        if not titles:
            QMessageBox.information(self, "Synchronisation",
                                    "Tous les titres de la liste ont déjà été cherchés sur TMDB.")
            return
        minutes = max(1, round(len(titles) * 0.5 / 60))
        box = QMessageBox(QMessageBox.Icon.Question, "Synchronisation",
                          f"Chercher {len(titles)} titre(s) sur TMDB ?", parent=self)
        box.setInformativeText(
            f"Durée estimée : environ {minutes} min. L'interface reste utilisable "
            "et la synchronisation peut être arrêtée à tout moment ; les films "
            "déjà trouvés sont conservés.")
        go_btn = box.addButton("Lancer", QMessageBox.ButtonRole.AcceptRole)
        cancel_btn = box.addButton("Annuler", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(go_btn)
        box.setEscapeButton(cancel_btn)
        box.exec()
        if box.clickedButton() is not go_btn:
            return
        self.start_sync(titles)

    def fix_titles(self, status):
        """Fenêtre pour corriger d'un coup les titres INTROUVABLE ou À VÉRIFIER.

        Les titres corrigés sont ensuite cherchés sur TMDB (si la case est
        cochée). Pour un À VÉRIFIER, le film déjà trouvé est conservé si la
        nouvelle recherche ne trouve rien.
        """
        title = f"Corriger les titres « {status} »"
        rows = []
        for r in range(self.model.rowCount()):
            raw = self.model.item(r, COL_RAW).data(RAW_ROLE)
            if self.model.item(r, COL_STATUS).text() == status and not self.is_searching(raw):
                rows.append((r, self.model.item(r, 0).data(Qt.ItemDataRole.DisplayRole), raw))
        if not rows:
            QMessageBox.information(self, title, f"Aucun film {status} dans la liste.")
            return
        rows.sort(key=lambda x: x[1])  # ordre de la liste
        dialog = FixTitlesDialog(rows, status, self)
        if not dialog.exec() or not dialog.changes:
            return
        done, to_search, keep = 0, [], {}
        for r, old, new in dialog.changes:
            try:
                kept, e = self.rename_row(r, old, new)
            except (OSError, ValueError) as err:
                QMessageBox.critical(
                    self, title,
                    f"Arrêt après {done} correction(s) : impossible de corriger "
                    f"« {old} » :\n{err}")
                self.reload()
                return
            done += 1
            # À chercher : titre inconnu, ou film conservé d'un À VÉRIFIER.
            if (not e or kept) and new not in to_search:
                to_search.append(new)
                if kept:
                    keep[new] = e
        message = f"{done} titre(s) corrigé(s) dans la liste"
        if to_search and dialog.search_after.isChecked():
            if self.sync:
                message += " ; synchronisation déjà en cours : relance-la ensuite pour les chercher"
            else:
                self.start_sync(to_search, keep)
                message += f" ; recherche de {len(to_search)} titre(s) sur TMDB"
        self.statusBar().showMessage(message, 10000)

    def start_sync(self, titles, keep=None):
        """Lance la recherche TMDB de ces titres, en arrière-plan (keep : voir SyncThread)."""
        self.sync_stats, self.sync_errors, self.sync_fatal = {}, [], None
        self.sync_done = 0
        self.sync_stopped = False
        self.sync = SyncThread(titles, self, keep)
        self.sync.progress.connect(self.on_sync_progress)
        self.sync.found.connect(self.on_sync_found)
        self.sync.title_failed.connect(self.on_sync_title_failed)
        self.sync.fatal.connect(self.on_sync_fatal)
        self.sync.ambiguous.connect(self.on_ambiguous)
        self.sync.finished.connect(self.on_sync_finished)
        self.sync_btn.setText("Arrêter la synchronisation")
        self.sync_btn.setToolTip("Arrêter la synchronisation (Échap)")
        self.esc_shortcut.setEnabled(True)
        self.progress.setRange(0, len(titles))
        self.progress.setValue(0)
        self.progress.show()
        self.sync.start()

    def set_searching(self, raw, searching):
        self.loading = True
        for r in self.rows_of(raw):
            if self.model.item(r, COL_STATUS).text() in (NOT_DONE, SEARCHING):
                self.set_status(self.model.item(r, COL_STATUS),
                                SEARCHING if searching else NOT_DONE)
        self.loading = False
        self.set_title_editable(raw, not searching)

    def on_sync_progress(self, done, total, raw):
        self.sync_done = done
        self.progress.setValue(done)
        self.sync_current = raw or None
        self.sync_label.setText(f"Synchronisation : {done}/{total}"
                                + (f" — {raw}" if raw else "") + " (Échap pour arrêter)")
        if raw:
            self.set_searching(raw, True)
        self.follow_sync(raw)

    def highlight_rows(self, raw, on):
        """Fond bleu (ou normal) sur toutes les cellules des lignes de ce titre."""
        self.loading = True
        for r in self.rows_of(raw):
            for c in range(len(COLUMNS)):
                self.model.item(r, c).setData(SYNC_ROW_COLOR if on else None,
                                              Qt.ItemDataRole.BackgroundRole)
        self.loading = False

    def follow_sync(self, raw):
        """Surligne le film en cours et le garde au milieu du tableau."""
        if self.sync_highlight and self.sync_highlight != raw:
            self.highlight_rows(self.sync_highlight, False)
        self.sync_highlight = raw or None
        if not raw:
            return
        self.highlight_rows(raw, True)
        rows = self.rows_of(raw)
        if rows:
            index = self.proxy.mapFromSource(self.model.index(rows[0], 0))
            if index.isValid():  # invisible si le filtre ou la recherche l'écarte
                self.table.scrollTo(index, QTableView.ScrollHint.PositionAtCenter)

    def on_sync_found(self, raw, entry):
        self.pending[raw] = entry
        self.apply_entry(raw, entry)
        status = tmdb_export.effective_status(raw, entry, self.validations)
        self.sync_stats[status] = self.sync_stats.get(status, 0) + 1
        if len(self.pending) >= 10:
            self.flush_pending()

    def on_sync_title_failed(self, raw, message):
        self.sync_errors.append((raw, message))
        self.set_searching(raw, False)

    def on_sync_fatal(self, message):
        self.sync_fatal = message
        if self.sync_current:
            self.set_searching(self.sync_current, False)

    def flush_pending(self):
        """Écrit dans le cache les résultats de synchronisation en attente."""
        if not getattr(self, "pending", None):
            return
        try:
            store_entries(self.cache_path, self.pending)
        except OSError as e:
            QMessageBox.critical(self, "Erreur", f"Impossible d'écrire le cache :\n{e}")
            return
        self.pending.clear()
        self.stamp = self.files_stamp()  # notre propre écriture : pas de rechargement

    def on_sync_finished(self):
        interrupted = self.sync_stopped
        total = len(self.sync.titles)
        self.sync = None
        if self.sync_current:
            self.set_searching(self.sync_current, False)
        self.sync_current = None
        self.follow_sync(None)
        self.flush_pending()
        self.progress.hide()
        self.sync_label.clear()
        self.sync_btn.setText("Synchronisation")
        self.sync_btn.setToolTip("Chercher sur TMDB tous les titres pas encore traités")
        self.sync_btn.setEnabled(True)
        self.esc_shortcut.setEnabled(False)
        if self.sync_fatal:
            QMessageBox.warning(self, "Synchronisation",
                                f"Synchronisation interrompue :\n{self.sync_fatal}")
            return
        found = sum(self.sync_stats.values())
        lines = [f"{'Synchronisation arrêtée' if interrupted else 'Synchronisation terminée'} : "
                 f"{found} titre(s) cherché(s) sur {total}."]
        if self.sync_stats:
            lines.append(" · ".join(f"{k} : {v}" for k, v in sorted(self.sync_stats.items())))
        if self.sync_errors:
            lines.append(f"{len(self.sync_errors)} titre(s) en erreur, restés NON TRAITÉ "
                         f"(ex. « {self.sync_errors[0][0]} » : {self.sync_errors[0][1]}).")
        if found:
            try:
                tmdb_export.regenerate(self.list_path)
                lines.append("Les fichiers de résultats ont été régénérés.")
            except (OSError, ValueError, json.JSONDecodeError) as e:
                lines.append(f"Fichiers de résultats non régénérés : {e}")
        QMessageBox.information(self, "Synchronisation", "\n\n".join(lines))

    def closeEvent(self, event):
        """Bouton « Quitter », Ctrl+Q ou croix de la fenêtre : demander confirmation."""
        box = QMessageBox(QMessageBox.Icon.Question, "Quitter",
                          "Voulez-vous vraiment quitter ?", parent=self)
        info = "Les validations et les corrections de titres sont déjà enregistrées."
        if self.sync:
            info += ("\n\nLa synchronisation en cours sera arrêtée ; les films déjà "
                     "trouvés sont conservés.")
        box.setInformativeText(info)
        quit_btn = box.addButton("Quitter", QMessageBox.ButtonRole.AcceptRole)
        cancel_btn = box.addButton("Annuler", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel_btn)  # Entrée ne quitte pas par mégarde
        box.setEscapeButton(cancel_btn)
        box.exec()
        if box.clickedButton() is quit_btn:
            if self.sync:
                self.sync.finished.disconnect()   # pas de bilan à la fermeture
                self.sync.requestInterruption()
                self.sync.answer(None)            # s'il attendait un choix
                self.sync.wait()                  # le titre en cours se termine
            for thread in list(self.lookups.values()):
                thread.requestInterruption()
                thread.answer(None)
                thread.wait()  # laisser finir les recherches en cours
            QApplication.processEvents()          # derniers résultats reçus
            self.flush_pending()
            event.accept()
        else:
            event.ignore()

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Ouvrir une liste de films", os.path.dirname(os.path.abspath(self.list_path)),
            "Listes (*.md *.txt);;Tous les fichiers (*)")
        if path:
            self.list_path = path
            self.reload()


def main():
    list_path = sys.argv[1] if len(sys.argv) > 1 else "liste_film.md"
    app = QApplication(sys.argv)
    if not os.path.exists(list_path):
        QMessageBox.critical(None, "Erreur", f"Fichier introuvable : {list_path}")
        return 1
    viewer = FilmViewer(list_path)
    viewer.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
