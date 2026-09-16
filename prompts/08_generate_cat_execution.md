---
name: generate_cat_execution
version: 1
tier: strong
description: Make the cat part of the mechanism rather than a sticker on top of it
---

Give this hook a cat execution.

THE HOOK
{{hook}}

THE MECHANISM
{{mechanism}}

THE MASCOT
{{mascot}}

THE ROLE YOU MUST USE FOR THIS ONE
{{cat_role}}

THE VISUAL TREATMENT YOU MUST USE
{{visual_treatment}}

THE TEST THIS MUST PASS
If you could delete the cat and the idea still works exactly the same, you have failed.
The cat has to be doing the mechanism, not standing next to it.

Bad: a cat sits in the corner while a voiceover explains the app.
Good: the cat is the one who cannot pronounce the word, so the embarrassment the
audience feels is happening on screen to someone else, which is why they keep watching.

Write cat_execution as a director would describe a shot. Concrete. Filmable.
Then answer the deletion test honestly in mechanism_dependency.

```json schema
{
  "type": "object",
  "required": ["cat_execution", "cat_role", "visual_treatment", "mechanism_dependency", "passes_deletion_test"],
  "properties": {
    "cat_execution": {"type": "string"},
    "cat_role": {"type": "string"},
    "visual_treatment": {"type": "string"},
    "mechanism_dependency": {"type": "string"},
    "passes_deletion_test": {"type": "boolean"}
  }
}
```
