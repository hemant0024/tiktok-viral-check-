---
name: score_hooks
version: 1
tier: cheap
description: Score one hook on the seven components, and say what is wrong with it
---

Score this hook honestly. A generous score that gets a bad ad produced costs the team
a shoot day. Be the person who says the awkward thing before the camera comes out.

THE HOOK
{{hook}}

THE PRODUCT
{{product}}

THE AUDIENCE
{{audience}}

SATURATION OF THE PARENT PATTERN: {{saturation_score}} of 100

Score each component 0 to 100.

attention_potential   would a thumb actually stop
curiosity             does it open a loop the viewer needs closed
novelty               have we all seen this exact move already
product_relevance     does the product belong here or is it bolted on
audience_relevance    does this speak to someone who freezes when they try to speak
visual_potential      is there something worth watching, not just something to hear
production_simplicity could a small team film this next week

Then give strengths, weaknesses, the real risk, and the one test worth running.
weaknesses must not be empty. Every hook has one.

```json schema
{
  "type": "object",
  "required": ["attention_potential", "curiosity", "novelty", "product_relevance", "audience_relevance", "visual_potential", "production_simplicity", "strengths", "weaknesses", "risk", "recommended_test"],
  "properties": {
    "attention_potential": {"type": "number"},
    "curiosity": {"type": "number"},
    "novelty": {"type": "number"},
    "product_relevance": {"type": "number"},
    "audience_relevance": {"type": "number"},
    "visual_potential": {"type": "number"},
    "production_simplicity": {"type": "number"},
    "strengths": {"type": "string"},
    "weaknesses": {"type": "string"},
    "risk": {"type": "string"},
    "recommended_test": {"type": "string"}
  }
}
```
