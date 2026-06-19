---
name: vault-discovery
description: >
  Interrogate TS_Obsidian_Vault research-ideas and concepts, cross-reference against
  RESEARCH_MEMORY.md and SYSTEM_STATE.md, and produce a prioritized discovery report.
  Read-only; no files written anywhere. Three modes: --quick (list only, ~30s),
  --themed (default, cross-referenced against current focus), --deep (full
  contradiction + gap analysis). Triggers on "what's in the vault", "vault discovery",
  "check vault ideas", "any vault ideas worth testing", /vault-discovery.
---

# Skill: /vault-discovery

Interrogate the TS_Obsidian_Vault and produce a prioritized discovery report of research
opportunities, gaps, and contradictions relevant to current Trade_Scan research themes.

Read-only. No directives created. No vault files written. Output to terminal only.

## Invocation

```
/vault-discovery [--quick | --themed | --deep]
```

Default: `--themed`

## Modes

**--quick**
List all vault research-ideas with `status: developing`. One line each.
Useful as a session-start check (~30 seconds). No cross-referencing.

**--themed** (default)
Cross-reference developing vault research-ideas against current Trade_Scan research focus
(`SYSTEM_STATE.md` + `RESEARCH_MEMORY.md`). Tier the ideas by actionability. Flag
contradictions and archivable ideas. Recommended for regular discovery sessions.

**--deep**
Full pass: everything in `--themed` plus:
- Read all `vault/concepts/` and check each claim against RESEARCH_MEMORY settled decisions
- Read vault `index.md` + `log.md` for recently ingested material not yet cross-referenced
- Identify gaps: instruments or strategy types mentioned in vault but absent from RESEARCH_MEMORY

---

## What to read

### From vault (path: `../TS_Obsidian_Vault/`)

| File/path | What to extract |
|---|---|
| `research-ideas/*.md` | frontmatter: `status`, `hypothesis`, `instrument`, `timeframe`, `source`; body: how-to-test, how-to-falsify |
| `concepts/*.md` | concept name, definition summary, sources cited, related concepts |
| `index.md` | quick scan for recently added entries (sources, concepts, research ideas) |
| `log.md` | last 5–10 entries — what was recently ingested |

Only read files with `status: developing` in research-ideas frontmatter. Ignore `status: archived`.

### From Trade_Scan (current repo)

| File | What to extract |
|---|---|
| `RESEARCH_MEMORY.md` | all settled/FROZEN decisions, rejected approaches, open arcs |
| `SYSTEM_STATE.md` | current research focus, active basket, open questions |

Read these **first**. They define what is "currently relevant" and what is "already answered."

---

## Output format

Print to terminal. No files written.

```
## Vault Discovery Report — [YYYY-MM-DD]

### Context: current Trade_Scan focus
[2–3 sentences from SYSTEM_STATE: what is being researched right now]

---

### Tier 1 — Test these now
Ideas that: (a) fit existing Trade_Scan infrastructure, and (b) address an open arc in
RESEARCH_MEMORY or SYSTEM_STATE, and (c) are not already answered by a settled decision.

For each:
- Hypothesis (from vault)
- Why it's Tier 1: what open arc it addresses
- How to test: sketch of directive approach (1–3 lines, not a full spec)
- Source: [[vault-page]]

---

### Tier 2 — Interesting but not yet
Ideas that are relevant to Trade_Scan themes but require infrastructure work, instrument
availability, or further vault development before they can be tested.

For each:
- Hypothesis
- What's blocking it
- What would make it Tier 1

---

### Tier 3 — Noted
Ideas with merit but too distant from current research focus, or based on thin evidence.
Listed without elaboration — just names and one-line summaries.

---

### Contradictions
Vault concept claims that conflict with RESEARCH_MEMORY settled decisions.

For each:
- Vault claim: [concept page, specific claim]
- RESEARCH_MEMORY decision: [the settled finding that contradicts it]
- Recommended action: [update vault concept | re-open RESEARCH_MEMORY arc | investigate gap]
NOTE: Do not resolve contradictions here. Surface them for human decision.

---

### Archive candidates
Vault research-ideas with status: developing that RESEARCH_MEMORY has already answered.
These should be archived in the vault with an outcome link.

For each:
- Vault idea: [[research-idea-slug]]
- Already answered by: [RESEARCH_MEMORY entry or source]
- Suggested outcome note: [one-line summary of what was found]
NOTE: Do not edit vault files. Report only — human updates the vault.

---

### Gaps (--deep only)
Things the vault references that Trade_Scan has not investigated:
- Instruments mentioned in vault ideas not present in RESEARCH_MEMORY
- Strategy types (ORB, trend filter types) with no Trade_Scan equivalent
- Vault concepts with no corresponding backtest evidence in RESEARCH_MEMORY

---

### Recently ingested (--deep only)
Sources added to vault since last discovery run (from log.md). Flag any that generated
research-ideas not yet cross-referenced against RESEARCH_MEMORY.
```

