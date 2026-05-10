#!/usr/bin/env python3
"""
UserPromptSubmit hook -- skill-routing enforcement.

See: outputs/system_reports/INTENT_INDEX.yaml for the rule set.

Runtime pipeline:
  1. Load + validate INTENT_INDEX.yaml. Validation errors on HARD
     intents are LOUD: the hook still runs, but emits a persistent
     "ENFORCEMENT DEGRADED" banner in the injected context until
     the index is repaired. SOFT intents just warn in the log.
  2. Score every intent (regex hit -> 100; else weighted fuzzy).
  3. Pick the highest-priority intent clearing its threshold.
  4. Inject (hard = MANDATORY ROUTING; soft = skill hint).
  5. Append a JSONL decision-trace record to
     .claude/logs/intent_matches.jsonl.

Hook never raises -- every failure path returns exit 0.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml  # type: ignore
except Exception:
    yaml = None


REPO_ROOT = Path(__file__).resolve().parents[2]
INDEX_PATH = REPO_ROOT / "outputs" / "system_reports" / "INTENT_INDEX.yaml"
LOG_PATH = REPO_ROOT / ".claude" / "logs" / "intent_matches.jsonl"
STATE_PATH = REPO_ROOT / ".claude" / "state" / "last_intent.json"
EXPECT_PATH = REPO_ROOT / ".claude" / "state" / "pending_skill_expectations.json"
VIOLATION_LOG = REPO_ROOT / ".claude" / "logs" / "violations.jsonl"
WORKFLOWS_DIR = REPO_ROOT / ".agents" / "workflows"

ESCALATION_THRESHOLD = 3   # violations in 24h -> escalate the next injection
ESCALATION_WINDOW_H = 24

DEFAULT_THRESHOLD = 3
PROXIMITY_BONUS = 3
PROXIMITY_WINDOW = 3
MAX_INTENTS = 25
_WORD_RE = re.compile(r"[a-z0-9_]+")


# ---------------- logging ----------------

def _log_jsonl(record: dict) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _write_last_intent(intent: dict | None, method: str, score: int) -> None:
    """Ephemeral state read by post_write_reminder for misclassification checks."""
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "ts": _dt.datetime.utcnow().isoformat() + "Z",
            "intent_id": intent.get("id") if intent else None,
            "expected_file_category": (intent or {}).get("expected_file_category"),
            "method": method,
            "score": score,
        }
        STATE_PATH.write_text(json.dumps(payload), encoding="utf-8")
    except Exception:
        pass


def _write_expectations(intent: dict | None) -> None:
    """Turn-scoped pending skill expectation.
    Overwritten every UserPromptSubmit so violations are scoped to the
    current turn. Consumed by skill_violation_check hook."""
    try:
        EXPECT_PATH.parent.mkdir(parents=True, exist_ok=True)
        if intent and intent.get("enforcement") == "hard":
            payload = {
                "turn_ts": _dt.datetime.utcnow().isoformat() + "Z",
                "expectations": [{
                    "intent_id": intent.get("id"),
                    "must_skill": intent.get("must_skill"),
                    "status": "pending",
                    "tools_before_skill": 0,
                }],
            }
        else:
            payload = {"turn_ts": _dt.datetime.utcnow().isoformat() + "Z",
                       "expectations": []}
        EXPECT_PATH.write_text(json.dumps(payload), encoding="utf-8")
    except Exception:
        pass


# ---------------- validation ----------------

def _validate_intents(intents: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (valid_intents, validation_errors). Broken HARD intents are
    retained (so the hook can still emit their blocking directive) but
    recorded in errors so the banner fires."""
    errors: list[dict] = []
    seen_ids: set[str] = set()
    valid: list[dict] = []
    skill_slugs = (
        {p.stem for p in WORKFLOWS_DIR.glob("*.md")}
        if WORKFLOWS_DIR.exists() else set()
    )
    for idx, it in enumerate(intents):
        iid = str(it.get("id", f"<idx{idx}>"))
        enforcement = it.get("enforcement", "soft")
        if iid in seen_ids:
            errors.append({"intent": iid, "error": "duplicate_id",
                           "severity": enforcement})
        seen_ids.add(iid)
        # regex compile check
        for pat in it.get("regex_patterns", []) or []:
            try:
                re.compile(pat)
            except re.error as e:
                errors.append({"intent": iid, "error": f"bad_regex:{e}",
                               "severity": enforcement})
        # skill existence
        skill = it.get("must_skill")
        if skill and skill_slugs and skill not in skill_slugs:
            errors.append({"intent": iid, "error": f"missing_skill:{skill}",
                           "severity": enforcement})
        valid.append(it)
    return valid, errors


