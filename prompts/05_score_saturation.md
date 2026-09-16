---
name: score_saturation
version: 1
tier: cheap
description: Judge the three repetition signals that cannot be counted mechanically
---

Numeric saturation signals (how many creators, how many brands, how old) are counted in
Python. Three signals need judgement instead of counting, and that is all you do here.

Return each as a number from 0.0 to 1.0, where 0.0 means every example is distinct and
1.0 means they are effectively the same execution repeated.

exact_wording_repetition  how much the opening LINES repeat across these examples
visual_repetition         how much the visual setup and framing repeat
audio_repetition          how much the same sound, song or audio device repeats

EXAMPLES USING THIS PATTERN
{{examples}}

Judge only what you can see. If there is one example, repetition is 0.0 by definition.

```json schema
{
  "type": "object",
  "required": ["exact_wording_repetition", "visual_repetition", "audio_repetition"],
  "properties": {
    "exact_wording_repetition": {"type": "number"},
    "visual_repetition": {"type": "number"},
    "audio_repetition": {"type": "number"},
    "notes": {"type": "string"}
  }
}
```
