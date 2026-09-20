# AGG-14 upstream research observations

Observed on 2026-09-20 for the default-off AGG-14 research boundary. These are
source-review inputs, not deployment qualification or permission to copy code.

## Kora

- Repository: \`solana-foundation/kora\`
- Observed \`main\`: \`fd90de2dccc722b95d3dc3e6bc2845d6702f0c12\`
- Observed tree: \`87a6f91a1ccf227f71828adc5de8dff0f649e69d\`
- \`LICENSE.md\` blob: \`ad9016a97e1bb7a0fa83cafc235727ef3bcaa128\` (MIT)
- README blob observed: \`9854ecb48edfb6d0f93940cc64e381aa14f6590d\`
- Audit status blob observed: \`901d36118d9269dc6c7ab6ebed27647cb61ec8ce\`
- Audit status names audited-through commit
  \`8c592591debd08424a65cc471ce0403578fd5d5d\`; current \`main\` is therefore not
  treated as an audited production pin by AGG-14.

Kora's README describes signing/paymaster infrastructure. AGG-14 deliberately
**does not import or start it**. \`PaymasterCapability\` requires separately supplied
external verification and funded sponsor evidence before a sponsored plan can be
approved, and even an approved plan cannot sign or submit.

## BlockScan

- Repository: \`nuwuxian/BlockScan\`
- Observed \`main\`: \`4556cd209c968ed60e8d15b245f8d53e3f725534\`
- README blob observed: \`7fa4776c47e1202ef3e6802d6f3b60afef0c7f6a\`
- GitHub repository metadata did not report a license and a root \`LICENSE\` lookup
  was not found during this review.

Accordingly no BlockScan code or model artifact is copied by AGG-14. It remains a
research lead and can only become a \`DefensiveToolBenchmark\` after source/data
rights and a local authorized benchmark are established.

## River

- Repository: \`online-ml/river\`
- Observed \`main\`: \`8f516e096520c35eabee9c08110c524518e4d3b5\`
- Observed license: BSD-3-Clause, license blob
  \`c3a351f973d0b1b38eadc6ae72917bfc5ce24f8e\`.

No River code is imported in this PR. If later selected for a measured online-ML
experiment, the exact commit/file dependency closure and dataset/holdout evidence
must be pinned in the research library first.
