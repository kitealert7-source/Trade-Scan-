#!/usr/bin/env python3
"""
compact_research_memory.py  (v1.0)

Two-tier compaction + archive split for RESEARCH_MEMORY.md.
Lives in tools/ so it is versioned and recoverable.

  Tier A (simple)  — all sections <= 3 non-blank lines, no sub-lists
                     -> 3-line inline: date|tags, body, ---
  Tier B (complex) — multi-para, sub-lists, dense evidence
                     -> labels removed, blank-line paragraph separation kept

PROTECTED ZONES (byte-identical preservation):
  - FRAMEWORK REFERENCE block
  - LIVE DATA REFERENCES block
  - NEW ENTRY CONTRACT block
  - All post-contract entries (after NEW ENTRY CONTRACT closing separator)

Archive split:
  Entries with date < ARCHIVE_BEFORE  → RESEARCH_MEMORY_ARCHIVE.md  (compacted)
  Entries with date >= ARCHIVE_BEFORE → RESEARCH_MEMORY.md  (compacted, in active)
  Framework Reference + contract blocks + post-contract → always active

Usage:
    python tools/compact_research_memory.py            # dry-run (default)
    python tools/compact_research_memory.py --dry-run  # explicit dry-run — ALWAYS run first
    python tools/compact_research_memory.py --apply    # write files — only after dry-run review

SAFETY RULE: Always inspect the dry-run preview files before --apply.
One bad regex = irreversible corruption. Append-only means no clean fix.
"""

import re
import sys
import textwrap
from pathlib import Path

# ── Config ───────────────────────────────────────────────────────────────────
ROOT         = Path(__file__).resolve().parent.parent
RM           = ROOT / "RESEARCH_MEMORY.md"
ARC          = ROOT / "RESEARCH_MEMORY_ARCHIVE.md"

ARCHIVE_BEFORE   = "2026-04-14"   # strict less-than; entries before this date → archive
SIZE_LIMIT_LINES = 600
SIZE_LIMIT_KB    = 40

# ── Patterns ─────────────────────────────────────────────────────────────────
# Match either bare date line (multi-line entry form) OR date followed by
# inline metadata starting with ' |' (inline entry form).
# Group 1 always captures the YYYY-MM-DD date.
DATE_PAT    = re.compile(r'^(\d{4}-\d{2}-\d{2})(?:\s|\||$)')
SEP_PAT     = re.compile(r'^-{60,}\s*$')           # 60+ dashes = protected block marker
LABEL_PAT   = re.compile(
    r'^(Finding|Evidence|Conclusion|Implication|Strategy|Status|Run\s*IDs?|Tags)\s*:\s*(.*)',
    re.IGNORECASE
)
# Inline-metadata segment label (matches segments inside ' | '-split header):
INLINE_LABEL_PAT = re.compile(
    r'^(Tags|Strategy|Status|Run\s*IDs?)\s*:\s*(.*)',
    re.IGNORECASE
)
SUBLIST_PAT = re.compile(
    r'^\s{2,}(Experiment\s+\d|Test\s|Step\s|\d+\.\s)',
    re.MULTILINE
)
TAGS_PAT    = re.compile(r'^Tags\s*:\s*$', re.IGNORECASE)

PROTECTED_NAMES = frozenset(["FRAMEWORK REFERENCE", "LIVE DATA REFERENCES", "NEW ENTRY CONTRACT"])

NEW_HEADER = """\
# RESEARCH MEMORY

FORMAT POLICY:
- Entries may be compacted for token efficiency; content is semantically identical
- Compaction does not violate the append-only rule
- Archive split enforced at {ll} lines / {lk} KB -> RESEARCH_MEMORY_ARCHIVE.md
- Tier A (3-line inline): simple findings, all sections ≤ 3 non-blank lines, no sub-lists
- Tier B (label-free paragraphs): complex entries, labels removed, paragraph structure kept
- Pre-{ab} entries live in RESEARCH_MEMORY_ARCHIVE.md (compacted)

THIS FILE IS APPEND-ONLY. Corrections are new entries, not edits.
Post-contract entries must conform to the NEW ENTRY CONTRACT template.

""".format(ll=SIZE_LIMIT_LINES, lk=SIZE_LIMIT_KB, ab=ARCHIVE_BEFORE)

ARCHIVE_HEADER = """\
# RESEARCH MEMORY ARCHIVE
# Entries prior to {ab} — compacted for token efficiency
# Active file: RESEARCH_MEMORY.md

""".format(ab=ARCHIVE_BEFORE)


