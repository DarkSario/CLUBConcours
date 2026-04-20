from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from clubconcours.app.ui_boot import BootDialog
from clubconcours.app.ui_main import MainWindow


def main() -> int:
    app = QApplication(sys.argv)

    boot = BootDialog()
    if boot.exec() != BootDialog.Accepted or boot.db_path is None:
        return 0

    w = MainWindow(db_path=boot.db_path)
    w.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())