def _load_intents() -> tuple[list[dict], list[dict]]:
    if yaml is None or not INDEX_PATH.exists():
        return [], [{"intent": "<index>", "error": "yaml_or_index_missing",
                     "severity": "hard"}]
    try:
        data = yaml.safe_load(INDEX_PATH.read_text(encoding="utf-8")) or {}
        raw = list(data.get("intents", []))
    except Exception as e:
        return [], [{"intent": "<index>", "error": f"yaml_parse:{e}",
                     "severity": "hard"}]
    if len(raw) > MAX_INTENTS:
        _log_jsonl({"ts": _dt.datetime.utcnow().isoformat() + "Z",
                    "level": "WARN",
                    "msg": f"INTENT_INDEX size={len(raw)} exceeds MAX={MAX_INTENTS}"})
    return _validate_intents(raw)


# ---------------- matching ----------------

def _tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _regex_hit(prompt: str, patterns: list[str]) -> tuple[bool, list[str]]:
    hits: list[str] = []
    for pat in patterns or []:
        try:
            m = re.search(pat, prompt)
            if m:
                hits.append(m.group(0))
        except re.error:
            continue
    return bool(hits), hits


def _score_fuzzy(prompt_lower: str, tokens: list[str], tags: list[dict]
                 ) -> tuple[int, list[str], list[int]]:
    if not tags:
        return 0, [], []
    score = 0
    matched_terms: list[str] = []
    exact_positions: list[int] = []
    for t in tags or []:
        tag = str(t.get("tag", "")).lower().strip()
        if not tag:
            continue
        weight = int(t.get("weight", 1))
        if re.search(rf"\b{re.escape(tag)}\b", prompt_lower):
            score += weight * 2
            matched_terms.append(tag)
            if " " not in tag and "-" not in tag:
                exact_positions.extend(
                    [i for i, tok in enumerate(tokens) if tok == tag]
                )
        elif tag in prompt_lower:
            score += weight * 1
            matched_terms.append(tag)
    return score, matched_terms, exact_positions


# ---------------- file-scope filter ----------------
#
# Some intents have a HARD enforcement that should only fire when the
# affected files actually fall in a protected scope. The text classifier
# alone produces false positives -- e.g. talking about "engine v1.5.8a"
# in a commit message that only touches engines/filter_stack.py (mutable
# shared infra, NOT the FROZEN engine vault). The `frozen_path_only`
# field on an intent gates the injection on actual changed-file scope.
#
# Default scope rules (applied when frozen_path_only is true and no
# explicit `frozen_paths` regex list is provided on the intent):
#   - engine_dev/universal_research_engine/<version>/...
#   - vault/engines/...
#   - any file whose name matches engine_manifest.json
#   - any file whose name matches contract.json
#
# Explicitly IGNORED (do NOT trigger) unless they ALSO touch one of the
# above paths in the same change set:
#   - engines/...
#   - tools/...
#   - governance/...
#   - tests/...
#   - outputs/...

_DEFAULT_FROZEN_PATTERNS = (
    r"^engine_dev/universal_research_engine/[^/]+/",
    r"^vault/engines/",
    r"(^|/)engine_manifest\.json$",
    r"(^|/)contract\.json$",
)


