# Failure, retry, ambiguity, deadline, and cancellation contract

`src.errors` is the sole semantic owner. Public reason codes are registry values, never exception names or text. Expected decisions use `Result`; ambiguity and cancellation cannot be flattened into failure or success. `ErrorEnvelope` admits registry-approved safe context only and never serializes an internal exception.

Unknown codes fail closed. Exception causes remain process-local. Only allowlisted supervision may catch `Exception`; cancellation is re-raised. Submission stays disabled: uncertain non-idempotent effects require reconciliation and quarantine.

Reason codes are retained while referenced by producers, consumers, durable rows, fixtures, evidence, CI, or operator documentation. Retirement requires a replacement and explicit compatibility decision.