---

## Behavior rules

**Read-only, always.**
Do not create directives. Do not write to vault files. Do not update research-idea status.
Do not add entries to RESEARCH_MEMORY. Discovery output is advisory; all follow-up is
human-decided.

**Vault is subordinate to canonical.**
If a vault concept and RESEARCH_MEMORY disagree, RESEARCH_MEMORY is authoritative. The vault
is an orientation layer (Invariant #31). A contradiction means the vault may be wrong or
stale — not that RESEARCH_MEMORY should be re-opened based on vault content alone.

**Honest tiering.**
An idea is Tier 1 only if it genuinely fits current infrastructure and addresses a real open
arc. Do not promote ideas to Tier 1 just to populate the section. An empty Tier 1 is a valid
and useful result — it means the vault has nothing directly actionable right now.

**Honest gap detection.**
Gaps are only worth flagging if they are real research gaps, not just "the vault mentioned
something Trade_Scan hasn't formally documented." Some vault concepts are library knowledge
(not everything needs a backtest). Flag only gaps where absence of Trade_Scan evidence
means an assumption is being made without support.

**Vault path.**
Vault is at `../TS_Obsidian_Vault/` relative to Trade_Scan root. All reads use this path.
The vault is never in `config/path_authority.py` and never written to from Trade_Scan.

**No state persistence.**
Do not implement a "last run date" tracker or any state file. Each run is independent and
advisory.

---

## When to run

- **Session start:** `--quick` to see if anything new is worth investigating this session
- **Before designing a new directive:** `--themed` to check if the vault has a relevant framing
- **Research review / milestone:** `--deep` to catch contradictions and stale vault ideas
- **After a major vault ingest:** `--themed` to see if new ideas connect to current Trade_Scan work

---

## Implementation notes

1. The skill reads `research-ideas/` by glob — all `.md` files with `type: research-idea`
   and `status: developing` in frontmatter.
2. The vault `log.md` uses `## [YYYY-MM-DD] ingest | ...` format — grep for recent entries.
3. If `RESEARCH_MEMORY.md` is large, read the header section (settled decisions) and open arcs
   first — those are the comparison points.
4. The Tier 1 / Tier 2 / Tier 3 classification is a judgment call, not a formula. Lean
   conservative on Tier 1.

---

## Future: --gaps mode (do not implement until v1 is validated)

A fourth mode where direction reverses: start from Trade_Scan's active research themes
(RESEARCH_MEMORY, SYSTEM_STATE), then check what the vault has on each. Report imbalances.
Example: "Cointegration is the primary active theme; vault has 2 cointegration concept pages
vs. 15 trend/ORB pages — consider targeted ingest to close the gap."

Add only after the three core modes have been used enough to validate output format and tiering.

---

## Related skills

| Skill | Relationship |
|---|---|
| `/hypothesis-testing` | Downstream — takes a Tier 1 idea from discovery and runs it |
| `/generate-directives` | Also downstream — forms the directive from a Tier 1 idea |
| `/session-start` | `--quick` mode is a natural session-start complement |
| `/update-vault` | Inverse — snapshots Trade_Scan state into the vault |

---

## Friction log

Protocol: see [`../SELF_IMPROVEMENT.md`](../SELF_IMPROVEMENT.md).

| Date | Friction (1 line) | Edit landed |
|---|---|---|
| (none yet) | | |