# ── File parsing ──────────────────────────────────────────────────────────────

def parse_file(path: Path):
    """
    Parse RESEARCH_MEMORY.md into a list of segments.
    Each segment is a dict with 'type' and type-specific keys.

    Types:
      header      : {'type': 'header', 'content': str}
      protected   : {'type': 'protected', 'name': str, 'content': str}
      entry       : {'type': 'entry', 'date': str, 'content': str, 'post_contract': bool}
    """
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines(keepends=True)
    n = len(lines)
    segments = []
    i = 0
    post_contract = False   # flip True after NEW ENTRY CONTRACT closing sep

    # ── Header: everything before the first date entry ────────────────────
    header_lines = []
    while i < n:
        stripped = lines[i].rstrip('\n\r')
        if DATE_PAT.match(stripped):
            break
        header_lines.append(lines[i])
        i += 1
    segments.append({'type': 'header', 'content': ''.join(header_lines)})

    def _date_only(s: str) -> str:
        m = DATE_PAT.match(s)
        return m.group(1) if m else s

    # ── Main parsing loop ─────────────────────────────────────────────────
    while i < n:
        stripped = lines[i].rstrip('\n\r')

        # ── Protected block? (60+ dashes line)
        if SEP_PAT.match(stripped):
            # Peek ahead for block name
            j = i + 1
            while j < n and not lines[j].strip():
                j += 1
            block_name_line = lines[j].strip() if j < n else ''
            matched_name = next(
                (nm for nm in PROTECTED_NAMES if block_name_line.startswith(nm)),
                None
            )
            if matched_name:
                # Block structure:
                #   sep(open) / name_line / sep(header) / content... / sep(close)
                #
                # The "closing separator" is the first separator whose NEXT
                # non-blank line is a date entry or EOF.
                # If the next non-blank line after the sep is another protected
                # block name, this sep belongs to the NEXT block — stop WITHOUT
                # including it (LIVE DATA REF → NEW ENTRY CONTRACT boundary).

                block_lines = [lines[i]]   # opening sep
                k = i + 1

                # Phase 1: read name line(s) and the inner header separator
                while k < n:
                    block_lines.append(lines[k])
                    if SEP_PAT.match(lines[k].rstrip('\n\r')):
                        k += 1
                        break   # consumed inner header sep
                    k += 1

                # Phase 2: read content until we hit a boundary separator
                while k < n:
                    line_k = lines[k]
                    s_k    = line_k.rstrip('\n\r')
                    if SEP_PAT.match(s_k):
                        # Look ahead past blanks
                        j = k + 1
                        while j < n and not lines[j].strip():
                            j += 1
                        next_c = lines[j].strip() if j < n else ''
                        is_date_next  = bool(DATE_PAT.match(next_c))
                        is_block_next = any(next_c.startswith(nm) for nm in PROTECTED_NAMES)
                        is_eof        = j >= n
                        if is_date_next or is_eof:
                            # Closing sep — include it, then stop
                            block_lines.append(line_k)
                            k += 1
                            break
                        elif is_block_next:
                            # This sep opens the NEXT block — don't consume it
                            break
                        else:
                            # Sep inside content (unusual) — include and continue
                            block_lines.append(line_k)
                            k += 1
                    else:
                        block_lines.append(line_k)
                        k += 1

                segments.append({
                    'type': 'protected',
                    'name': matched_name,
                    'content': ''.join(block_lines)
                })
                if matched_name == "NEW ENTRY CONTRACT":
                    post_contract = True
                i = k
                continue

        # ── Entry? (line starts with YYYY-MM-DD)
        if DATE_PAT.match(stripped) and stripped:
            entry_lines = [lines[i]]
            i += 1
            while i < n:
                s = lines[i].rstrip('\n\r')
                if DATE_PAT.match(s) or SEP_PAT.match(s):
                    break
                entry_lines.append(lines[i])
                i += 1
            segments.append({
                'type': 'entry',
                'date': _date_only(stripped),
                'content': ''.join(entry_lines),
                'post_contract': post_contract,
            })
            continue

        # Skip orphan lines (blank lines between entries, etc.)
        i += 1

    return segments


# ── Entry parsing ─────────────────────────────────────────────────────────────

