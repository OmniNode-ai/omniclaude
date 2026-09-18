## Problem

OMN-17488 scope 2 asks us to distinguish genuine delegation degradation from
expected probe/synthetic traffic. The chain canary already sets an explicit
provenance marker at ingress, but that marker is discarded before any durable
terminal surface.

## Acceptance criteria

**AC4** — the attribution query can classify canary vs non-canary rows without
prompt-template matching.

No code has been changed for this issue.

https://github.com/OmniNode-ai/omnibase_infra/pull/3615
https://github.com/OmniNode-ai/omnibase_infra/pull/3626
https://github.com/OmniNode-ai/omnibase_infra/pull/3627
https://github.com/OmniNode-ai/onex_change_control/pull/9974
