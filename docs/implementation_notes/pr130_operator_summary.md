# PR-130 operator summary

For the first Jito live path, use only the single-transaction Jito transport.
Do not send a multi-transaction bundle. Do not put the Jito tip in a separate
transaction. Do not treat Jito bundle acknowledgement or status as economic
settlement.

The canonical sender manifest now records the PR-130 policy so review tooling can
see whether the chosen transport shape is compatible with the first-production
policy.
