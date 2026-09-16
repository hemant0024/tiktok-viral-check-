---
name: detect_trends
version: 1
tier: cheap
description: Write the "why it matters" line for a pattern whose numbers are already computed
---

The scores below were computed in Python. Do not recalculate them, do not argue with
them, and do not invent new numbers. Your only job is the sentence a busy creative
director reads at 9am.

PATTERN
{{pattern}}

COMPUTED SCORES
Momentum: {{momentum_score}} of 100
Saturation: {{saturation_score}} of 100
Cross category: appears in {{distinct_categories}} categories
Opportunity: {{opportunity_score}} of 100
Lifecycle: {{lifecycle_label}}
Growth: {{velocity_views_per_day}} views per day ({{velocity_confidence}} confidence)
Breakout: {{is_breakout}}
Based on {{content_count}} pieces of content from {{distinct_creators}} creators

RULES
- One or two sentences. Plain words. No hype.
- Say what changed and why the team should care today specifically.
- If confidence is low, say the signal is early rather than overstating it.
- Never predict virality. Never say "will go viral" or anything close to it.
- If saturation is high, say so plainly. The team needs to know when to skip something.

```json schema
{
  "type": "object",
  "required": ["why_it_matters"],
  "properties": {
    "why_it_matters": {"type": "string"},
    "watch_out_for": {"type": "string"}
  }
}
```
