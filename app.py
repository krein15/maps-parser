"""Точка входа программы (её же использует PyInstaller).

Без аргументов открывается окно, с аргументами работает командная строка —
так собранный exe годится и для запуска по расписанию:

    MapsParser.exe collect -q кофейня -c Тюмень
"""

import sys

if __name__ == "__main__":
    if len(sys.argv) > 1:
        from mapsparser.__main__ import main as cli_main
        from mapsparser.__main__ import setup_console

        setup_console()
        sys.exit(cli_main())

    from mapsparser.gui.app import main

    main()
