"""Check command delivery when its server process exits."""

import sys
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtNetwork import QLocalServer

from terminx.ui.sidebar import receive_instance_command


def main():
    app = QCoreApplication([])
    server = QLocalServer()
    name, directory = sys.argv[1:3]
    assert server.listen(name)
    received = []

    def quit():
        received.append("quit")
        app.quit()

    window = SimpleNamespace(quit=quit)
    server.newConnection.connect(lambda: receive_instance_command(server, window))
    (Path(directory) / "server-ready").touch()
    QTimer.singleShot(8000, app.quit)
    app.exec()
    server.close()
    assert received == ["quit"], "The server exited before it received the command"


if __name__ == "__main__":
    main()
