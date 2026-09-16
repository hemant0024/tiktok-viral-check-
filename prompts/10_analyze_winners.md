---
name: analyze_winners
version: 1
tier: strong
description: Extract the reusable DNA from an ad that actually performed
---

This ad won. Work out what won, so it can be used again.

"winner = true" is not an insight. The insight is the combination that produced it.

THE CREATIVE
{{creative}}

THE PERFORMANCE
{{performance}}

HOW OTHER CREATIVES PERFORMED IN THE SAME PERIOD
{{baseline}}

Extract the parts, then state the reusable pattern as a formula the team can apply to a
different hook tomorrow. For example:
"Reaction + Embarrassment + English pronunciation + Cat reaction"

Be careful about what you attribute. If this creative ran with far more spend than the
others, say so in caveat rather than crediting the creative for the budget.

```json schema
{
  "type": "object",
  "required": ["winning_hook_type", "winning_emotion", "winning_visual", "winning_structure", "winning_problem", "winning_payoff", "winning_cta", "winning_audience", "reusable_pattern"],
  "properties": {
    "winning_hook_type": {"type": "array", "items": {"type": "string"}},
    "winning_emotion": {"type": "string"},
    "winning_visual": {"type": "string"},
    "winning_structure": {"type": "string"},
    "winning_problem": {"type": "string"},
    "winning_payoff": {"type": "string"},
    "winning_cta": {"type": "string"},
    "winning_audience": {"type": "string"},
    "reusable_pattern": {"type": "string"},
    "caveat": {"type": "string"}
  }
}
```
