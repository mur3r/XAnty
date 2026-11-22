"""Package the executable with Chrome and ChromeDriver for another Windows PC."""
import argparse
import os
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def package(executable: Path) -> Path:
    root = Path(__file__).resolve().parents[1]
    executable = executable.resolve()
    if not executable.is_file():
        raise FileNotFoundError(executable)
    for filename in ('Bro/chrome.exe', 'Drivers/chromedriver.exe'):
        if not (root / filename).is_file():
            raise FileNotFoundError(root / filename)
    destination = executable.with_name(executable.stem + '-portable.zip')
    temporary = destination.with_suffix('.zip.tmp')
    instructions = '''XAnty — Windows x64

1. Распакуйте архив целиком в отдельную папку.
2. Запустите XAnty.exe.
3. При первом запуске выберите распакованную папку как рабочую:
   в ней уже находятся Bro/chrome.exe и Drivers/chromedriver.exe.
4. Язык интерфейса меняется внизу слева.

При обновлении закройте предыдущую версию и заново откройте профили.
Кнопка рядом с прокси проверяет его и показывает внешний IP или ошибку.
При закрытии последнего окна Chrome профиль получает статус «Закрыт».
Режим No Search автоматически исправляется на Google при запуске профиля.

Все профили Dolphin: «Из Dolphin» → API-токен → «Перенести все профили».
Передача профилей: закройте профили → «Передать профили» → выбранные или все.
Получение профилей: «Передать профили» → «Получить профили из файла» → .xanty.

Архив программы содержит приложение, браузер и драйвер.
Аккаунты, настройки, логи и сессии пользователя в него не включаются.
Файл .xanty с профилями передавайте получателю отдельно.
Для отображения окна требуется Microsoft Edge WebView2 Runtime.

API Dolphin не экспортирует полный отпечаток, расширения и local storage.
Cookies доступны по API на платном тарифе с облачной синхронизацией.
Недоступные данные отмечаются в отчёте. Некоторые сайты могут запросить вход повторно.
'''
    excluded_folders = {'user data', 'userdata', 'browser_profiles', 'webui_profile', 'logs', 'cache'}
    excluded_files = {'first run', 'cookies', 'history', 'login data', 'local state', 'accounts.json', 'paths.json'}
    try:
        with ZipFile(temporary, 'w', ZIP_DEFLATED, compresslevel=3, allowZip64=True) as archive:
            archive.write(executable, 'XAnty.exe')
            archive.writestr('START-HERE.txt', instructions.encode('utf-8-sig'))
            for folder in ('Bro', 'Drivers'):
                source = (root / folder).resolve()
                for path in sorted(source.rglob('*')):
                    if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(source):
                        continue
                    relative = path.relative_to(root)
                    if (path.suffix.lower() in ('.log', '.tmp') or path.name.lower() in excluded_files
                            or any(part.lower() in excluded_folders for part in relative.parts)):
                        continue
                    archive.write(path, relative.as_posix())
        with ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise RuntimeError('Portable archive verification failed')
            names = set(archive.namelist())
            if not {'XAnty.exe', 'Bro/chrome.exe', 'Drivers/chromedriver.exe', 'START-HERE.txt'}.issubset(names):
                raise RuntimeError('Required files are missing from portable archive')
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('exe', type=Path)
    args = parser.parse_args()
    print(f'Portable package ready: {package(args.exe)}')
