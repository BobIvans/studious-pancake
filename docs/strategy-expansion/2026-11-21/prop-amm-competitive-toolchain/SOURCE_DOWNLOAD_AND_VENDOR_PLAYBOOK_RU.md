# Загрузка исходников, third-party mirror и изоляция зависимостей

## Задача

Собрать исходный код подтверждённых open-source инструментов внутри репозитория для воспроизводимой сборки и тестов. Не смешивать vendored research sources с production runtime. Сервисы LocalShred, DoubleZero, OrbitFlare, Triton, Helius, GetBlock, Astralane, Syncro, Sanctum, BoltTx, Nozomi и Jupiter API не являются open-source репозиториями, которые можно клонировать целиком: для них сохраняются только официальный API/terms reference и mocked adapter contract.

Полный pin/license/state registry находится в VENDORED_SOURCE_MANIFEST_V1.json.

## Куда размещать

- vendor/strategy-research/<source-name>/ — upstream snapshot без вложенного .git.
- vendor/strategy-research/<source-name>/provenance.json — repository URL, commit SHA, release/tag, archive SHA-256, license SPDX, license SHA-256, retrieval date, Cargo.lock digest, local patch list.
- vendor/strategy-research/<source-name>/LICENSE* / NOTICE — исходные license notices.
- tools/prop-amm-harnesses/<harness>/ — отдельный build/test wrapper с отдельным Cargo.toml и Cargo.lock.
- docs/third_party/prop_amm_sources/ — generated source register, not code copies.

Не добавлять эти workspaces в корневой Cargo workspace или production Python package без отдельного adapter review.

## Команды безопасного mirror

Для каждого источника со статусом MIRROR_CANDIDATE / DEV_TEST_HARNESS_CANDIDATE:

~~~bash
set -euo pipefail
REPO_URL="https://github.com/OWNER/REPO.git"
PIN="<40-hex-commit-from-VENDORED_SOURCE_MANIFEST_V1.json>"
NAME="<repo-name>"
TMP="$(mktemp -d)"
DEST="vendor/strategy-research/$NAME"

git clone --filter=blob:none --no-checkout "$REPO_URL" "$TMP/repo"
git -C "$TMP/repo" checkout --detach "$PIN"
test "$(git -C "$TMP/repo" rev-parse HEAD)" = "$PIN"

mkdir -p "$DEST"
git -C "$TMP/repo" archive --format=tar "$PIN" | tar -xf - -C "$DEST"
git -C "$TMP/repo" show "$PIN:LICENSE" > "$DEST/LICENSE" 2>/dev/null || true
~~~

Перед повтором команды проверьте, что DEST не содержит незарегистрированных пользовательских изменений. Не перезаписывайте каталог молча. Для репозитория, где лицензионный файл имеет другое имя, сохраните оригинальный файл; не генерируйте поддельный LICENSE. Для pmm-sim отдельно включите его Cargo.lock и примените локальный patch branch -> pinned revision для Magnus только в snapshot/harness.

После архивации:
1. Проверить отсутствие .git и submodule gaps.
2. Проверить все symlink/path entries на выход за DEST.
3. Вычислить sha256sum archive.tar, sha256sum LICENSE*, git rev-parse HEAD.
4. Сохранить LICENSE/NOTICE без изменения текста.
5. Проверить все Cargo.toml, Cargo.lock, git dependencies, build scripts, proc macros и binary targets.
6. cargo metadata --locked, затем cargo test --locked, cargo build --release --locked, cargo clippy --locked --all-targets -- -D warnings в отдельной изолированной папке.
7. Записать stdout/stderr, toolchain version, OS, CPU, dependency graph and test counts.

Не запускать неизвестные install.sh, Makefile, postinstall/build.rs или network scripts до code review. Не запускать mainnet/live loop и не использовать .env из upstream.

## Обязательная изоляция версий

Из проверенных manifest-ов видно, что инструменты не имеют единого совместимого Solana SDK:
- sol-parser-sdk v0.11.0: Rust 2021, Solana SDK 4.0.1 / Client 4.2.2, Yellowstone 13.5.
- pmm-sim v0.2.0: Rust 2024, Solana SDK 3.0, LiteSVM 0.10, Magnus git dependency. Его Cargo.lock pin-ит Magnus revision 9ecd34b634031f5dfdf5747c33a329605ea6e7c4; Cargo.toml при этом использует mutable branch extend-router-ixs. Vendor patch должен заменить только этот branch selector на immutable rev, сохранив исходный lockfile и patch diff.
- 1000xsh/swaps v0.1.1: Rust 2024, solana-address ^2.6; root license file в этом sweep не найден, несмотря на license = MIT в Cargo.toml. Не копировать в репозиторий, пока cargo package / published crate archive не подтверждает пакетные license notices и checksum.
- ValidatorsDAO/solana-stream: Apache-2.0; current upstream README требует проверить поддержку Transaction v1 и Alpenglow wire format. Это отдельная современная зависимость, не автоматически совместимая с Yellowstone SDK v13.5 из sol-parser-sdk.
- Mollusk и Pinocchio — отдельные developer/program workspaces, не добавлять в runtime.
- Jito ShredStream Proxy — historical reference, не активный feed после sunset.

Не разрешается насильно сводить эти разные SDK к одной версии. Использовать отдельные harness crates и только небольшой reviewed adapter boundary к текущему Python 3.13 runtime. Предпочтение — уже существующий composition root / plugin boundary. Новый sidecar допускается лишь после benchmark, backpressure/health tests и MPR-05 packaging review; не создавать дополнительный постоянно работающий detector/transport daemon.

## Что загружать и что нет

- Mirror candidates: sol-parser-sdk, pmm-sim, ValidatorsDAO/solana-stream, solana-arb-executor (skill/reference), Mollusk (dev), Pinocchio (только program reference), Jito proxy (historical reference).
- Hold: 1000xsh/swaps — подтвердить license archive; только после этого source mirror + venue conformance.
- API-only: Jupiter V2, all feed and relay vendors.
- Не загружать/не запускать: unverified Python live-loop framework; no-license educational framework until terms verified; sol-trade-sdk / sol-trade-router-sdk because they add a separate signing/submission surface; KADES/CADES/Capture OS without canonical repository/API; any paid provider binary or hidden client not explicitly published by vendor.

## Результат загрузки

Agent должен создать vendor/strategy-research/INDEX.md, каждый provenance.json, THIRD_PARTY_NOTICES.md, deterministic harnesses, checksums, build/test reports and source-level blockers. Presence of source code does not imply runtime capability.
