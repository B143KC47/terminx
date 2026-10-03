# Third-party software

The source project uses the MIT license.
The Windows package also contains libraries with their own licenses.
The `licenses` directory contains their original notices.
The release component record gives the distribution versions.
The release includes the matching Qt and PySide source archives in a different ZIP.
The source record gives the upstream URLs and SHA-256 values.

| Component | Source or license reference |
|---|---|
| CPython | [Python license](https://docs.python.org/3/license.html) |
| OpenSSL | [OpenSSL license](https://github.com/openssl/openssl/blob/openssl-3.5.4/LICENSE.txt) |
| libffi | [libffi license](https://github.com/libffi/libffi/blob/v3.4.6/LICENSE) |
| SQLite | [SQLite public domain statement](https://sqlite.org/copyright.html) |
| PySide6 and Shiboken6 | [Qt for Python](https://doc.qt.io/qtforpython-6/) |
| Qt libraries | [Qt licensing](https://doc.qt.io/qt-6/licensing.html) |
| Rich | [Rich source](https://github.com/Textualize/rich) |
| psutil | [psutil source](https://github.com/giampaolo/psutil) |
| tomlkit | [tomlkit source](https://github.com/python-poetry/tomlkit) |
| markdown-it-py and mdurl | [markdown-it-py source](https://github.com/executablebooks/markdown-it-py) |
| Pygments | [Pygments source](https://github.com/pygments/pygments) |
| PyInstaller bootloader | [PyInstaller license](https://pyinstaller.org/en/stable/license.html) |
| Inno Setup | [Inno Setup source](https://github.com/jrsoftware/issrc) |

The package keeps Qt and PySide libraries as different replaceable files.
The package does not restrict replacement of LGPL libraries or debugging of those replacements.
The application source and build instructions stay available in this repository.
The package does not modify third-party library source.
The [Qt obligations reference](https://www.qt.io/development/open-source-lgpl-obligations) describes library source and replacement rights.
Original upstream license text takes precedence over this short component description.
