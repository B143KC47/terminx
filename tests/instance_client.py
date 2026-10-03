"""Send a test command from a different process."""

import sys
import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QLocalSocket

from terminx.ui.sidebar import notify_running_instance


def main():
    app = QCoreApplication([])
    name, command = sys.argv[1:3]
    if command != "partial":
        assert notify_running_instance(name, command.encode())
        return
    work = Path(sys.argv[3])
    socket = QLocalSocket()
    socket.connectToServer(name)
    assert socket.waitForConnected(3000)
    socket.write(b"qu")
    socket.flush()
    (work / "partial").touch()
    deadline = time.monotonic() + 5
    while not (work / "complete").exists():
        assert time.monotonic() < deadline, "The test did not allow command completion"
        app.processEvents()
        time.sleep(0.01)
    socket.write(b"it\n")
    socket.flush()
    assert socket.bytesAvailable() or socket.waitForReadyRead(3000)
    assert bytes(socket.readAll()).strip() == b"ok"
    socket.disconnectFromServer()


if __name__ == "__main__":
    main()
