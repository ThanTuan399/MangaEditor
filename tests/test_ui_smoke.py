import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PySide6.QtWidgets import QApplication

from manga_editor.presentation.main_window import MainWindow

APP = QApplication.instance() or QApplication([])


class UiSmokeTests(unittest.TestCase):
    def test_main_window_can_be_created(self):
        window = MainWindow()
        self.assertIn("v0.2", window.windowTitle())
        window.session.dirty = False
        window.close()
        window.deleteLater()
        APP.processEvents()


if __name__ == "__main__":
    unittest.main()
