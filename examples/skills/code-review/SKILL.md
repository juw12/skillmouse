---
name: code-review
description: Defect-first review of a code snippet or diff - bugs, edge cases, then style.
---

# Code review

Review the input code. Report findings ordered by severity:

1. **[P1]** bugs, crashes, security problems
2. **[P2]** edge cases and wrong behaviour
3. **[P3]** readability and naming

For each finding give the line, the problem, and a concrete fix. End with a corrected version
of the code if anything above P3 was found. Be brief; no praise.
