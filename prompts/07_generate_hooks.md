---
name: generate_hooks
version: 1
tier: strong
description: Write original hooks that use the mechanism without copying the source wording
---

Write {{hooks_per_pattern}} original hooks for this product using this mechanism.

THE MECHANISM
{{pattern}}

THE BRIDGE TO THE PRODUCT
{{adaptation}}

THE PRODUCT
{{product}}

THE AUDIENCE
{{audience}}

SOURCE HOOKS THAT USED THIS MECHANISM. DO NOT COPY THEM.
These are here so you can see the mechanism working and then write something else.
Reusing their phrasing gets the hook rejected automatically by a similarity check.
{{source_hooks}}

WHAT HAS ALREADY WORKED FOR US
{{winners}}

WHAT HAS ALREADY FAILED FOR US
{{losers}}

RULES
- Write for {{market_country}} social media. The slang, the rhythm and the references
  must sound native. Nothing that only lands somewhere else.
- Each hook is the first line of a video. Short. Spoken out loud, not written down.
- Make each of the five genuinely different. Five rewrites of one idea is one hook.
- first_3_second_action must be something a person can film. Not a mood.
- Never claim guaranteed outcomes, fluency timelines, or anything in {{forbidden_claims}}.
- Never use the phrase "will go viral" or promise performance.
- Specific beats clever. "You understand every word and still freeze" beats
  "Unlock your English potential".

```json schema
{
  "type": "object",
  "required": ["hooks"],
  "properties": {
    "hooks": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["hook", "first_frame_visual", "first_3_second_action", "spoken_dialogue", "on_screen_text", "creative_mechanism", "product_reveal", "payoff", "cta"],
        "properties": {
          "hook": {"type": "string"},
          "first_frame_visual": {"type": "string"},
          "first_3_second_action": {"type": "string"},
          "spoken_dialogue": {"type": "string"},
          "on_screen_text": {"type": "string"},
          "creative_mechanism": {"type": "string"},
          "product_reveal": {"type": "string"},
          "payoff": {"type": "string"},
          "cta": {"type": "string"}
        }
      }
    }
  }
}
```
