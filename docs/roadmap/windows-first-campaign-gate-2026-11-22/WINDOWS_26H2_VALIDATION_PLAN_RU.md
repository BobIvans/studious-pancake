# Windows 11 26H2 — целевая среда и проверочный контракт

## Целевая конфигурация

Основная машина исполнения Flashloan Bot — native Windows 11 x64, General Availability Channel, актуальный стабильный выпуск. По Microsoft Windows Release Health на 2026-11-22:
- Windows 11 26H2, OS build family 26300;
- последнее ноябрьское обновление GA указано как build 26300.9974, от 2026-11-10;
- Python-проект сейчас требует >=3.13,<3.14; фактический Windows smoke в #670 был на Python 3.13.15 x64.

Референс Windows Release Health: https://learn.microsoft.com/en-us/windows/release-health/windows11-release-information

Не считать этот build зафиксированной версией пользовательской машины. Перед любым receipt снимать реальные Caption, DisplayVersion/WindowsVersion, BuildNumber, Architecture, PowerShell и Python patch. Windows 10.0 в Kernel/OS Version string не означает Windows 10: build 26300 относится к Windows 11 26H2. В #670 это нужно назвать корректно.

## Что уже проверено в #670

Исходный receipt сообщает:
- native Windows, x64; Git Bash;
- Python 3.13.15;
- build==1.5.0, setuptools==84.1.0 и wheel==0.47.0 установлены в venv;
- wheel build стал PASS;
- package_smoke wheelhouse упал из-за uvloop==0.22.1 без platform marker в requirements.lock;
- verify_occ_durable_host упал с PermissionError WinError 32 при удалении content.sqlite3;
- полный pytest: 288 failed, 5599 passed, 9 skipped, 327 errors на указанном baseline; большинство errors из pytest-socket/ProactorEventLoop, а genuine tail требует отдельного triage.

Это историческая baseline receipt, а не текущее состояние main. Counts нужно пересчитать после каждого исправления.

## Windows defects — точные acceptance criteria

### WIN-01 — uvloop platform marker

Источник истины: pyproject.toml содержит uvloop==0.22.1 с platform_system != 'Windows', но requirements.lock содержит uvloop==0.22.1 без marker.

Использовать scripts/lock_requirements.py и утверждённую версию uv, перегенерировать requirements.lock штатным способом. Проверить:
- Windows install из requirements.lock с require-hashes и only-binary проходит без uvloop;
- Linux runtime/dev install сохраняет uvloop;
- hashes и versions детерминированы;
- после генерации повторный lock diff пустой или документирован;
- package_smoke wheelhouse PASS на Windows и Linux.

### WIN-02 — ProactorEventLoop под pytest-socket

Существующий tests/conftest.py разрешает AF_UNIX, но Windows ProactorEventLoop может использовать AF_INET socketpair для внутренних каналов. pytest-socket --disable-socket блокирует этот системный канал.

Нельзя отключать сетевую изоляцию. Исправление должно отдельно доказать:
- Windows asyncio default loop создаётся и выполняется;
- async pytest fixtures не получают SocketBlockedError при setup;
- внешние неразрешённые TCP/UDP/DNS попытки остаются заблокированы;
- тесты для localhost allowlist работают без доступа в интернет;
- Linux test bootstrap не регрессирует.

Официальный Python reference: https://docs.python.org/3.13/library/asyncio-platforms.html  
pytest-socket reference: https://pypi.org/project/pytest-socket/

### WIN-03 — SQLite handle lifecycle

Временный каталог нельзя удалять, пока открыт SQLite connection/WAL/SHM handle. Точно локализовать handle в OCCDurableLibrary, host wrapper, journal или authority. Добавить явный close/context manager и test that deletion succeeds after close. Запрещено игнорировать WinError 32 или удалять каталог с retries до исчезновения файла.

### WIN-04 — genuine Windows test failures

После устранения event-loop fixture errors повторно запустить полный offline suite. Классифицировать остаток по актуальным traceback. В особенности не считать automatically resolved:
- GPR tests;
- MPR2602 provider/transport/raw-state;
- TON radar;
- synthetic path registry errors;
- test failures вне socket setup.

Каждый distinct root cause должен иметь reproducible test и отдельный backlog ID.

## Нужный native Windows receipt

Сохранять в gitignored или approved artifact location; не класть secrets, private endpoints, raw auth headers или user profile paths в Git.

Receipt должен содержать:
- commit SHA;
- OS caption/version/build/architecture;
- PowerShell version;
- Python exact version + architecture;
- uv/Git/core.autocrlf;
- install command и exit code;
- package_smoke stages;
- pip check;
- compileall;
- validate_authority_map;
- verify_repo stage summary;
- offline pytest passed/failed/errors/skipped + exact test IDs;
- SHA256 receipt и verifier output;
- explicit zero network/live actions.

## Рекомендуемый PowerShell inventory

~~~powershell
$ErrorActionPreference = "Stop"
Get-CimInstance Win32_OperatingSystem |
  Select-Object Caption, Version, BuildNumber, OSArchitecture
Get-ComputerInfo |
  Select-Object WindowsProductName, WindowsVersion, OsBuildNumber, OsArchitecture
$PSVersionTable
py -0p
python --version
uv --version
git --version
git config --get core.autocrlf
git rev-parse HEAD
git status --short
~~~

## Verification commands после фиксов

~~~powershell
..venvScriptspython.exe -m pip check
..venvScriptspython.exe -m compileall -q arb_bot.py src scripts tests
..venvScriptspython.exe scriptserify_repo.py --skip-dependency-audit
..venvScriptspython.exe -m pytest -m "not live and not manual" --disable-socket --allow-unix-socket -q
~~~

Если один stage не выполнен — receipt должен говорить NOT_RUN, а не PASS. Если падает — точный blocker, exit code и test IDs сохраняются.
