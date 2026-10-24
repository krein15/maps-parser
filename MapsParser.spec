# Сборка: .venv\Scripts\python -m PyInstaller MapsParser.spec --noconfirm
#
# Получается dist/MapsParser/MapsParser.exe: без аргументов открывается окно, с аргументами
# работает командная строка. Сборка папкой, а не одним файлом: так программа стартует сразу,
# а не распаковывает себя во временный каталог при каждом запуске.
#
# Браузер внутрь не кладётся и не нужен: обе карты отдают данные обычным запросом,
# поэтому программа весит десятки мегабайт, а не триста.

from PyInstaller.utils.hooks import collect_data_files

datas = [
    ("assets/icon.ico", "assets"),
    ("assets/brand/*.png", "assets/brand"),  # значок и логотип в шапке окна
    ("mapsparser/data/*.json", "mapsparser/data"),  # справочник городов 2ГИС
]
datas += collect_data_files("customtkinter")  # темы и шрифты окна

analysis = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=["openpyxl", "PIL._tkinter_finder"],
    excludes=["matplotlib", "numpy", "pandas", "pytest", "lxml", "tkinter.test", "test"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="MapsParser",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/icon.ico",
    version_info=None,
)

collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="MapsParser",
)
