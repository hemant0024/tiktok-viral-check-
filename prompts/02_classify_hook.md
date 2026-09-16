---
name: classify_hook
version: 1
tier: cheap
description: Pull the hook apart into its component parts
---

Extract the hook from this piece of content and break it into parts.

The hook is the first three seconds. Everything after that is the video, not the hook.

Allowed hook types, multiple allowed, use these exact strings:
Curiosity, Confession, Shock, POV, Reaction, Challenge, Transformation, Comparison,
Contrarian, Problem, Demonstration, Story, Humor, Social Proof, Pattern Interrupt,
Before/After, Question, Mistake, Secret, Controversy

CONTENT
Title / caption: {{title}}
Description: {{description}}
Transcript or captions: {{transcript}}
Observed visual notes: {{visual_notes}}
Duration: {{duration_seconds}} seconds
Hashtags: {{hashtags}}

RULES
- original_hook is the actual opening line, quoted as closely as the evidence allows.
- If you only have metadata and no transcript, say so: set evidence to "metadata_only"
  and keep visual_hook and on_screen_text short and clearly inferred.
- Never invent a spoken line you cannot see evidence for. An empty string beats a guess.
- cta is what the video asks the viewer to do, empty string if it asks nothing.

```json schema
{
  "type": "object",
  "required": ["original_hook", "first_3_second_description", "hook_type", "emotional_trigger", "curiosity_mechanism", "problem", "payoff", "evidence"],
  "properties": {
    "original_hook": {"type": "string"},
    "first_3_second_description": {"type": "string"},
    "visual_hook": {"type": "string"},
    "spoken_hook": {"type": "string"},
    "on_screen_text": {"type": "string"},
    "hook_type": {"type": "array", "items": {"type": "string"}},
    "creative_format": {"type": "string"},
    "emotional_trigger": {"type": "string"},
    "curiosity_mechanism": {"type": "string"},
    "problem": {"type": "string"},
    "payoff": {"type": "string"},
    "cta": {"type": "string"},
    "target_audience": {"type": "string"},
    "product_category": {"type": "string"},
    "evidence": {"type": "string", "enum": ["full_transcript", "captions", "metadata_only"]}
  }
}
```
