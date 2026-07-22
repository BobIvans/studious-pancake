# PR-152 exact sender-free paper attempt

PR-152 composes existing production-hardening boundaries into one reviewable
paper attempt:

1. Verify rooted, unexpired Jupiter and MarginFi execution evidence.
2. Reserve native capital durably before building the candidate.
3. Bind the durable reservation into the atomic planner request.
4. Run the existing planner, canonical v0 compilation, exact simulation and
   economic reconciliation vertical.
5. Confirm final Jupiter and MarginFi provenance pins.
6. Revalidate the durable reservation with the exact fee of the final immutable
   message.
7. Release the reservation on every fail-closed pre-submission outcome.

The result records one provider evidence hash, durable attempt ID, final message
hash, planner digest and reconciliation hash. It always reports
`sender_imported=false` and `submission_allowed=false`.

## Production debt closed

This closes the orchestration gap between the already implemented durable capital
coordinator, atomic MarginFi/Jupiter vertical and exact fee workflow. It does not
claim that Jupiter or MarginFi external promotion evidence is complete; those
contracts remain independently gated.

## Safety

- No private key or signer import.
- No RPC/Jito sender import.
- No transaction submission.
- No live-mode enablement.
- Provider evidence must be rooted, fresh and explicitly execution-allowed.
- The account snapshot hash must be bound into exact simulation evidence.
- Final provider pins must match the pins admitted before reservation.
- Fee growth beyond the durable reservation releases the attempt before any send.
