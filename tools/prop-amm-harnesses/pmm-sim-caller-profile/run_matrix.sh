#!/usr/bin/env bash
# pmm-sim caller-profile matrix runner — LOCAL LiteSVM research only.
# No signing, no sending, no mainnet impersonation. Zero-outbound enforced by an
# unroutable --http-url (any implicit RPC fetch fails hard).
#
# Usage: bash run_matrix.sh <pmm-sim.exe> <snapshot-cfg-dir> <results-out-dir> [parallelism]
set -euo pipefail

SIM="$1"; SNAP="$2"; OUT="$3"; PAR="${4:-4}"
mkdir -p "$OUT"
SHA_BEFORE=$(sha256sum "$SNAP/cfg/setup.toml" | cut -d' ' -f1)

run_one() {
  local pmm="$1" suffix="$2" call_type="$3" spoof="$4" src="$5" dst="$6" amount="$7"
  local tag="${call_type}"
  local extra=()
  if [ "$call_type" = "cpi" ]; then
    if [ -n "$spoof" ] && [ "$spoof" != "-" ]; then tag="$spoof"; extra+=(--spoof="$spoof"); else tag="magnus"; fi
  fi
  RUST_LOG="${RUST_LOG:-info}" "$SIM" benchmark \
    --pmms="${pmm}_${suffix}" \
    --range="${amount},$((amount + 1)),1" \
    --src-token="$src" --dst-token="$dst" \
    --call-type="$call_type" "${extra[@]+"${extra[@]}"}" \
    --jit-accounts=false --jit-programs=false \
    --http-url="http://127.0.0.1:1" \
    --setup-path="$SNAP/cfg/setup.toml" \
    --programs-path="$SNAP/cfg/programs" \
    --accounts-path="$SNAP/cfg/accounts" \
    --datasets-path="$OUT" \
    >"$OUT/log_${tag}_${pmm}_${suffix}_${src}2${dst}_${amount}.log" 2>&1 \
    || echo "RUN_FAILED tag=$tag pmm=$pmm suffix=$suffix $src->$dst amount=$amount" >> "$OUT/failures.txt"
}
export -f run_one
export SIM SNAP OUT

JOBS=()
for variant in "humidifi FksffEqn DB3sUCP2 6n9VhCwQ AvGeFw71 5dhYayH9" \
               "humidifi-swap-v2 FksffEqn DB3sUCP2 6n9VhCwQ AvGeFw71 5dhYayH9" \
               "humidifi-swap-v3 FksffEqn DB3sUCP2 6n9VhCwQ AvGeFw71 5dhYayH9"; do
  set -- $variant; pmm="$1"; shift
  for suffix in "$@"; do
    if [ "$suffix" = "5dhYayH9" ]; then DIRS=("wsol usd1" "usd1 wsol"); else DIRS=("wsol usdc" "usdc wsol"); fi
    for ct_sp in "direct -" "cpi -" "cpi jupiter" "cpi dflow" "cpi okxlabs" "cpi titan"; do
      set -- $ct_sp; ct="$1"; sp="$2"
      for dir in "${DIRS[@]}"; do
        set -- $dir; src="$1"; dst="$2"
        for amount in 1 5 10 25 50 100 250 500 1000 2000 4000 8000 16000 32000 64000; do
          JOBS+=("$pmm $suffix $ct $sp $src $dst $amount")
        done
      done
    done
  done
done

printf '%s\n' "${JOBS[@]}" | xargs -P "$PAR" -n 7 bash -c 'run_one "$@"' _
SHA_AFTER=$(sha256sum "$SNAP/cfg/setup.toml" | cut -d' ' -f1)
[ "$SHA_BEFORE" = "$SHA_AFTER" ] || { echo "FATAL: setup.toml mutated during run"; exit 1; }
echo "matrix run complete; results in $OUT; failures (if any) in $OUT/failures.txt"
