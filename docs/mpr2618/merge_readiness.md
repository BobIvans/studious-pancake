# Merge-readiness contract

MPR-2618 is mergeable as a default-off security primitive when repository CI is green on the final head and no newer MPR-2617 ref claims the same ownership.

A merge does **not** mean live credential rotation is authorized. External/provider/KMS/HSM rotation, real signer key migration, webhook dual-secret cutover, conformance invalidation and HA/restore propagation remain downstream qualification work.

If a MPR-2617 branch appears before merge and owns credential/trust rotation or compromise response, perform semantic collision review before merge and narrow this PR rather than merging two coequal authorities.
