---
name: adapt_to_product
version: 1
tier: strong
description: Work out how a creative mechanism maps onto this product, before writing any hooks
---

Before anyone writes a hook, work out whether this mechanism even fits the product,
and if so, what the honest bridge is.

THE MECHANISM
{{pattern}}

THE PRODUCT
{{product}}

THE AUDIENCE
{{audience}}

Answer three things.

1. The bridge. What real thing about this product lets this mechanism land honestly?
   If the mechanism is "insider secret", what does the product actually know that the
   audience does not? Name the real insight, not a marketing line.

2. The tension. What does the audience believe that the product contradicts? The best
   version of this mechanism sits on that contradiction.

3. Fit. Score product_applicability 0 to 100 and say plainly if this is a stretch.
   A low score here is useful. It stops the team producing something that will not work.

RULES
- Do not write hooks. That is the next step.
- Do not invent product capabilities. Work only from what you were given.
- If the mechanism does not fit, say so and score it low. Do not force it.

```json schema
{
  "type": "object",
  "required": ["bridge", "tension", "product_applicability", "audience_relevance", "angle", "is_stretch"],
  "properties": {
    "bridge": {"type": "string"},
    "tension": {"type": "string"},
    "angle": {"type": "string"},
    "product_applicability": {"type": "number"},
    "audience_relevance": {"type": "number"},
    "is_stretch": {"type": "boolean"},
    "why": {"type": "string"}
  }
}
```