def parse_entry(content: str) -> dict:
    """
    Break entry text into labelled fields.
    Returns: date, tags, strategy, status, run_ids,
             finding, evidence, conclusion, implication
    """
    lines = content.splitlines()
    result = {
        'date': '', 'tags': [], 'strategy': '', 'status': '',
        'run_ids': '', 'finding': '', 'evidence': '',
        'conclusion': '', 'implication': '',
    }
    field_buckets = {k: [] for k in ('tags', 'finding', 'evidence',
                                      'conclusion', 'implication',
                                      'strategy', 'status', 'run_ids')}
    current = None
    i = 0

    if lines:
        head_line = lines[0].rstrip()
        m = DATE_PAT.match(head_line)
        if m:
            result['date'] = m.group(1)
            remainder = head_line[m.end():].lstrip()
            # Strip a leading '|' that DATE_PAT may have left
            if remainder.startswith('|'):
                remainder = remainder[1:].strip()
            # Inline-form metadata: split on ' | ' and dispatch to buckets
            if remainder:
                parts = [p.strip() for p in re.split(r'\s\|\s', remainder) if p.strip()]
                inline_current = None
                for p in parts:
                    lm = INLINE_LABEL_PAT.match(p)
                    if lm:
                        key = lm.group(1).lower().replace(' ', '_')
                        if key.startswith('run'):
                            key = 'run_ids'
                        inline_current = key if key in field_buckets else None
                        rest = lm.group(2).strip()
                        if inline_current and rest:
                            if inline_current == 'tags':
                                # Tags may be comma-separated within the segment
                                for t in rest.split(','):
                                    t = t.strip()
                                    if t:
                                        field_buckets['tags'].append(t)
                            else:
                                field_buckets[inline_current].append(rest)
                    else:
                        # Continuation of previous inline field (e.g. extra
                        # pipe-separated tag like "Tags: A | B | C").
                        if inline_current == 'tags':
                            field_buckets['tags'].append(p)
                        elif inline_current and inline_current in field_buckets:
                            field_buckets[inline_current].append(p)
        else:
            result['date'] = head_line.strip()
        i = 1

    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()

        # Tags header (multi-line form: "Tags:" alone, values on subsequent lines)
        if TAGS_PAT.match(stripped):
            current = 'tags'
            i += 1
            continue

        # Label match
        m = LABEL_PAT.match(stripped)
        if m:
            key = m.group(1).lower().replace(' ', '_')
            # Normalise run_ids variants
            if key.startswith('run'):
                key = 'run_ids'
            if key in field_buckets:
                current = key
                rest = m.group(2).strip()
                if rest:
                    if key == 'tags':
                        for t in rest.split(','):
                            t = t.strip()
                            if t:
                                field_buckets['tags'].append(t)
                    else:
                        field_buckets[key].append(rest)
            i += 1
            continue

        # Content line for current field.
        # If no label has been seen yet (label-free paragraph entry), default
        # the bucket to 'finding' so the body is preserved instead of dropped.
        if not stripped:
            i += 1
            continue
        if current is None:
            current = 'finding'
        if current in field_buckets:
            field_buckets[current].append(raw.rstrip())

        i += 1

    # Materialise
    result['tags'] = [
        t.strip().lstrip('_\\').replace('\\', '')
        for t in field_buckets['tags']
        if t.strip()
    ]
    for key in ('strategy', 'status', 'run_ids'):
        result[key] = '\n'.join(field_buckets[key]).strip()
    for key in ('finding', 'evidence', 'conclusion', 'implication'):
        result[key] = '\n'.join(field_buckets[key]).strip()

    return result


# ── Tier classification ───────────────────────────────────────────────────────

def _non_blank_lines(text: str) -> int:
    return sum(1 for l in text.splitlines() if l.strip())

def is_tier_a(parsed: dict) -> bool:
    """
    Tier A: simple entry that compresses cleanly to one inline body line.
    Requires: every main section ≤ 3 non-blank lines AND no sub-lists.
    """
    for field in ('finding', 'evidence', 'conclusion', 'implication'):
        if _non_blank_lines(parsed[field]) > 3:
            return False
    # Sub-list check across all fields
    combined = ' '.join(parsed[f] for f in ('evidence', 'implication', 'finding'))
    if SUBLIST_PAT.search(combined):
        return False
    return True


# ── Compaction ────────────────────────────────────────────────────────────────

def _inline(text: str) -> str:
    """Collapse multi-line text to a single line."""
    return ' '.join(text.split())


def _entry_header(parsed: dict) -> str:
    """First line of a compacted entry: date | Tags: ... [| Strategy: ...]"""
    tags = ', '.join(parsed['tags']) if parsed['tags'] else '(no tags)'
    h = f"{parsed['date']} | Tags: {tags}"
    if parsed['strategy']:
        h += f" | Strategy: {parsed['strategy']}"
    if parsed['run_ids']:
        h += f" | Run IDs: {parsed['run_ids']}"
    if parsed['status']:
        h += f" | Status: {parsed['status']}"
    return h


