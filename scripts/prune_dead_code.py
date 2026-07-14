#!/usr/bin/env python3
"""
FIX 263: Скрипт автоматического удаления мертвого кода (Pruning Tool)
Сканирует проект, находит неиспользуемые функции и переменные с помощью AST.
"""
import ast
import os
import sys

def find_dead_elements(filepath):
    """Анализирует Python-файл и возвращает неиспользуемые функции."""
    with open(filepath, "r", encoding="utf-8") as f:
        try:
            tree = ast.parse(f.read(), filename=filepath)
        except SyntaxError:
            return set()

    defined_funcs = set()
    used_names = set()
    imports = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            defined_funcs.add(node.name)
        elif isinstance(node, ast.AsyncFunctionDef):
            defined_funcs.add(node.name)
        elif isinstance(node, ast.ClassDef):
            defined_funcs.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used_names.add(node.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.asname or alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imports.add(alias.asname or alias.name.split('.')[0])

    # Функции, которые объявлены, но ни разу не вызваны внутри этого же файла
    dead_funcs = defined_funcs - used_names - imports
    # Исключаем __init__ и магические методы
    dead_funcs = {f for f in dead_funcs if not f.startswith('__')}
    return dead_funcs

if __name__ == "__main__":
    target_dirs = ["src", "tests"]
    for td in target_dirs:
        if not os.path.exists(td):
            continue
        for root, _, files in os.walk(td):
            for file in files:
                if file.endswith(".py"):
                    path = os.path.join(root, file)
                    dead = find_dead_elements(path)
                    if dead:
                        print(f"⚠️ {path}: Неиспользуемые элементы: {dead}")

    print("✅ Prune analysis complete.")