def _get_changed_files() -> list[str]:
    """Return git-tracked changed files (staged + unstaged ONLY).

    Untracked files ('??' status) are deliberately EXCLUDED. Long-sitting
    untracked artifacts under a frozen path (e.g. an unintegrated engine
    fork directory) would otherwise lift the frozen_path_only suppression
    on every UserPromptSubmit — producing the engine_change misfire pattern
    of "12 violations in 24h" on prompts that aren't engine work at all.

    Active edits (M/A/D/R/C/U) still count. If a user is genuinely
    scaffolding a new engine version, the moment they `git add` it the
    hook will start firing as intended.

    Best-effort: returns [] on any subprocess/git error. The hook never
    blocks on this.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "-uall"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    files: list[str] = []
    for line in (result.stdout or "").splitlines():
        # Porcelain format: "XY <path>" where X/Y are status flags.
        # Renames look like "R  old -> new" — keep the "new" path.
        # Untracked is "?? <path>" — excluded (see docstring).
        line = line.rstrip()
        if len(line) < 4:
            continue
        if line[:2] == "??":
            continue
        path_part = line[3:].strip()
        if " -> " in path_part:
            path_part = path_part.split(" -> ", 1)[1]
        # Strip surrounding quotes git adds for paths with special chars.
        path_part = path_part.strip('"')
        if path_part:
            # Normalize Windows backslashes
            files.append(path_part.replace("\\", "/"))
    return files


def _changes_touch_frozen_paths(changed_files: list[str],
                                patterns: tuple[str, ...] = _DEFAULT_FROZEN_PATTERNS,
                                ) -> bool:
    """True iff at least one changed file matches a frozen-scope pattern."""
    if not changed_files:
        return False
    compiled = [re.compile(p) for p in patterns]
    for f in changed_files:
        for c in compiled:
            if c.search(f):
                return True
    return False


# ---------------- subject + infra-action filters ----------------
#
# Intents with `requires_subject: true` represent strategy-workflow
# requests (promote, deploy, lifecycle changes). The text classifier
# alone produces false positives — a prompt that talks ABOUT the
# promote tool ("delete the /promote scaffolding", "migrate promotion
# doctrine", "refactor portfolio_complete handler") shares vocabulary
# with workflow execution but is meta-tooling, not workflow.
#
# Two-layer gate (post-score, before injection):
#   1. Infra-action suppression: prompts whose lead verb is an
#      infrastructure action (delete/refactor/migrate/etc.) suppress
#      the workflow injection UNLESS a strong subject identifier is
#      named — the rare hybrid case ("promote ABC_V1_P05 then delete
#      the burn-in scaffolding") still fires because the strong
#      subject signals genuine workflow intent.
#   2. Fuzzy-no-subject suppression: fuzzy-fired matches require a
#      strong subject (strategy_id / PF_id / vault_id). Regex hits
#      bypass — they encode subject requirements in the pattern
#      itself (idiomatic phrasal patterns like "add X to portfolio"
#      rely on the infra-action gate above to filter false positives).

_INFRA_PHRASES = (
    # Action verbs (deletion / migration / refactor)
    "delete", "deletes", "deleted", "deleting",
    "remove", "removes", "removed", "removing",
    "retire", "retires", "retired", "retiring",
    "cleanup", "cleans", "cleaning", "clean-up",
    "refactor", "refactors", "refactored", "refactoring",
    "rename", "renames", "renamed", "renaming",
    "migrate", "migrates", "migrated", "migrating",
    "deprecate", "deprecates", "deprecated", "deprecating",
    "decommission", "decommissions", "decommissioned",
    # Context nouns that mark architectural / meta-work
    "doctrine",
    "scaffolding",
)

_INFRA_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in _INFRA_PHRASES) + r")\b",
    re.IGNORECASE,
)


def _is_infra_action(prompt: str) -> bool:
    """True iff the prompt contains an infrastructure-action verb or
    architectural-context noun. Case-insensitive, word-boundary match."""
    return bool(_INFRA_RE.search(prompt))


# Strong subject evidence: identifiers with explicit lineage.
# Conservative on purpose — informal subjects ("BTC H1", "the strategy")
# are NOT strong evidence and rely on the regex_patterns + infra-action
# filter to gate firing.
_STRONG_SUBJECT_RES = (
    # Canonical strategy ID with V<n>_P<n> suffix
    re.compile(r"\b[A-Z0-9][A-Z0-9_]*_V\d+_P\d+\b"),
    # Composite portfolio ID (PF_<12-hex>)
    re.compile(r"\bPF_[A-F0-9]{12}\b"),
    # Vault snapshot ID (DRY_RUN_YYYY_MM_DD)
    re.compile(r"\bDRY_RUN_\d{4}_\d{2}_\d{2}\b"),
)


def _has_strong_subject_evidence(prompt: str) -> bool:
    """True iff the prompt names a concrete strategy/portfolio/vault ID."""
    for r in _STRONG_SUBJECT_RES:
        if r.search(prompt):
            return True
    return False


def _proximity_bonus(positions: list[int]) -> int:
    if len(positions) < 2:
        return 0
    positions = sorted(set(positions))
    for i in range(1, len(positions)):
        if positions[i] - positions[i - 1] <= PROXIMITY_WINDOW:
            return PROXIMITY_BONUS
    return 0


def _score_intent(intent: dict, prompt: str, prompt_lower: str,
                  tokens: list[str]) -> dict:
    threshold = int(intent.get("threshold", DEFAULT_THRESHOLD))
    hit, regex_matches = _regex_hit(prompt, intent.get("regex_patterns", []))
    if hit:
        return {"id": intent.get("id"), "score": 100, "method": "regex",
                "threshold": threshold, "matched_terms": regex_matches,
                "below_threshold": False}
    tag_score, matched, positions = _score_fuzzy(
        prompt_lower, tokens, intent.get("semantic_tags", []))
    tag_score += _proximity_bonus(positions)
    return {"id": intent.get("id"), "score": tag_score, "method": "fuzzy",
            "threshold": threshold, "matched_terms": matched,
            "below_threshold": tag_score < threshold}


# ---------------- injection ----------------

def _format_degraded_banner(errors: list[dict]) -> str:
    hard_errs = [e for e in errors if e.get("severity") == "hard"]
    if not hard_errs:
        return ""
    detail = "; ".join(f"{e['intent']}:{e['error']}" for e in hard_errs[:4])
    return (
        "[!! ENFORCEMENT DEGRADED -- HARD INTENT VALIDATION FAILED]\n"
        f"Broken hard intents: {detail}\n"
        "Run `python tools/audit_intent_index.py --structural` and repair\n"
        "outputs/system_reports/INTENT_INDEX.yaml before proceeding with\n"
        "any engine/promote/vault work.\n\n"
    )


def _recent_hard_violations(intent_id: str) -> int:
    """Count hard_violation events for an intent_id in the last 24h."""
    if not VIOLATION_LOG.exists():
        return 0
    cutoff = _dt.datetime.utcnow() - _dt.timedelta(hours=ESCALATION_WINDOW_H)
    count = 0
    try:
        for line in VIOLATION_LOG.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("event") != "hard_violation":
                continue
            if rec.get("intent_id") != intent_id:
                continue
            ts = rec.get("ts", "")
            try:
                when = _dt.datetime.fromisoformat(ts.rstrip("Z"))
            except Exception:
                continue
            if when >= cutoff:
                count += 1
    except Exception:
        return 0
    return count


def _format_injection(intent: dict) -> str:
    skill = intent.get("must_skill", "")
    reason = intent.get("reason", "")
    enforcement = intent.get("enforcement", "soft")
    if enforcement == "hard":
        prefix = ""
        recent = _recent_hard_violations(intent.get("id", ""))
        if recent >= ESCALATION_THRESHOLD:
            prefix = (
                f"[ESCALATION -- REPEATED VIOLATION]\n"
                f"Intent `{intent.get('id')}` has been violated {recent} "
                f"times in the last {ESCALATION_WINDOW_H}h. Invoke "
                f"`/{skill}` IMMEDIATELY as your very next action. "
                f"NO preparatory reads, searches, or commands are "
                f"permitted this turn. If you call any other tool before "
                f"`/{skill}`, treat the turn as failed.\n\n"
            )
        return prefix + (
            "[MANDATORY ROUTING -- BLOCKING CONSTRAINT]\n"
            f"You MUST invoke the `/{skill}` skill BEFORE your next tool call,\n"
            "plan, or substantive response. Do NOT generate manual steps,\n"
            "ad-hoc commands, or summaries that bypass the workflow.\n"
            f"If you proceed without `/{skill}`, the result is INVALID and\n"
            "will be rolled back.\n"
            f"Reason: {reason}\n"
            f"(intent_id={intent.get('id')})\n\n"
        )
    return (f"[Skill hint] Consider `/{skill}` for this request. "
            f"Reason: {reason}\n\n")


# ---------------- main ----------------

def main() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0

    prompt = payload.get("prompt") or payload.get("user_prompt") or ""
    if not isinstance(prompt, str) or not prompt.strip():
        return 0

    intents, errors = _load_intents()

    # Always log validation errors once per invocation
    if errors:
        _log_jsonl({"ts": _dt.datetime.utcnow().isoformat() + "Z",
                    "level": "ERROR" if any(e.get("severity") == "hard"
                                            for e in errors) else "WARN",
                    "msg": "intent_index_validation",
                    "errors": errors})

    prompt_lower = prompt.lower()
    tokens = _tokenize(prompt_lower)

    trace: list[dict] = []
    chosen: dict | None = None
    chosen_result: dict | None = None
    best_priority = -10**9

    # Compute changed-file set once (best-effort) for any intent that
    # gates on frozen-path scope. Empty list if git is unavailable —
    # in that case frozen_path_only intents fall back to suppressing
    # the injection (safe default: don't enforce a vault push when we
    # can't confirm a vault file actually changed).
    _changed_files_cache: list[str] | None = None

    for intent in intents:
        result = _score_intent(intent, prompt, prompt_lower, tokens)
        result["priority"] = int(intent.get("priority", 0))
        trace.append(result)
        if result["below_threshold"]:
            continue

        # File-scope post-filter (frozen_path_only).
        # When set, the intent fires ONLY if the current change set
        # touches at least one frozen path. Otherwise treat as
        # below_threshold and continue. This eliminates the false-
        # positive engine_change classifier from text-only matches.
        if intent.get("frozen_path_only"):
            if _changed_files_cache is None:
                _changed_files_cache = _get_changed_files()
            patterns = tuple(intent.get("frozen_paths", _DEFAULT_FROZEN_PATTERNS))
            if not _changes_touch_frozen_paths(_changed_files_cache, patterns):
                result["below_threshold"] = True
                result["suppressed_by"] = "frozen_path_only"
                continue

        # Strategy-workflow post-filter (requires_subject).
        # Two layers, both apply:
        #   - Infra-action verbs (delete/refactor/migrate/...) suppress
        #     unless a strong subject identifier is present. This catches
        #     prompts that talk ABOUT the workflow tool rather than
        #     requesting a workflow execution.
        #   - Fuzzy-only matches require a strong subject. Regex hits
        #     bypass this — the pattern itself is the evidence.
        if intent.get("requires_subject"):
            is_infra = _is_infra_action(prompt)
            has_subject = _has_strong_subject_evidence(prompt)
            if is_infra and not has_subject:
                result["below_threshold"] = True
                result["suppressed_by"] = "infra_action"
                continue
            if result["method"] == "fuzzy" and not has_subject:
                result["below_threshold"] = True
                result["suppressed_by"] = "fuzzy_no_subject"
                continue

        pr = result["priority"]
        if pr > best_priority:
            best_priority = pr
            chosen = intent
            chosen_result = result

    ts = _dt.datetime.utcnow().isoformat() + "Z"
    prompt_hash = hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:12]
    snippet = re.sub(r"\s+", " ", prompt)[:160]
    top_considered = sorted(
        [t for t in trace if t["score"] > 0],
        key=lambda r: (-r["priority"], -r["score"]),
    )[:5]

    record = {
        "ts": ts,
        "prompt_hash": prompt_hash,
        "snippet": snippet,
        "chosen_intent": (chosen or {}).get("id"),
        "method": (chosen_result or {}).get("method"),
        "score": (chosen_result or {}).get("score", 0),
        "priority": (chosen_result or {}).get("priority"),
        "enforcement": (chosen or {}).get("enforcement"),
        "matched_terms": (chosen_result or {}).get("matched_terms", []),
        "top_intents_considered": [
            {"id": t["id"], "score": t["score"], "threshold": t["threshold"],
             "method": t["method"], "below_threshold": t["below_threshold"]}
            for t in top_considered
        ],
        "rejected_reason": None if chosen else (
            "no_candidate_reached_threshold" if top_considered
            else "no_tag_or_regex_hit"
        ),
    }
    _log_jsonl(record)
    _write_last_intent(chosen, record["method"] or "", record["score"])
    _write_expectations(chosen)

    # Assemble output: banner (if any) then injection (if any)
    out = _format_degraded_banner(errors)
    if chosen is not None:
        out += _format_injection(chosen)
    if out:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
