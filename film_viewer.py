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
Bouton « Exporter… » : enregistre les films affichés (filtre et recherche
appliqués) en Markdown ou en CSV.

Colonne « Validé » : cocher un film « À VÉRIFIER » valide le titre TMDB
proposé ; il passe en « OK ». Les validations sont enregistrées dans
validations.json (à côté de la liste) et reprises par tmdb_enrich.py.
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

import tmdb_export

CACHE_FILE = ".tmdb_cache.json"  # même nom que dans tmdb_enrich.py
NOT_DONE = "NON TRAITÉ"
STATUSES = ["OK", "À VÉRIFIER", "INTROUVABLE", NOT_DONE]
STATUS_COLORS = {
    "OK": QColor("#2e9e44"),
    "À VÉRIFIER": QColor("#d98a00"),
    "INTROUVABLE": QColor("#d43c3c"),
    NOT_DONE: QColor("#888888"),
}
COLUMNS = ["#", "Statut", "Validé", "Titre (liste)", "Titre TMDB", "Titre original",
           "Date de sortie", "Réalisateur", "ID TMDB"]
COL_STATUS = COLUMNS.index("Statut")
COL_CHECK = COLUMNS.index("Validé")
COL_RAW = COLUMNS.index("Titre (liste)")
COL_ID = COLUMNS.index("ID TMDB")
COL_TITLES = [COLUMNS.index(c) for c in ("Titre (liste)", "Titre TMDB", "Titre original")]
COL_SEARCH = COL_TITLES + [COLUMNS.index("Réalisateur")]
# Statut utilisé par le filtre : figé jusqu'au prochain changement de filtre,
# pour qu'une ligne cochée ne disparaisse pas sous le curseur.
FILTER_ROLE = Qt.ItemDataRole.UserRole + 1


def load_films(list_path):
    """Une ligne par titre de la liste, complétée par le cache TMDB.

    Chaque ligne suit COLUMNS ; la colonne « Validé » vaut None si le film
    ne peut pas être validé (statut autre que « À VÉRIFIER »), sinon True/False.
    """
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
    films = []
    for i, raw in enumerate(titles, 1):
        e = cache.get(raw, {})
        checkable = e.get("status") == "À VÉRIFIER" and bool(e.get("id"))
        validated = tmdb_export.is_validated(raw, e, validations) if checkable else None
        status = tmdb_export.effective_status(raw, e, validations) if e else NOT_DONE
        films.append([i, status, validated, raw, e.get("title", ""),
                      e.get("original_title", ""), e.get("date", ""),
                      e.get("director", ""), e.get("id", "")])
    return films, cache_path, validations


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
        self.table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        self.table.doubleClicked.connect(self.open_tmdb)

        self.status_combo = QComboBox()
        self.status_combo.currentIndexChanged.connect(self.on_status_filter)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher un titre ou un réalisateur…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.proxy.set_text)
        open_btn = QPushButton("Ouvrir une liste…")
        open_btn.clicked.connect(self.choose_file)
        reload_btn = QPushButton("Recharger")
        reload_btn.clicked.connect(self.reload)
        export_btn = QPushButton("Exporter…")
        export_btn.setToolTip("Enregistrer les films affichés en Markdown ou en CSV")
        export_btn.clicked.connect(self.export)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Statut :"))
        bar.addWidget(self.status_combo)
        bar.addWidget(self.search, 1)
        bar.addWidget(reload_btn)
        bar.addWidget(export_btn)
        bar.addWidget(open_btn)
        layout = QVBoxLayout()
        layout.addLayout(bar)
        layout.addWidget(self.table)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        self.loading = False
        self.validations = {}
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
            films, cache_path, self.validations = load_films(self.list_path)
        except OSError as e:
            QMessageBox.critical(self, "Erreur", f"Impossible de lire {self.list_path} :\n{e}")
            return
        self.watch(cache_path)
        self.setWindowTitle(f"Films TMDB — {os.path.basename(self.list_path)}")

        self.stamp = self.files_stamp()
        scroll = self.table.verticalScrollBar().value()

        self.loading = True
        self.model.removeRows(0, self.model.rowCount())
        for film in films:
            row = []
            for col, value in enumerate(film):
                item = QStandardItem()
                if col == COL_CHECK:
                    item.setEditable(False)
                    item.setCheckable(value is not None)
                    if value is not None:
                        item.setCheckState(Qt.CheckState.Checked if value
                                           else Qt.CheckState.Unchecked)
                        item.setToolTip("Cocher pour valider le titre TMDB proposé")
                elif col == 0 or (col == COL_ID and value != ""):
                    item.setData(int(value), Qt.ItemDataRole.DisplayRole)  # tri numérique
                else:
                    item.setText(str(value))
                row.append(item)
            self.set_status(row[COL_STATUS], film[COL_STATUS], film[COL_CHECK])
            row[COL_STATUS].setData(film[COL_STATUS], FILTER_ROLE)
            if film[COL_ID]:
                row[COL_ID].setToolTip("Double-clic : ouvrir la fiche TMDB")
            self.model.appendRow(row)
        self.loading = False

        self.fill_status_combo()
        self.update_count()
        self.table.verticalScrollBar().setValue(scroll)

    @staticmethod
    def set_status(item, status, validated=None):
        item.setText(status)
        item.setForeground(STATUS_COLORS.get(status, QColor("#888888")))
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        item.setToolTip("Validé manuellement" if validated else "")

    def on_item_changed(self, item):
        """Coche « Validé » : enregistre la validation et met à jour le statut."""
        if self.loading or item.column() != COL_CHECK or not item.isCheckable():
            return
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
