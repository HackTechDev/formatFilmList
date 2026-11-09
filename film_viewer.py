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

Films « INTROUVABLE » : double-clic (ou F2) sur « Titre (liste) » pour
corriger le titre. La correction est écrite dans la liste ; le nouveau titre
sera cherché au prochain lancement de tmdb_enrich.py.

Films « NON TRAITÉ » : un clic sur « NON TRAITÉ » cherche tout de suite ce
titre sur TMDB (en arrière-plan) et enregistre le résultat dans le cache.
"""
import json
import os
import sys

from PyQt6.QtCore import (QFileSystemWatcher, QSortFilterProxyModel, Qt,
                          QThread, QTimer, QUrl, pyqtSignal)
from PyQt6.QtGui import (QColor, QDesktopServices, QKeySequence, QShortcut,
                         QStandardItem, QStandardItemModel)
from PyQt6.QtWidgets import (QApplication, QComboBox, QFileDialog, QHBoxLayout,
                             QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu,
                             QMessageBox, QPushButton, QTableView, QVBoxLayout,
                             QWidget)

import tmdb_enrich
import tmdb_export

CACHE_FILE = ".tmdb_cache.json"  # même nom que dans tmdb_enrich.py
NOT_DONE = "NON TRAITÉ"
STATUSES = ["OK", "À VÉRIFIER", "INTROUVABLE", NOT_DONE]
STATUS_COLORS = {
    "OK": QColor("#2e9e44"),
    "À VÉRIFIER": QColor("#d98a00"),
    "INTROUVABLE": QColor("#d43c3c"),
    NOT_DONE: QColor("#888888"),
    "RECHERCHE…": QColor("#2f6fd6"),
}
SEARCHING = "RECHERCHE…"
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
    """Ajoute une entrée au cache sur disque (relu juste avant, écrit d'un coup)."""
    cache = {}
    if os.path.exists(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    cache[raw] = entry
    tmp = cache_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    os.replace(tmp, cache_path)


class LookupThread(QThread):
    """Recherche TMDB d'un titre, hors du fil de l'interface."""
    found = pyqtSignal(str, object)   # titre, entrée de cache
    failed = pyqtSignal(str, str)     # titre, message d'erreur

    def __init__(self, raw, parent):
        super().__init__(parent)
        self.raw = raw

    def run(self):
        try:
            self.found.emit(self.raw, tmdb_enrich.lookup(self.raw))
        except tmdb_enrich.TmdbError as e:
            self.failed.emit(self.raw, str(e))
        except Exception as e:  # réseau, réponse inattendue…
            self.failed.emit(self.raw, f"{type(e).__name__} : {e}")


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
        # Seul le titre des films INTROUVABLE est modifiable (voir fill_row).
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
        editable = film[COL_STATUS] == "INTROUVABLE"
        raw_item.setEditable(editable)
        raw_item.setToolTip("Double-clic (ou F2) pour corriger le titre" if editable else "")
        if film[COL_STATUS] == NOT_DONE and film[COL_RAW] in self.lookups:
            self.set_status(items[COL_STATUS], SEARCHING)

    @staticmethod
    def set_status(item, status, validated=None):
        item.setText(status)
        item.setForeground(STATUS_COLORS.get(status, QColor("#888888")))
        font = item.font()
        font.setBold(True)
        font.setUnderline(status == NOT_DONE)  # cliquable, comme un lien
        item.setFont(font)
        if status == NOT_DONE:
            item.setToolTip("Cliquer pour chercher ce film sur TMDB")
        else:
            item.setToolTip("Validé manuellement — clic droit pour annuler la validation"
                            if validated else "")

    def rows_of(self, raw):
        return [r for r in range(self.model.rowCount())
                if self.model.item(r, COL_RAW).data(RAW_ROLE) == raw]

    def on_cell_clicked(self, index):
        """Clic sur « NON TRAITÉ » : recherche immédiate du titre sur TMDB."""
        if index.column() != COL_STATUS:
            return
        r = self.proxy.mapToSource(index).row()
        if self.model.item(r, COL_STATUS).text() != NOT_DONE:
            return
        raw = self.model.item(r, COL_RAW).data(RAW_ROLE)
        if raw in self.lookups:
            return
        thread = LookupThread(raw, self)
        thread.found.connect(self.on_lookup_found)
        thread.failed.connect(self.on_lookup_failed)
        thread.finished.connect(lambda raw=raw: self.lookups.pop(raw, None))
        self.lookups[raw] = thread
        self.loading = True
        for row in self.rows_of(raw):
            self.set_status(self.model.item(row, COL_STATUS), SEARCHING)
        self.loading = False
        self.statusBar().showMessage(f"Recherche de « {raw} » sur TMDB…")
        thread.start()

    def on_lookup_found(self, raw, entry):
        try:
            store_in_cache(self.cache_path, raw, entry)
        except OSError as e:
            QMessageBox.critical(self, "Erreur", f"Impossible d'écrire le cache :\n{e}")
        self.cache[raw] = entry
        self.stamp = self.files_stamp()  # notre propre écriture : pas de rechargement
        self.loading = True
        for r in self.rows_of(raw):
            num = self.model.item(r, 0).data(Qt.ItemDataRole.DisplayRole)
            self.fill_row(r, film_row(num, raw, entry, self.validations))
        self.loading = False
        self.fill_status_combo(refilter=False)
        status = tmdb_export.effective_status(raw, entry, self.validations)
        self.statusBar().showMessage(
            f"« {raw} » → {tmdb_enrich.found_label(entry)} : {status}", 10000)

    def on_lookup_failed(self, raw, message):
        self.loading = True
        for r in self.rows_of(raw):
            self.set_status(self.model.item(r, COL_STATUS), NOT_DONE)
        self.loading = False
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
        """Titre d'un film INTROUVABLE corrigé : mise à jour de la liste."""
        r = item.row()
        old = item.data(RAW_ROLE)
        new = " ".join(item.text().split())
        if not new or new == old:
            self.loading = True
            item.setText(old)  # rien à faire : on remet le titre d'origine
            self.loading = False
            return
        num = self.model.item(r, 0).data(Qt.ItemDataRole.DisplayRole)
        try:
            rename_in_list(self.list_path, num, old, new)
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, "Erreur", f"Impossible de corriger le titre :\n{e}")
            self.reload()
            return
        self.stamp = self.files_stamp()  # notre propre écriture : pas de rechargement
        e = self.cache.get(new, {})
        self.loading = True
        self.fill_row(r, film_row(num, new, e, self.validations))
        self.loading = False
        self.fill_status_combo(refilter=False)
        if e:
            suite = f"déjà connu : {self.model.item(r, COL_STATUS).text()}"
        else:
            suite = "sera recherché au prochain « ./films.sh enrichir »"
        self.statusBar().showMessage(f"Titre corrigé : « {old} » → « {new} » ({suite})", 8000)

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
        self.fill_status_combo(refilter=False)
        title = self.model.item(row, COL_TITLES[1]).text()
        self.statusBar().showMessage(
            f"« {raw} » → {title} : " + ("validé (OK)" if validated else "à vérifier"), 6000)

    def on_context_menu(self, pos):
        """Clic droit sur un film validé : proposer d'annuler la validation."""
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        r = self.proxy.mapToSource(index).row()
        raw = self.model.item(r, COL_RAW).data(RAW_ROLE)
        if not tmdb_export.is_validated(raw, self.cache.get(raw, {}), self.validations):
            return
        menu = QMenu(self)
        menu.addAction("Annuler la validation", lambda: self.unvalidate(raw))
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

    def closeEvent(self, event):
        """Bouton « Quitter », Ctrl+Q ou croix de la fenêtre : demander confirmation."""
        box = QMessageBox(QMessageBox.Icon.Question, "Quitter",
                          "Voulez-vous vraiment quitter ?", parent=self)
        box.setInformativeText(
            "Les validations et les corrections de titres sont déjà enregistrées.")
        quit_btn = box.addButton("Quitter", QMessageBox.ButtonRole.AcceptRole)
        cancel_btn = box.addButton("Annuler", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel_btn)  # Entrée ne quitte pas par mégarde
        box.setEscapeButton(cancel_btn)
        box.exec()
        if box.clickedButton() is quit_btn:
            for thread in list(self.lookups.values()):
                thread.wait()  # laisser finir les recherches en cours
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
