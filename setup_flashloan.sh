#!/bin/bash

echo "=== Marginfi Flash Loan Bot - Быстрая настройка ==="
echo ""

# Проверка наличия .env файла
if [ ! -f ".env" ]; then
    echo "Создаю .env файл из .env.example..."
    cp .env.example .env
    echo "Заполните .env файл вашими значениями!"
    echo "Обязательные поля:"
    echo "  - MARGINFI_ACCOUNT=ваш_marginfi_аккаунт"
    echo "  - FLASHLOAN_PROGRAM_ID=ваш_задеплоенный_контракт"
    echo "  - HELIUS_API_KEY=ваш_helius_api_key"
    echo "  - MARGINFI_SOL_BANK=CCwqExrqLGHtq12X182rFvA4KEDtK13q2E7B3Jp2Cxyj"
    echo "  - MARGINFI_USDC_BANK=2s37akK2eyBbp8DZgCm7RtsaEz8eWhVKGfHGA3cKMEW2"
    echo ""
else
    echo "Проверяю .env файл..."
    if ! grep -q "MARGINFI_ACCOUNT=" .env; then
        echo "Ошибка: MARGINFI_ACCOUNT не найден в .env"
        exit 1
    fi
    if ! grep -q "HELIUS_API_KEY=" .env; then
        echo "Ошибка: HELIUS_API_KEY не найден в .env"
        exit 1
    fi
    echo ".env файл валиден."
fi

echo "1. Заполните .env файл:"
echo "   - MARGINFI_ACCOUNT=ваш_marginfi_аккаунт"
echo "   - FLASHLOAN_PROGRAM_ID=будет_после_деплоя"
echo ""

echo "2. Соберите контракт:"
echo "   anchor build"
echo ""

echo "3. Задеплойте контракт:"
echo "   anchor deploy"
echo "   (скопируйте program ID в FLASHLOAN_PROGRAM_ID)"
echo ""

echo "4. Запустите бота:"
echo "   python arb_bot.py"
echo ""

echo "=== Готово к запуску! ==="