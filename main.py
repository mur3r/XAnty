"""
Точка входа X-Genius. Запуск из папки проекта:

    python main.py

Весь код живёт в пакете xgenius/ (см. README.md). Этот файл оставлен, чтобы
существующие ярлыки / сборки, запускающие main.py, продолжали работать.
"""
import sys

if __name__ == "__main__":
    try:
        from xgenius.app import run
        run()
    except Exception as exc:
        if sys.platform == "win32" and getattr(sys, "frozen", False):
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, str(exc), "XAnty - launch error", 0x10)
        else:
            raise
