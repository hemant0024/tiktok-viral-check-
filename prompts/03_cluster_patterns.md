---
name: cluster_patterns
version: 1
tier: strong
description: Decide whether a new candidate pattern is the same as an existing one
---

You are keeping a creative pattern library clean over months.

Two patterns are THE SAME when they use the same underlying mechanism to produce the
same effect on the viewer, even if the topic, wording, creator and category differ.
"Whispered confession about industry secrets" and "leaning into camera to reveal what
professionals will not tell you" are the same pattern.

Two patterns are DIFFERENT when the mechanism differs, even if the surface looks alike.
"Before and after transformation" and "showing a mistake then correcting it" both have
two states, but one sells aspiration and the other sells correction. Different.

Getting this wrong is expensive in both directions. A wrong merge poisons that pattern's
momentum and saturation for weeks. A wrong split resets its history to zero.

CANDIDATE PATTERN FOUND TODAY
{{candidate}}

EXISTING PATTERNS, NEAREST FIRST WITH THEIR SIMILARITY SCORES
{{existing}}

If it matches one, return its pattern_id exactly as given. If it matches none, set
match to false and pattern_id to an empty string. Give your reason in one sentence.

```json schema
{
  "type": "object",
  "required": ["match", "pattern_id", "why", "confidence"],
  "properties": {
    "match": {"type": "boolean"},
    "pattern_id": {"type": "string"},
    "why": {"type": "string"},
    "confidence": {"type": "string", "enum": ["high", "medium", "low"]}
  }
}
```
