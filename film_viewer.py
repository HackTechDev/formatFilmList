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
"""
import json
import os
import sys

from PyQt6.QtCore import (QFileSystemWatcher, QSortFilterProxyModel, Qt,
                          QTimer, QUrl)
from PyQt6.QtGui import QColor, QDesktopServices, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (QApplication, QComboBox, QFileDialog, QHBoxLayout,
                             QHeaderView, QLabel, QLineEdit, QMainWindow,
                             QMessageBox, QPushButton, QTableView, QVBoxLayout,
                             QWidget)

CACHE_FILE = ".tmdb_cache.json"  # même nom que dans tmdb_enrich.py
NOT_DONE = "NON TRAITÉ"
STATUSES = ["OK", "À VÉRIFIER", "INTROUVABLE", NOT_DONE]
STATUS_COLORS = {
    "OK": QColor("#2e9e44"),
    "À VÉRIFIER": QColor("#d98a00"),
    "INTROUVABLE": QColor("#d43c3c"),
    NOT_DONE: QColor("#888888"),
}
COLUMNS = ["#", "Statut", "Titre (liste)", "Titre TMDB", "Titre original",
           "Date de sortie", "Réalisateur", "ID TMDB"]
COL_STATUS = COLUMNS.index("Statut")
COL_ID = COLUMNS.index("ID TMDB")
COL_TITLES = [COLUMNS.index(c) for c in ("Titre (liste)", "Titre TMDB", "Titre original")]
COL_SEARCH = COL_TITLES + [COLUMNS.index("Réalisateur")]


def load_films(list_path):
    """Retourne une ligne par titre de la liste, complétée par le cache TMDB."""
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
    films = []
    for i, raw in enumerate(titles, 1):
        e = cache.get(raw, {})
        films.append([i, e.get("status", NOT_DONE), raw, e.get("title", ""),
                      e.get("original_title", ""), e.get("date", ""),
                      e.get("director", ""), e.get("id", "")])
    return films, cache_path


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
        if self.status and m.item(row, COL_STATUS).text() != self.status:
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
        self.table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        self.table.doubleClicked.connect(self.open_tmdb)

        self.status_combo = QComboBox()
        self.status_combo.currentIndexChanged.connect(
            lambda: self.proxy.set_status(self.status_combo.currentData()))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher un titre ou un réalisateur…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.proxy.set_text)
        open_btn = QPushButton("Ouvrir une liste…")
        open_btn.clicked.connect(self.choose_file)
        reload_btn = QPushButton("Recharger")
        reload_btn.clicked.connect(self.reload)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Statut :"))
        bar.addWidget(self.status_combo)
        bar.addWidget(self.search, 1)
        bar.addWidget(reload_btn)
        bar.addWidget(open_btn)
        layout = QVBoxLayout()
        layout.addLayout(bar)
        layout.addWidget(self.table)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

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

    def schedule_reload(self, *_):
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
            films, cache_path = load_films(self.list_path)
        except OSError as e:
            QMessageBox.critical(self, "Erreur", f"Impossible de lire {self.list_path} :\n{e}")
            return
        self.watch(cache_path)
        self.setWindowTitle(f"Films TMDB — {os.path.basename(self.list_path)}")

        self.model.removeRows(0, self.model.rowCount())
        for film in films:
            row = []
            for col, value in enumerate(film):
                item = QStandardItem()
                if col == 0 or (col == COL_ID and value != ""):
                    item.setData(int(value), Qt.ItemDataRole.DisplayRole)  # tri numérique
                else:
                    item.setText(str(value))
                row.append(item)
            status = film[COL_STATUS]
            row[COL_STATUS].setForeground(STATUS_COLORS.get(status, QColor("#888888")))
            font = row[COL_STATUS].font()
            font.setBold(True)
            row[COL_STATUS].setFont(font)
            if film[COL_ID]:
                row[COL_ID].setToolTip("Double-clic : ouvrir la fiche TMDB")
            self.model.appendRow(row)

        self.films = films
        self.fill_status_combo()
        self.update_count()

    def fill_status_combo(self):
        counts = {}
        for f in self.films:
            counts[f[COL_STATUS]] = counts.get(f[COL_STATUS], 0) + 1
        current = self.status_combo.currentData()
        self.status_combo.blockSignals(True)
        self.status_combo.clear()
        self.status_combo.addItem(f"Tous ({len(self.films)})", None)
        for s in STATUSES:
            if counts.get(s):
                self.status_combo.addItem(f"{s} ({counts[s]})", s)
        idx = self.status_combo.findData(current)
        self.status_combo.setCurrentIndex(max(idx, 0))
        self.status_combo.blockSignals(False)
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
