---
name: generate_daily_report
version: 1
tier: strong
description: Write the concise daily message a creative team reads on a phone
---

Write today's DAILY CREATIVE RADAR message.

The reader is a creative director with a coffee and about forty seconds. They need one
thing from this: what should I make today, and why that.

TODAY
{{date}}

TOP CONCEPTS, ALREADY RANKED AND SCORED
{{concepts}}

WHAT FAILED IN TODAY'S RUN
{{failures}}

RULES
- One block per concept. Each block must fit on one phone screen.
- Lead with the mechanism, not the metric. Numbers support the idea, they do not open it.
- Include the hook in quotes and the cat execution in one line.
- Use the opportunity label you were given. Never invent your own verdict.
- Never predict virality. Never write "will go viral", "guaranteed", or "this will blow up".
- If a source failed, add one honest line at the end saying what the report is missing.
- No preamble, no sign off, no emoji beyond the section markers already in the format.

FORMAT, follow it exactly

DAILY CREATIVE RADAR
{{date}}

#1 <MECHANISM NAME IN CAPS>

Opportunity: <score> | Momentum: <score> | Saturation: <Low/Medium/High>
Cross-category: <n>

Mechanism:
<one line>

Hook:
"<the hook>"

Cat execution:
<one line>

<opportunity label> - <one line on why today>

(repeat for each concept)

```json schema
{
  "type": "object",
  "required": ["message"],
  "properties": {
    "message": {"type": "string"},
    "headline": {"type": "string"}
  }
}
```
