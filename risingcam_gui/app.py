import sys

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def main() -> int:
    QCoreApplication.setOrganizationName("EL Measurement Lab")
    QCoreApplication.setApplicationName("EL Measurement Equipment Control")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()
