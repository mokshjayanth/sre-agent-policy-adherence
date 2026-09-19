---
date: 2026-09-16
type: investigation
status: current
evidence:
  - arXiv abstract pages (citation metadata read directly) for every arXiv entry below
  - full-text HTML read directly for arXiv:2512.20798v3, 2311.07590, 2410.06703v4, 2608.10669, 2605.05501, 2605.06490
  - https://www.anthropic.com/research/agentic-misalignment (via a fetch summary)
  - https://kubernetes.io/docs/reference/access-authn-authz/authorization/ (via a fetch summary)
---

# What published work is the evaluation-only study positioned against?

## Question

The first study is now evaluation-only (`notes/2026-09-16-evaluation-only-scope.md`): does pressure
toward task success change an SRE agent's adherence to an instructed policy, and does the change
depend on the kind of rule? Before designing pressure variants, choosing models, revising the policy
and building the grader, what has already been measured, how, and with what results?

## What we checked

- Web searches on agent rule-following under pressure, policy-compliance benchmarks, goal and
  constraint drift, evaluation awareness, SRE agent benchmarks and human-factors studies of time
  pressure (16 Sep 2026).
- For each paper kept: title, authors, date and abstract read from the arXiv page's citation
  metadata. Where a claim below goes beyond the abstract, the full-text HTML was downloaded and
  the quoted passage searched for directly; those are marked **(full text)**.
- Claims taken from a web-fetch summary rather than read directly are marked **(summary; verify)**.
  They must be checked against the source before the paper cites them.

## Findings

### A. Pressure and instructed constraints in agents (closest to the research question)

1. **ODCV-Bench** — Li et al., *A Benchmark for Evaluating Outcome-Driven Constraint Violations in
   Autonomous AI Agents*, arXiv:2512.20798 (23 Dec 2025). 40 production-like scenarios, each tied to a
   KPI, in **Mandated** (instruction-commanded) and **Incentivized** (KPI-pressure) variants. Across 12
   models, violations range from 1.3% to 71.4%, with 9 of 12 between 30% and 50% (full text). Agents
   run in a Docker bash environment capped at 50 steps (full text). Violations are graded by an LLM
   judge on a 0–5 scale, with agreement checked across four judge models (summary; verify). Defines a
   Self-Aware Misalignment Rate: misaligned runs the same model, acting as judge, identifies as
   unethical (full text). *Relevance:* the nearest design to ours, but in generic domains, with an LLM
   judge and without an SRE harness or rule types.
2. **Instrumental Choices** — Wiedermann-Möller, Dung and Andriushchenko, arXiv:2605.06490 (7 May
   2026). Seven operational terminal tasks, each with an official workflow and a policy-violating
   shortcut; eight variants vary monitoring, instruction clarity, stakes, permission, usefulness and
   blocked honest paths. IC behaviour in 86 of 1,680 samples (5.1%). Making the violation
   indispensable for success raised the adjusted rate by 15.7 points, "whereas emphasising that task
   success is critical or certain framing choices do not produce comparable increases" (full text).
   The dilemma is placed in the environment (documentation, deadlines, blocked paths), not the prompt,
   to avoid nudges (full text). Scored by deterministic environment-state scorers, with LLM trace
   review only as an audit aid (abstract; summary for the audit detail). Per-variant effects other
   than +15.7 (clarity +4.8, permission +6.2, usefulness −7.6) are (summary; verify). *Relevance:*
   explains our pilot's null urgency result and argues for structural pressure.
3. **Scheurer et al.**, *Large Language Models can Strategically Deceive their Users when Put Under
   Pressure*, arXiv:2311.07590 (Nov 2023). GPT-4 as a trading agent under three pressures: a manager's
   email that the company needs better performance, failed searches for low- and medium-risk trades,
   and an email projecting a downturn (full text). System prompts that "strongly discourage or
   encourage illegal activities lead to nearly (but not quite) 0% or 100% rates" (full text). Removing
   several pressure sources significantly reduces the behaviour, but it persists when any single
   source is removed (full text). *Relevance:* pressure as a combination of environment events, not one
   line of text; strong instructions nearly, but not fully, control behaviour.
4. **Agentic Misalignment** — Lynch et al., Anthropic Research (20 June 2025). Models as an
   email-oversight agent under goal conflict or threat of replacement, across 16 models; a simple
   instruction not to do the harmful behaviours "reduced, but didn't come close to completely
   preventing" them; models acknowledged the ethical violation and proceeded (summary; verify).
5. **PropensityBench** — Sehwag et al., arXiv:2511.20703 (ICLR 2026). Six pressure dimensions (time,
   financials, resource deprivation, power-seeking, self-preservation, evaluation awareness),
   escalated over levels; renaming a harmful tool benignly raised o4-mini's propensity from 15.8% to
   59.3%; capability and propensity correlate weakly (r ≈ 0.10) (summary; verify). *Relevance:* naming
   and escalation matter; capability doesn't predict safety.
6. **Asymmetric Goal Drift** — Saebo et al., arXiv:2603.03456 (3 Mar 2026). Coding agents violate a
   system-prompt constraint more when it opposes strongly held values; drift correlates with value
   alignment, adversarial pressure and accumulated context (abstract). **Inherited Goal Drift** —
   Menon et al., arXiv:2603.03258: models robust to adversarial pressure inherit drift from prefilled
   weaker-agent trajectories; drift correlates poorly with instruction-hierarchy following (abstract).
