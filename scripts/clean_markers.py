#!/usr/bin/env python3
"""
FIX 267: Очистка кодовой базы от мусорных маркеров («Fix N», «Phase N», «Task N»)
Удаляет избыточные номерные комментарии, захламляющие код.
"""
import re
import os

# Паттерн для маркеров: Fix N, Phase N, Task N, БЛОК N в начале строки после #
# Сохраняем осмысленные комментарии, удаляя только пустые номерные маркеры
MARKER_PATTERN = re.compile(
    r"#\s*(" 
    r"FIX\s*\d+[.:]?\s*"
    r"|"
    r"Phase\s*\d+[.:]?\s*"
    r"|"
    r"Task\s*\d+[.:]?\s*"
    r"|"
    r"БЛОК\s*\d+[.:]?\s*"
    r")"
    r"[—-]?\s*",
    re.IGNORECASE,
)

def clean_file(filepath):
    """Удаляет номерные маркеры из комментариев в файле."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    orig_len = len(content)
    content = MARKER_PATTERN.sub("# ", content)
    # Убираем двойные пробелы после #
    content = content.replace("#  ", "# ")

    if len(content) != orig_len:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    return False

if __name__ == "__main__":
    cleaned = 0
    for root, _, files in os.walk("src"):
        for file in files:
            if file.endswith(".py"):
                if clean_file(os.path.join(root, file)):
                    print(f"🧹 Cleaned: {os.path.join(root, file)}")
                    cleaned += 1

    print(f"✅ Clean markers complete: {cleaned} files modified.")