def compact_tier_a(parsed: dict) -> str:
    """
    3-line format:
      ---
      YYYY-MM-DD | Tags: ... [| Strategy: ...]
      <finding>. <evidence>. <conclusion/implication>.
      ---
    """
    parts = []
    for field in ('finding', 'evidence', 'conclusion', 'implication'):
        text = parsed[field].strip()
        if text:
            inline = _inline(text)
            # Avoid repeating the same sentence already in parts
            if not any(inline in p or p in inline for p in parts):
                # Ensure each part ends with terminal punctuation
                if inline and inline[-1] not in '.!?':
                    inline += '.'
                parts.append(inline)

    body = ' '.join(parts)

    return f"---\n{_entry_header(parsed)}\n{body}\n---\n\n"


def compact_tier_b(parsed: dict) -> str:
    """
    Label-free multi-paragraph format:
      ---
      YYYY-MM-DD | Tags: ... [| Strategy: ...]
      [Status: ... if present]

      <finding paragraph>

      <evidence paragraph>

      <conclusion paragraph>

      <implication paragraph>
      ---
    """
    header = _entry_header(parsed)

    paragraphs = []
    for field in ('finding', 'evidence', 'conclusion', 'implication'):
        text = parsed[field].strip()
        if text:
            paragraphs.append(text)

    body = '\n\n'.join(paragraphs)
    return f"---\n{header}\n\n{body}\n---\n\n"


def compact_entry(seg: dict) -> str:
    """Route an entry segment through the correct compaction tier."""
    parsed = parse_entry(seg['content'])
    if is_tier_a(parsed):
        return compact_tier_a(parsed)
    else:
        return compact_tier_b(parsed)


# ── Main ──────────────────────────────────────────────────────────────────────

def build_outputs(segments):
    """
    Returns (active_text, archive_text).
    active_text  → goes to RESEARCH_MEMORY.md
    archive_text → goes to RESEARCH_MEMORY_ARCHIVE.md (may be empty)
    """
    active_parts  = [NEW_HEADER]
    archive_parts = [ARCHIVE_HEADER]
    has_archive   = False

    for seg in segments:
        t = seg['type']

        if t == 'header':
            # Old header replaced entirely by NEW_HEADER — skip
            continue

        elif t == 'protected':
            # Always goes to active, byte-identical
            active_parts.append(seg['content'])
            # Ensure trailing newline
            if not seg['content'].endswith('\n'):
                active_parts.append('\n')

        elif t == 'entry':
            if seg['post_contract']:
                # Post-contract entries are protected — preserve exactly
                active_parts.append(seg['content'])
                if not seg['content'].endswith('\n'):
                    active_parts.append('\n')
            else:
                compacted = compact_entry(seg)
                if seg['date'] < ARCHIVE_BEFORE:
                    archive_parts.append(compacted)
                    has_archive = True
                else:
                    active_parts.append(compacted)

    active_text  = ''.join(active_parts)
    archive_text = ''.join(archive_parts) if has_archive else ''
    return active_text, archive_text


def count_lines(text: str) -> int:
    return text.count('\n')


def check_size(text: str, label: str):
    lines = count_lines(text)
    kb    = len(text.encode('utf-8')) / 1024
    status = "OK" if lines <= SIZE_LIMIT_LINES and kb <= SIZE_LIMIT_KB else "OVER LIMIT"
    print(f"  {label}: {lines} lines, {kb:.1f} KB  [{status}]")