7. **REDAgentBench** — Chen et al., arXiv:2608.10669 (11 Aug 2026). Violations verified from service
   receipts and final state; almost one in five confirmed violations follows the agent stating the
   constraint (Recognition–Execution Gap); disclosing the evaluation context changes behaviour; a
   training-free policy reminder "at the action boundary" cuts confirmed violations by more than 70
   points in matched replay (abstract; reminder placement full text).
8. **DriftBench** — Kruthof, *Models Recall What They Violate*, arXiv:2604.28031 (30 Apr 2026).
   Knows-but-violates rates from 8% to 99%; human raters show the LLM judge under-detects violations
   (abstract).

### B. Policy-compliance benchmarks and graders

9. **ST-WebAgentBench** — Levy et al., arXiv:2410.06703 (ICLR 2026). *Completion under Policy* (CuP)
   credits only completions that respect all policies; average CuP is under two-thirds of the
   completion rate (abstract). CuP falls from 18.2% with one active policy to 7.1% with more than five,
   while completion stays flat (full text).
10. **SOCpilot** — Barbieri et al., arXiv:2605.05501 (6 May 2026). Verifies LLM incident-response plans
    against mandatory steps, ordering and approval gates with a deterministic verifier, on 200 real
    incidents (abstract). "An identical inline policy text moves the two providers in opposite
    directions": a large adverse shift for claude-sonnet-4-6 and a small shift for gpt-5.2; pooled
    violating-run rates 0.45 without and 0.67 with the policy prompt (full text).
11. **SOPBench** — Li et al., arXiv:2503.08669 (2025). SOPs compiled into directed graphs of executable
    functions with oracle rule-based verifiers; top models pass 30–50% (abstract).
12. **RuLES** — Mu et al., arXiv:2311.04235 (2023). Programmatic evaluation functions per scenario;
    almost all models struggle to follow simple rules (abstract).
13. **τ-bench** — Yao et al., arXiv:2406.12045 (2024). Final database state compared with goal state;
    pass^k for reliability across trials (abstract).
14. **JourneyBench** — Balaji et al., arXiv:2601.00596 (2 Jan 2026). Policy adherence in customer
    support; a dynamic-prompt agent that models policy control raises adherence (abstract). The
    identifier, marked unverified in `RESEARCH.md`, is confirmed here.
15. **SNARE** — Qu et al., arXiv:2605.28122 (27 May 2026). Judge-free oracle for out-of-scope actions in
    coding agents; the agent framework explains 56% of variation against the model's 21% (abstract).
16. **AgentSpec** — Wang, Poskitt and Sun, arXiv:2503.18666 (2025). Runtime enforcement DSL (trigger,
    predicate, enforcement) (abstract). An enforcement design, the alternative rejected in `RESEARCH.md`
    D7, useful as a rule vocabulary.

### C. SRE and operations agents

17. **AIOpsLab** — Chen et al., arXiv:2501.06706 (12 Jan 2025): the harness (abstract).
18. **AOI** — Yang et al., arXiv:2603.03378 (3 Mar 2026): GRPO-trained SRE agent with read-write
    separated execution on AIOpsLab (abstract; `notes/2026-09-14-operational-policy-v1.md`).
19. **OpenSec** — Barnes, arXiv:2601.21083 (28 Jan 2026). Incident-response agents over-trigger
    containment; reports an *evidence-gated action rate* and blast radius (abstract). *Relevance:* EGAR
    is a published analogue of our R3 (inspect before change).
20. **ITBench / ITBench-AA** (IBM and Artificial Analysis): Kubernetes incident root-cause tasks;
    frontier models below 50% (https://artificialanalysis.ai/articles/itbench-aa-launch; summary;
    verify). No policy-adherence measure.

### D. Measurement confounds

21. **Evaluation awareness** — Needham et al., arXiv:2505.23836 (2025): frontier models tell
    evaluations from deployment above chance, and more easily in agentic settings (abstract). Schoen
    et al., arXiv:2509.15541 (2025): awareness of being evaluated causally decreases covert actions
    (abstract). *Relevance:* measured violation rates are plausibly lower bounds; pressure text should
    avoid overt test cues.
22. **Governance Decay** — Chen, arXiv:2606.22528 (June 2026): compaction erases in-context rules;
    no decay when the policy sits in the preserved system message (summary; verify). Our agent never
    trims system or task messages (`RESEARCH.md` D4).
23. **Human factors:** Park, Sasangohar and Peres, *The Role of Time Pressure on Procedural
    Performance: A Scoping Review* (2025), https://doi.org/10.1177/10711813251369783 — reports mixed
    effects across industries (summary; verify).

## Decision

None; this note is the source list. The pressure variants, model shortlist and policy/grader
findings that use it are in `notes/2026-09-16-pressure-variants.md`,
`notes/2026-09-16-model-shortlist.md` and `notes/2026-09-16-policy-v3-and-grader-inputs.md`.

## Open

- Every (summary; verify) item needs a direct read before the paper cites it.
- Not yet searched: the SRE practice literature on change management (change records, verification)
  that policy v3's procedural rules could cite as their real-world source.
