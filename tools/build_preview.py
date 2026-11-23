"""
Собирает xgenius/web/static/preview.html — одностраничную копию интерфейса со встроенными
CSS/JS. Её можно открыть двойным кликом без запущенного сервиса: покажет демо-данные.
Запуск: python tools/build_preview.py
"""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "xgenius" / "web" / "static"


def build() -> Path:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for name in ("style.css", "design-system.css", "profiles-screen.css"):
        css = (STATIC / name).read_text(encoding="utf-8")
        html = html.replace(f'<link rel="stylesheet" href="{name}">', f"<style>\n{css}\n</style>")

    def inline_script(m):
        name = m.group(1)
        js = (STATIC / name).read_text(encoding="utf-8")
        return f"<script>\n/* ---- {name} ---- */\n{js}\n</script>"

    html = re.sub(r'<script src="([a-z-]+\.js)"></script>', inline_script, html)
    html = html.replace("<title>XAnty</title>", "<title>XAnty (preview)</title>")
    out = STATIC / "preview.html"
    out.write_text(html, encoding="utf-8")
    return out


if __name__ == "__main__":
    print("written:", build())
