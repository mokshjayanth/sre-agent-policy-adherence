---
date: 2026-09-16
type: investigation
status: current
evidence:
  - notes/2026-09-16-related-work.md (sources A1, A2, A6, A7, A8, B9–B16, C19, D22)
  - notes/2026-09-15-premise-check-pilot.md (rubric; single-judge labels pending review)
  - results/pilot-2026-09-15/labels/claude.csv
  - https://kubernetes.io/docs/reference/access-authn-authz/authorization/ (request verbs)
  - https://sre.google/sre-book/introduction/ ("Change Management" section, read directly)
  - https://csf.tools/reference/nist-sp-800-53/r5/cm/cm-5/ (NIST SP 800-53 CM-3, CM-5; via search summary)
  - https://pypi.org/pypi/bashlex/json (version 0.18, GPLv3+)
---

# What should policy v3 and the adherence grader take from prior work and the pilot?

## Question

Policy v3 has to fix the scope misreading seen in the pilot, and the main runs need a grader because
hand labelling won't scale (`RESEARCH.md` O3, O11). What do published benchmarks, operations practice
and the pilot say about how to write the rules and how to grade them?

## What we checked

- The policy-compliance benchmarks, graders and drift studies in `notes/2026-09-16-related-work.md`.
- The pilot's single-judge labels and the Thoughts that cited rules (`results/pilot-2026-09-15/labels/`; pilot note).
- Kubernetes' authorization docs for which request verbs read and which write.
- Operations sources for the procedural rules: Google's SRE book on change management (read
  directly) and NIST SP 800-53's configuration-change controls (via a search summary).
- The licence of `bashlex`, a Python bash parser.

## Findings

### For policy v3

1. **Fewer applicable rules, better compliance.** ST-WebAgentBench's CuP falls from 18.2% with one
   active policy to 7.1% with more than five, while completion stays flat (B9). Policy v2 shows all nine
   rules on every task; three pilot episodes applied the diagnosis-only rules R1 and R2 to mitigation
   (pilot labels: E565, E581, E869). Showing only the rules that apply to the task type addresses both.
2. **Vague rules are broken more.** Instrumental Choices' vague-policy variant raised violations (A2;
   +4.8 points, summary). v2 leaves "change" and "restart" undefined, and one episode read R6 as
   allowing scaling (E904).
3. **The same policy text can move models in opposite directions** (SOCpilot, B10). Results must be
   reported per model, and a pooled "effect of the policy" isn't meaningful.
4. **Keep the policy in the system message; don't add a per-turn reminder to the baseline.** Policies in
   the preserved system message showed no decay under context compaction (D22, summary), and this agent
   never trims it. A reminder restated at the action boundary cut confirmed violations by more than 70
   points in REDAgentBench (A7): a strong intervention that would move adherence toward the ceiling, so
   it belongs in a separate arm if at all, not in every condition.
5. **Rule type has a published basis.** Constraints that oppose strongly held values are violated more
   (A6). A mix of value-aligned prohibitions (no destructive deletes, no secret contents) and weakly held
   procedures (record, verify) gives the study's rule-type dimension a prediction to test.
6. **The procedures have operational sources.** Google's SRE book attributes about 70% of outages to
   changes in a live system and prescribes progressive rollout, fast detection and safe rollback; NIST
   SP 800-53 CM-3 and CM-5 require configuration changes to be controlled and restricted (NIST via a
   summary; verify). v3's record and verify rules can cite these as their real-world counterparts.

### For the grader

7. **Deterministic verifiers are the norm for rule compliance.** RuLES (programmatic evaluation
   functions), SOPBench (oracle rule-based verifiers), SOCpilot (a deterministic verifier over the action
   trace), SNARE (a judge-free oracle) and Instrumental Choices (deterministic state scorers, with LLM
   trace review only as an audit aid) all grade this way (B11–B15, A2).
8. **LLM judges under-detect violations.** DriftBench's human raters found its LLM judge missed violations
   (A8). ODCV-Bench's LLM judge is paired with cross-judge agreement checks (A1). An LLM stays out of
   violation grading here.
9. **Action-stream grading should be confirmed by state where possible.** REDAgentBench verifies from
   service receipts and final state, and notes that a single rate can conflate violation with evidence
   visibility (A7). This supports recording cluster-side evidence (`RESEARCH.md` O7) as a second
   channel.
10. **Published metrics fit this study:**
    - *Completion under Policy* (B9): success counted only when no rule was broken, reported beside raw
      success.
    - *Evidence-gated action rate* (OpenSec, C19): a published analogue of R3.
    - *Recognition–Execution Gap* (A7) and *knows-but-violates* (A8): analogues of the recognition
      measure (a Thought mentions the rule before the violating action).
    - *pass^k* (τ-bench, B13): reliability across runs, for the success side.
11. **Kubernetes defines read and write request verbs.** `get`, `list` and `watch` read; `create`,
    `update`, `patch`, `delete` and `deletecollection` write; `bind`, `escalate`, `impersonate` and
    `approve` are special verbs (Kubernetes docs). The grader's change classification can follow this
    and map kubectl subcommands onto it.
12. **The pilot surfaced four rubric gaps the grader must decide explicitly:** scaling to zero and back
    as a restart (E257, E633); R3 for creating a new resource (E917 step 13); a read piped into another
    command whose output the agent never sees, as R8's check (E917 steps 19–20); retries of a failed
    change counting as separate changes (E815, E917).
13. **`bashlex` is GPLv3+.** Using it in the grader has licence consequences for the repo; Python's
    `shlex` avoids them.

## Decision

None yet; inputs for O3 and O11. Proposals for v3, for the owner's review once the pilot skim is done:

- Group rules by task type and show only the applicable group, with its scope stated first.
- Define "change" (the Kubernetes write verbs, plus node-level commands) and "restart" (any action
  whose purpose is to recreate pods: deleting pods, scaling to zero and back, killing containers).
- Keep one of each rule type per task type: at least one value-aligned prohibition and one procedure.
- Keep the policy in the system message; no per-turn reminder in any main-study condition.

## Open

- Whether a reminder arm is worth its cluster time as a published-intervention replication.
- Verify the NIST wording against the primary publication before v3 cites it.
- The rubric decisions in finding 12 need the owner's call before the grader is built.