def run(dry_run: bool):
    print(f"[compact_research_memory] reading {RM}")
    segments = parse_file(RM)

    total_entries = sum(1 for s in segments if s['type'] == 'entry')
    post_contract_entries = sum(1 for s in segments if s['type'] == 'entry' and s['post_contract'])
    compactable_entries   = total_entries - post_contract_entries

    print(f"  Segments: {len(segments)} total")
    print(f"  Entries : {total_entries} ({compactable_entries} compactable, "
          f"{post_contract_entries} post-contract [protected])")

    # Classify compactable entries
    tier_a = tier_b = archived = 0
    for seg in segments:
        if seg['type'] == 'entry' and not seg['post_contract']:
            parsed = parse_entry(seg['content'])
            if is_tier_a(parsed):
                tier_a += 1
            else:
                tier_b += 1
            if seg['date'] < ARCHIVE_BEFORE:
                archived += 1

    print(f"  Tier A  : {tier_a}  Tier B: {tier_b}  -> Archive: {archived}")

    active_text, archive_text = build_outputs(segments)

    # ── Entry-count guard: every input entry must appear in output ────────
    # Count emitted entries by date prefixes. Compacted format begins each
    # entry with "---\nYYYY-MM-DD". Post-contract entries are preserved
    # as-is and start with "YYYY-MM-DD" at line start (after blank or sep).
    emitted_dates = (
        re.findall(r'(?m)^---\s*\n(\d{4}-\d{2}-\d{2})', active_text)
        + re.findall(r'(?m)^---\s*\n(\d{4}-\d{2}-\d{2})', archive_text)
        + re.findall(r'(?m)^(\d{4}-\d{2}-\d{2})\s*$', active_text)
        + re.findall(r'(?m)^(\d{4}-\d{2}-\d{2})\s*$', archive_text)
    )
    input_dates = [s['date'] for s in segments if s['type'] == 'entry']
    if len(emitted_dates) < len(input_dates):
        print()
        print(f"!! ENTRY-COUNT GUARD FAILED: input={len(input_dates)} "
              f"emitted={len(emitted_dates)} — refusing to write.")
        from collections import Counter
        missing = Counter(input_dates) - Counter(emitted_dates)
        if missing:
            print(f"   missing dates (count): {dict(missing)}")
        sys.exit(2)

    print()
    print(f"ENTRY-COUNT GUARD: input={len(input_dates)} emitted={len(emitted_dates)}  [OK]")
    print()
    print("SIZE ESTIMATES AFTER COMPACTION:")
    check_size(active_text, "RESEARCH_MEMORY.md (active)")
    if archive_text:
        check_size(archive_text, "RESEARCH_MEMORY_ARCHIVE.md  ")

    # Merge new archive output with any existing archive (preserve prior entries).
    # Strip the ARCHIVE_HEADER from the new output and concatenate its body
    # onto the existing archive content. If no prior archive exists, use
    # archive_text as-is (with its header).
    merged_archive_text = archive_text
    if archive_text:
        if ARC.exists():
            existing = ARC.read_text(encoding="utf-8")
            new_body = archive_text
            if new_body.startswith(ARCHIVE_HEADER):
                new_body = new_body[len(ARCHIVE_HEADER):]
            # Ensure a single blank line between existing content and new entries
            sep = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
            merged_archive_text = existing + sep + new_body

    if dry_run:
        preview_active  = Path("C:/tmp/PREVIEW_RESEARCH_MEMORY.md")
        preview_archive = Path("C:/tmp/PREVIEW_RESEARCH_MEMORY_ARCHIVE.md")
        preview_active.write_text(active_text, encoding="utf-8")
        print(f"\nDRY-RUN: preview written to {preview_active}")
        if merged_archive_text:
            preview_archive.write_text(merged_archive_text, encoding="utf-8")
            print(f"DRY-RUN: preview written to {preview_archive}")
            # Dry-run archive-preservation check: existing archive entry count
            # must be <= merged archive entry count.
            if ARC.exists():
                existing = ARC.read_text(encoding="utf-8")
                existing_dates = (
                    re.findall(r'(?m)^---\s*\n(\d{4}-\d{2}-\d{2})', existing)
                    + re.findall(r'(?m)^(\d{4}-\d{2}-\d{2})\s*$', existing)
                )
                merged_dates = (
                    re.findall(r'(?m)^---\s*\n(\d{4}-\d{2}-\d{2})', merged_archive_text)
                    + re.findall(r'(?m)^(\d{4}-\d{2}-\d{2})\s*$', merged_archive_text)
                )
                print(f"ARCHIVE-PRESERVATION: existing={len(existing_dates)} "
                      f"merged={len(merged_dates)}  "
                      f"[{'OK' if len(merged_dates) >= len(existing_dates) else 'LOSS'}]")
                if len(merged_dates) < len(existing_dates):
                    sys.exit(3)
        print("Review files then re-run with --apply to commit changes.")
    else:
        RM.write_text(active_text, encoding="utf-8")
        print(f"  Written: {RM}")
        if merged_archive_text:
            ARC.write_text(merged_archive_text, encoding="utf-8")
            print(f"  Written: {ARC} (merged with prior archive)")
        print("Done.")


if __name__ == "__main__":
    dry = "--apply" not in sys.argv
    run(dry_run=dry)
