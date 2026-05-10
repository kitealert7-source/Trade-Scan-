#!/usr/bin/env python3
"""
audit_intent_index.py -- self-healing layer for the intent/enforcement
hook system.

Modes:
  --structural  YAML parse, regex compile, skill existence, py_compile
                of both hooks, duplicate id check.
  --overlap     Pairwise Jaccard similarity on regex + tag vocabulary.
                Flags pairs >= OVERLAP_THRESHOLD (default 0.70).
                Also reports shadowed intents (same keys, lower priority).
  --dead        Scans intent_matches.jsonl; intents with zero HIT in the
                last N days (default 14) are flagged.
  --daily       Top-5 MISS prompts and top-3 low-score near-misses over
                the last 24h. Visibility only, no action.
  --misclass    Scan post_write.jsonl for misclassified=True events.
  --violations  Summarize hard-enforcement violations: hard intent
                fired, turn ended without the required /skill call.
  --miss-cluster Cluster MISS prompts by n-gram frequency to reveal
                coverage gaps (candidate new intents).
  --all         Run every mode.

Exit codes:
  0 -- clean
  1 -- warnings only
  2 -- hard errors (broken HARD intent -> enforcement degraded)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import py_compile
import re
import sys
from collections import Counter
from pathlib import Path

try:
    import yaml
except ImportError:
    print("[ERROR] PyYAML required (pip install pyyaml)", file=sys.stderr)
    sys.exit(2)


REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = REPO_ROOT / "outputs" / "system_reports" / "INTENT_INDEX.yaml"
SKILLS_DIR = REPO_ROOT / ".claude" / "skills"
HOOK_FILES = [
    REPO_ROOT / ".claude" / "hooks" / "intent_injector.py",
    REPO_ROOT / ".claude" / "hooks" / "post_write_reminder.py",
]
INTENT_LOG = REPO_ROOT / ".claude" / "logs" / "intent_matches.jsonl"
POSTWRITE_LOG = REPO_ROOT / ".claude" / "logs" / "post_write.jsonl"
VIOLATION_LOG = REPO_ROOT / ".claude" / "logs" / "violations.jsonl"
_MISS_STOPWORDS = {
    "the","a","an","is","to","of","and","for","in","on","at","please","this",
    "that","my","i","we","it","be","can","will","do","have","has","lets",
    "let","are","with","but","from","as","so","if","or","not","you","your",
}

# Synonym table for MISS cluster normalization. Keep small; expand
# only when you see fragmented clusters in real usage.
_MISS_SYNONYMS = {
    "limit": "cap", "max": "cap", "ceiling": "cap",
    "exposure": "risk", "sizing": "risk",
    "change": "update", "modify": "update", "adjust": "update",
    "repair": "fix", "resolve": "fix",
    "stale": "old", "outdated": "old",
    "remove": "cleanup", "clear": "cleanup", "delete": "cleanup",
    "push": "promote", "ship": "promote", "advance": "promote",
    "rerun": "rerun", "rereun": "rerun",
}

# MISS prompts containing ANY of these words surface even at count=1.
_MISS_HIGH_RISK = {
    "engine", "registry", "vault", "portfolio", "capital", "promote",
    "ledger", "governance", "manifest",
    "frozen", "canonical", "execution_loop", "mps",
}
_CLUSTER_MERGE_OVERLAP = 0.5

OVERLAP_THRESHOLD = 0.70
DEAD_WINDOW_DAYS = 14
MAX_INTENTS = 25
_WORD_RE = re.compile(r"[a-z0-9_]+")


# ---------- helpers ----------

def _load_index() -> list[dict]:
    if not INDEX_PATH.exists():
        raise FileNotFoundError(INDEX_PATH)
    data = yaml.safe_load(INDEX_PATH.read_text(encoding="utf-8")) or {}
    return list(data.get("intents", []))


def _vocab(intent: dict) -> set[str]:
    """Tokenize all regex patterns + tags into a keyword bag."""
    bag: set[str] = set()
    for pat in intent.get("regex_patterns", []) or []:
        for tok in _WORD_RE.findall(pat.lower()):
            if len(tok) >= 3 and tok not in {"the", "and", "for"}:
                bag.add(tok)
    for t in intent.get("semantic_tags", []) or []:
        tag = str(t.get("tag", "")).lower().strip()
        if tag:
            bag.add(tag)
    return bag


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _read_jsonl(path: Path, since: _dt.datetime | None = None) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if since is not None:
            ts = rec.get("ts", "")
            try:
                when = _dt.datetime.fromisoformat(ts.rstrip("Z"))
            except Exception:
                continue
            if when < since:
                continue
        out.append(rec)
    return out


# ---------- modes ----------

def check_structural(intents: list[dict]) -> tuple[int, int]:
    """Return (errors, warnings)."""
    errors = warnings = 0

    if len(intents) > MAX_INTENTS:
        print(f"[WARN] INTENT_INDEX size={len(intents)} exceeds "
              f"MAX={MAX_INTENTS}; merge or prune.")
        warnings += 1

    skills = ({p.parent.name for p in SKILLS_DIR.glob("*/SKILL.md")}
              if SKILLS_DIR.exists() else set())

    seen: set[str] = set()
    for it in intents:
        iid = str(it.get("id", "<missing>"))
        enforcement = it.get("enforcement", "soft")
        severity = "ERROR" if enforcement == "hard" else "WARN"

        if iid in seen:
            print(f"[{severity}] duplicate intent id: {iid}")
            if severity == "ERROR": errors += 1
            else: warnings += 1
        seen.add(iid)

        for pat in it.get("regex_patterns", []) or []:
            try:
                re.compile(pat)
            except re.error as e:
                print(f"[{severity}] {iid}: bad regex {pat!r}: {e}")
                if severity == "ERROR": errors += 1
                else: warnings += 1

        skill = it.get("must_skill")
        if skill and skills and skill not in skills:
            print(f"[{severity}] {iid}: must_skill='{skill}' has no "
                  f".claude/skills/{skill}/SKILL.md")
            if severity == "ERROR": errors += 1
            else: warnings += 1

        if enforcement == "hard" and not it.get("reason"):
            print(f"[WARN] {iid}: hard intent missing 'reason'")
            warnings += 1

    for hook in HOOK_FILES:
        if not hook.exists():
            print(f"[ERROR] missing hook: {hook}")
            errors += 1
            continue
        try:
            py_compile.compile(str(hook), doraise=True)
        except py_compile.PyCompileError as e:
            print(f"[ERROR] {hook.name} does not compile: {e}")
            errors += 1

    if errors == 0 and warnings == 0:
        print("[OK] structural: passed")
    return errors, warnings


def check_overlap(intents: list[dict]) -> int:
    """Return number of warnings."""
    warnings = 0
    vocabs = [(it.get("id", "?"), _vocab(it), int(it.get("priority", 0)))
              for it in intents]
    for i in range(len(vocabs)):
        for j in range(i + 1, len(vocabs)):
            a_id, a_v, a_pr = vocabs[i]
            b_id, b_v, b_pr = vocabs[j]
            sim = _jaccard(a_v, b_v)
            if sim >= OVERLAP_THRESHOLD:
                print(f"[WARN] overlap {a_id} <-> {b_id}: "
                      f"Jaccard={sim:.2f}")
                warnings += 1
                # shadow check
                if a_v.issubset(b_v) and a_pr < b_pr:
                    print(f"         -> {a_id} is shadowed by {b_id} "
                          f"(priority {a_pr} < {b_pr})")
                elif b_v.issubset(a_v) and b_pr < a_pr:
                    print(f"         -> {b_id} is shadowed by {a_id} "
                          f"(priority {b_pr} < {a_pr})")
    if warnings == 0:
        print("[OK] overlap: no pairs >= "
              f"{OVERLAP_THRESHOLD:.2f} Jaccard")
    return warnings


def check_dead(intents: list[dict], days: int = DEAD_WINDOW_DAYS) -> int:
    warnings = 0
    since = _dt.datetime.utcnow() - _dt.timedelta(days=days)
    records = _read_jsonl(INTENT_LOG, since=since)
    hit_counts: Counter[str] = Counter()
    for r in records:
        cid = r.get("chosen_intent")
        if cid:
            hit_counts[cid] += 1
    for it in intents:
        iid = str(it.get("id", "?"))
        if hit_counts.get(iid, 0) == 0:
            print(f"[WARN] dead intent (0 hits in {days}d): {iid}")
            warnings += 1
    if warnings == 0:
        print(f"[OK] dead-intent: all intents hit at least once in "
              f"{days}d window")
    return warnings


def daily_summary() -> int:
    since = _dt.datetime.utcnow() - _dt.timedelta(days=1)
    records = _read_jsonl(INTENT_LOG, since=since)
    misses = [r for r in records if r.get("chosen_intent") is None
              and r.get("snippet")]
    near = [r for r in records if r.get("chosen_intent") is None
            and r.get("top_intents_considered")]
    print(f"[DAILY] 24h prompts: {len(records)}, MISSes: {len(misses)}, "
          f"near-miss: {len(near)}")
    if misses:
        print("  Top MISS snippets:")
        for r in misses[:5]:
            print(f"    - {r['snippet'][:100]}")
    if near:
        print("  Near-miss candidates (top scoring intent < threshold):")
        for r in near[:3]:
            top = r["top_intents_considered"][0]
            print(f"    - intent={top['id']} score={top['score']}/"
                  f"{top['threshold']}: {r['snippet'][:80]}")
    return 0


def check_violations(days: int = 14) -> int:
    """Summarize hard-enforcement violations from .claude/logs/violations.jsonl."""
    since = _dt.datetime.utcnow() - _dt.timedelta(days=days)
    records = _read_jsonl(VIOLATION_LOG, since=since)
    if not records:
        print(f"[OK] violations: 0 events in last {days}d")
        return 0
    by_event: Counter[str] = Counter(r.get("event", "?") for r in records)
    hard = [r for r in records if r.get("event") == "hard_violation"]
    breaches = [r for r in records if r.get("event") == "tool_before_skill"]
    satisfied = [r for r in records if r.get("event") == "skill_satisfied"]
    warnings = 1 if (hard or breaches) else 0
    print(f"[STATS] {days}d: satisfied={len(satisfied)} "
          f"tool_before_skill={len(breaches)} hard_violation={len(hard)}")
    if hard:
        print(f"[WARN] {len(hard)} hard violations "
              f"(turn ended without required skill):")
        by_intent: Counter[str] = Counter(
            f"{r.get('intent_id')}->/{r.get('must_skill')}" for r in hard)
        for key, count in by_intent.most_common(10):
            print(f"  {count}x  {key}")
    if breaches and not hard:
        print("  (no hard violations, but breaches logged; most turns "
              "eventually invoked the skill)")
    return warnings


def _normalize_tokens(tokens: list[str]) -> list[str]:
    return [_MISS_SYNONYMS.get(t, t) for t in tokens]


def _merge_clusters(clusters: list[tuple[str, int, list[str]]]
                    ) -> list[tuple[str, int, list[str]]]:
    """Greedy merge: if two clusters' token sets overlap >=
    _CLUSTER_MERGE_OVERLAP (Jaccard), fold the smaller one into the
    larger. Examples are unioned; count is max(a,b) (conservative --
    individual docs may not overlap)."""
    merged: list[tuple[set[str], str, int, list[str]]] = []
    for gram, count, examples in clusters:
        tset = set(gram.split())
        placed = False
        for i, (mset, mgram, mcount, mexamples) in enumerate(merged):
            union = mset | tset
            if not union:
                continue
            overlap = len(mset & tset) / len(union)
            if overlap >= _CLUSTER_MERGE_OVERLAP:
                new_gram = mgram if mcount >= count else gram
                new_set = union
                new_count = max(mcount, count)
                merged_examples = list({*mexamples, *examples})
                merged[i] = (new_set, new_gram, new_count, merged_examples)
                placed = True
                break
        if not placed:
            merged.append((tset, gram, count, list(examples)))
    return [(g, c, ex) for (_, g, c, ex) in merged]


def miss_cluster(days: int = 7, min_count: int = 3, top_k: int = 15) -> int:
    """Cluster MISS prompts by n-gram frequency (normalized) to surface
    coverage gaps. Also surfaces single MISSes touching high-risk
    keywords."""
    since = _dt.datetime.utcnow() - _dt.timedelta(days=days)
    records = [r for r in _read_jsonl(INTENT_LOG, since=since)
               if r.get("chosen_intent") is None and r.get("snippet")]
    if not records:
        print(f"[OK] miss-cluster: 0 MISS prompts in last {days}d")
        return 0

    snippets = [r["snippet"] for r in records]
    ngram_doc_freq: Counter[str] = Counter()
    ngram_examples: dict[str, list[str]] = {}

    for s in snippets:
        raw_tokens = [t for t in _WORD_RE.findall(s.lower())
                      if t not in _MISS_STOPWORDS and len(t) > 1]
        tokens = _normalize_tokens(raw_tokens)
        seen_this_doc: set[str] = set()
        for n in (2, 3):
            for i in range(len(tokens) - n + 1):
                gram = " ".join(tokens[i:i + n])
                if gram in seen_this_doc:
                    continue
                seen_this_doc.add(gram)
                ngram_doc_freq[gram] += 1
                ngram_examples.setdefault(gram, []).append(s)

    raw_clusters = [(g, c, ngram_examples[g][:4])
                    for g, c in ngram_doc_freq.most_common()
                    if c >= min_count]
    clusters = _merge_clusters(raw_clusters)[:top_k]

    unigram_freq: Counter[str] = Counter()
    for s in snippets:
        raw = [t for t in _WORD_RE.findall(s.lower())
               if t not in _MISS_STOPWORDS and len(t) > 2]
        for tok in set(_normalize_tokens(raw)):
            unigram_freq[tok] += 1
    uni_candidates = [(g, c) for g, c in unigram_freq.most_common(top_k)
                      if c >= max(min_count, 4)]

    # High-risk count=1 MISSes: surface separately (never get clustered).
    high_risk_single = []
    for r in records:
        snip = r.get("snippet", "").lower()
        hit_terms = {t for t in _MISS_HIGH_RISK if t in snip}
        if hit_terms:
            high_risk_single.append((sorted(hit_terms), r["snippet"]))

    print(f"[STATS] {days}d MISS prompts: {len(records)} "
          f"(high-risk touches: {len(high_risk_single)})")

    if clusters:
        print(f"Top n-gram clusters (normalized, merged, "
              f">= {min_count} MISSes):")
        for gram, count, examples in clusters:
            print(f"  {count}x  '{gram}'")
            for ex in examples[:2]:
                print(f"      e.g., {ex[:100]}")
    else:
        print("  (no n-gram reached min_count)")

    if uni_candidates:
        print("Frequent unigrams (potential tag candidates):")
        for tok, count in uni_candidates[:8]:
            print(f"  {count}x  {tok}")

    if high_risk_single:
        print("HIGH-RISK single MISSes (surface even at count=1):")
        for terms, snippet in high_risk_single[:10]:
            print(f"  [{','.join(terms)}]  {snippet[:100]}")

    return 1 if (clusters or uni_candidates or high_risk_single) else 0


def misclass_summary() -> int:
    since = _dt.datetime.utcnow() - _dt.timedelta(days=7)
    records = [r for r in _read_jsonl(POSTWRITE_LOG, since=since)
               if r.get("misclassified")]
    if not records:
        print("[OK] misclassification: 0 mismatches in last 7d")
        return 0
    print(f"[WARN] {len(records)} misclassification event(s) in 7d:")
    for r in records[:10]:
        print(f"  intent={r.get('last_intent_id')} "
              f"expected_cat={r.get('last_intent_expected_cat')} "
              f"actual_cat={r.get('file_category')} "
              f"file={r.get('file_rel')}")
    return 1


# ---------- CLI ----------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--structural", action="store_true")
    ap.add_argument("--overlap", action="store_true")
    ap.add_argument("--dead", action="store_true")
    ap.add_argument("--daily", action="store_true")
    ap.add_argument("--misclass", action="store_true")
    ap.add_argument("--violations", action="store_true")
    ap.add_argument("--miss-cluster", action="store_true")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    if not any([args.structural, args.overlap, args.dead, args.daily,
                args.misclass, args.violations, args.miss_cluster,
                args.all]):
        args.all = True

    try:
        intents = _load_index()
    except Exception as e:
        print(f"[ERROR] cannot load index: {e}")
        return 2

    total_errors = 0
    total_warnings = 0

    if args.structural or args.all:
        print("== structural ==")
        e, w = check_structural(intents)
        total_errors += e
        total_warnings += w

    if args.overlap or args.all:
        print("== overlap ==")
        total_warnings += check_overlap(intents)

    if args.dead or args.all:
        print("== dead intents ==")
        total_warnings += check_dead(intents)

    if args.misclass or args.all:
        print("== misclassification ==")
        total_warnings += misclass_summary()

    if args.violations or args.all:
        print("== violations ==")
        total_warnings += check_violations()

    if args.miss_cluster or args.all:
        print("== miss clustering ==")
        total_warnings += miss_cluster()

    if args.daily or args.all:
        print("== daily summary ==")
        daily_summary()

    print(f"\nSummary: errors={total_errors} warnings={total_warnings}")
    if total_errors > 0:
        return 2
    if total_warnings > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
