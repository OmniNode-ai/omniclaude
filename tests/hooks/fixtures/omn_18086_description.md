## Finding

Discovered during OMN-18054 probe (2026-09-09).

`DELETE /v1/tenants/me/inference-credentials/{ref}` returns HTTP 200 and sets `revoked_at` in the `tenant_inference_credentials` projection. However, the Infisical store entry for the credential is not deleted by this operation.

`resolve_tenant_scoped_api_key_async` reads from the Infisical store directly and does not consult `revoked_at` from the projection. As a result, a revoked credential continues to resolve at the effect boundary.

Observed: credential resolved on 61 consecutive attempts over 302.6 seconds after the product surface confirmed revocation.

## Acceptance Criteria

AC1: The revoke route (`revoke_inference_credential`) deletes the Infisical store entry before publishing the credential-revoked event. A failed delete returns a typed 5xx with no event and no `revoked_at` write. Implemented in omnimarket PR #2504 per ruling b817d8b7.

AC2: An OMN-18054-shape probe run against dev after PR #2504 merges confirms the Infisical store entry is gone within one revoke round-trip.

## References

* OMN-18054 (probe that surfaced this gap)
* OMN-17092 (Infisical adapter delete_secret — may be relevant)
* OMN-16944 (carrier that introduced tenant-credential namespace resolution)

## Carrier pull requests (full URLs, for evidence resolution)

* <pull-request id="1f5da229-5717-4889-ac80-74d560111e8b" href="https://linear.app/omninode/review/featomn-18086-delete-infisical-entry-before-publishing-credential-b0579a92bee7">OmniNode-ai/omnimarket#2504</pull-request> — merged 2026-09-15T05:07:21Z, merge commit `75d942d9509ee13cdb94126519925caafab089b4`. Sequences the store delete ahead of the publish (AC1).
* <pull-request id="db57d1c7-0aa5-43a5-b99a-06ca67eddfc3" href="https://linear.app/omninode/review/fixomn-18054-pass-allow-deletetrue-to-infisicalsecretstore-in-revoke-89465a1a8ba9">OmniNode-ai/omnimarket#2567</pull-request> — merged 2026-09-15T17:08:06Z, merge commit `3038d1dabadea4973707f0228862b4aef4e09242`. Supplies the flag the delete needed to take effect.
* <pull-request id="8e7665f3-0ee4-4a8e-ae5a-c8040f62cbf5" href="https://linear.app/omninode/review/featomn-18086-add-delete-secret-to-adapterinfisical-and-8b8974674289">OmniNode-ai/omnibase_infra#3468</pull-request> — merged, merge commit `e6eb385666bca88d9b74565a44ba4ba73d0814fc`. Adds the store delete capability.
* <pull-request id="12dff8ca-d7d3-4df1-a446-d9f44370105e" href="https://linear.app/omninode/review/chore-release-v03824-omn-18086-48779748a9a9">OmniNode-ai/omnibase_infra#3472</pull-request> — merged 2026-09-13T09:27:47Z, merge commit `ce797b54f187d81860896e9a17eb1b34a57422a0`. Releases it as v0.38.24.

`omnibase_infra#3517` is **not** a carrier. It was a retry of the v0.38.24 release that was closed without merging once `#3472` had already carried that release. It remains attached to this ticket as history only, and it is the reason the done-flip evidence gate currently refuses this ticket. Acceptance does not rest on it.
