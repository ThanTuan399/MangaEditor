from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .presentation.main_window import MainWindow


def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("MangaEditor V0")
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()
