from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from clubconcours.app.ui_boot import BootDialog
from clubconcours.app.ui_main import MainWindow


def apply_theme(app: QApplication) -> None:
    # Load QSS file shipped with the app
    qss_path = Path(__file__).resolve().parent / "theme.qss"
    if qss_path.exists():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))
    # Optional: consistent tooltip delays etc could go here


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app)

    boot = BootDialog()
    if boot.exec() != BootDialog.Accepted or boot.db_path is None:
        return 0

    w = MainWindow(db_path=boot.db_path)
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())