---
name: sanity
description: Sanity-check after forming a plan or finishing a code change. Invoke on /sanity, "sanity check", "am i missing anything", "did i miss a step", "anything i forgot", "second opinion". Use proactively after any plan is agreed or any change is staged — even if the user doesn't ask.
---

Review the current plan or recent changes in context. Run `git diff HEAD` if useful. Analyse what is missing, risky, or forgotten — then tell the user what you found. Be direct and specific. Only ask the user a question if you genuinely need a piece of information to complete the assessment that you cannot infer from context.
