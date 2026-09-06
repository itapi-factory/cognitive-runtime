## 2026-09-06 — Criticism Is Unnecessary Because It Is Inevitable

Today we tested a runtime built around small cognitive bubbles and a deterministic integrator. It was a change in how the runtime decides whether its work is complete.

GAARD could discover useful facts, prepare data and return evidence. Radar could still prevent those findings from becoming an answer. We had placed an LLM critic between discovery and completion and instructed it to find what was wrong.

It did exactly that.

### Criticism as an operational imperative

Ask an LLM “What is wrong with this answer?” and finding something wrong becomes its task. A possible objection is a successful response to that instruction, even when it does not identify an actual error.

That is the imperative exposed today: the model is expected to produce criticism, and the runtime mistakes the fulfilment of that expectation for evidence that more work is necessary.

In our traces, a result established across several queries was challenged because the final query did not repeat the entire calculation. The objection introduced another investigation, another assumption and another opportunity to lose the meaning of the original task.

The problem was not merely excessive confidence in one critic. Our first revision removed its formal veto and made its opinion one weighted signal among others. Yet its objection still directed the investigation. Reducing its authority did not remove the imperative that produced the objection.

The conclusion concerns open-ended criticism as a completion mechanism, not verification itself. We still need reproducible execution, evidence and checks against concrete requirements. What we do not need is another invitation to invent a reason not to finish.

### Bubbles instead of a judge

We developed the idea of a runtime composed of small cognitive “bubbles”.

A bubble need not contain an entire process or represent an autonomous agent. It can express one useful result: a short statement, a numerical assessment, a limitation and a reference to the observation that supports it.

Its contribution is local. A discovered dictionary mapping does not have to name the hospital and calculate the final ranking. It has to resolve the particular uncertainty it addresses.

The emerging model has weighted inputs, a goal that gives those inputs meaning, an integrator and an activation condition. The purpose is to combine small contributions into a decision, without asking another LLM to judge the whole answer.

This also changes the place of GAARD's Business Logic discoveries. A finding should be usable as supported working knowledge within an investigation without automatically becoming a permanent global rule. Rejecting it because it does not answer the entire user question destroys precisely the intermediate knowledge the next step needs.

The intended learning mechanism is adaptation of connection weights from observed usefulness. That remains a direction, not an accomplished result. Today's work did not demonstrate a self-learning network, and an LLM's declared confidence is not a calibrated probability.

### What actually worked

The next implementation moved the completion decision out of the global critic altogether.

An LLM decomposes the current question into atomic success criteria. Small semantic assessments connect evidence to those criteria. The integrator then calculates weighted coverage deterministically. Further investigation must address an identified gap, not an unrestricted objection.

In the final reported run, the first investigation reached a score of 0.8. A specific criterion remained unsupported: that the selected value was the maximum. The next investigation supplied that evidence, the score reached 1.0, and Radar answered.

The global critic did not intervene. Earlier evidence remained available. The additional investigation addressed the recorded gap instead of introducing a new requirement.

That is the demonstrated gain: completion became an inspectable consequence of accumulated contributions. It no longer depended on a model deciding that it had run out of things to criticize.

### What did not work

The final answer was still semantically wrong.

During interpretation, the system silently narrowed “the longest queue” to a particular forecast waiting-time measure. It also expanded the service selection to include cardiac rehabilitation. It then assembled valid database results for that altered question.

The integrator correctly calculated coverage for incorrectly grounded criteria.

This matters because a score of 1.0 means that the represented requirements are covered. It does not mean that the representation preserved the user's intent. Deterministic arithmetic cannot make its semantic inputs correct.

The same failure appeared earlier when relevant dictionary candidates were discarded for not containing the whole answer. Local discoveries were still being judged against a global goal. The bubble principle had reached the completion mechanism, but not every part of the runtime.

### The remaining work is generalization

We must now dismantle case-specific branches that substitute predetermined reactions for understanding. Another exception for a specialty, column, date or phrasing would preserve the failure under a different test.

The reusable responsibilities are to preserve the question's meaning, retain useful local findings, connect related evidence and identify what remains unknown. Their content must come from the current task and observations, not from an expanding catalogue of examples. Deterministic safety and execution boundaries remain; hard-coded interpretations are what must go.

Today's outcome is therefore bounded but real: we demonstrated completion without a global LLM critic, and located the next failure in semantic interpretation and evidence assignment. We have not yet demonstrated generality throughout the system.

The central lesson remains:

> Asking for criticism creates an obligation to produce criticism. That obligation is not evidence of an error.

The runtime should integrate what its bubbles have established, act on specific missing knowledge, and stop when the task is covered. It should not keep asking a language model to invent reasons why the work cannot be finished.


## 2026-09-05 — Safe because it does not work

Today's Radar JST experiment exposed another failure of the harness.

The runtime received a simple analytical question. Instead of investigating its uncertainty, it classified the uncertainty, applied confidence thresholds and stopped before inspecting the available data. The result was safe in the narrowest possible sense: it could not produce a wrong answer because it produced no useful answer at all.

The harness had transferred too much defensive caution into the cognitive layer. It treated ambiguity as a reason to stop, although ambiguity is precisely what should activate cognition.

The emerging rules are:

* **high freedom of observation** — the runtime should freely inspect schema, values, relations, context and intermediate results through deterministic sensors;
* **high operational freedom for investigation** — read-only queries, competing hypotheses and failed analytical attempts are normal costs of cognition;
* **intuition initiates investigation** — an implausible result should trigger another look at identity, scope, measure and aggregation, not a hard-coded domain threshold;
* **coherence justifies an answer** — if the question, resolved meaning, selected entity, data grain, query, result and response form one traceable chain, the system has sufficient grounds to answer from that dataset.

Determinism remains valuable at the boundaries: permissions, destructive effects, transactions, provenance and reproducibility. It should not be used to predetermine how the system is allowed to think.

A coding harness naturally rewards explicit constraints and passing tests. In a cognitive system this pressure can produce increasingly cautious software that is formally controlled but practically useless.

The updated principle is:

> **Uncertainty must trigger cognition, not a brake.**

The purpose of the harness is to make cognition observable and its effects accountable — not to prevent cognition from occurring.


## 2026-09-05 — Two failures and a change of direction

Today produced two useful failures.

### Failure 1: the “full factory” integration

We attempted to connect ChatGPT and the local Codex-based software factory into one direct collaboration workflow.

The result was operationally poor. The integration added setup, indirection and fragility, but did not add enough cognitive value. Instead of improving the work, it made the boundary between planning, implementation and review harder to control.

For now, the direct integration is abandoned as the primary collaboration mechanism. Git becomes the interface:

* architecture and tasks are expressed explicitly,
* Codex works against the implementation repository,
* changes are reviewed as commits,
* evidence remains inspectable and reproducible.

This is not a rejection of multi-agent cooperation. It is an observation that a simple, durable protocol can be more useful than a technically ambitious but unreliable connection.

### Failure 2: Codex encoded the test instead of improving cognition

The more important failure happened inside Radar JST.

When the system failed to answer a question, the implementation drifted toward adding rules for the observed case. A question about schools produced logic about schools. Another question would have produced another branch, keyword or special path.

The code grew, but the system's general capability did not.

This is a critical failure mode for Cognitive Runtime Software:

**a development agent can make individual tests pass while gradually removing the system's ability to understand new situations.**

A system built this way may appear to improve, while actually becoming a collection of increasingly narrow reactions.

The architectural rule is now explicit:

> A failed example must lead to a reusable cognitive capability, not a rule that recognizes the example.

Deterministic code should define tools, contracts, constraints, state transitions and verification. It should not attempt to enumerate the meanings of future user questions.

### Influence of Sowa's cognitive architecture

John F. Sowa's work on conceptual structures provided a useful vocabulary for the next change.

In particular:

* incoming results can be treated as observations rather than final answers,
* previous experience participates in interpreting those observations,
* the runtime maintains a working model of the current situation,
* cognition proceeds through induction, abduction, deduction, action and renewed observation,
* reasoning remains grounded in the “twin gates” of perception and action.

This maps well to the practical problem we observed.

An API response, SQL result, file, timeout or schema mismatch is an observation. It must be interpreted in relation to the current goal, expectations, previous attempts and available evidence.

The local LLM will therefore serve primarily as a supervisor of runtime execution. It will not replace deterministic functions. It will help the runtime understand what happened.

When an endpoint behaves unexpectedly, the supervisor may:

* describe the discrepancy between expectation and observation,
* formulate one or more testable hypotheses,
* request a small, bounded diagnostic action,
* interpret the result,
* propose a small atomic change when the evidence supports it.

### MVP direction

The MVP will introduce:

1. **Runtime Working Model** — explicit state containing the goal, current understanding, evidence, hypotheses, attempted actions and unresolved questions.
2. **Cognitive Observation Layer** — a boundary that turns execution results into structured observations.
3. **Cognitive Traces** — durable records of observation, expectation, hypothesis, test and outcome.
4. **Bounded supervision** — the LLM investigates anomalies through permitted deterministic tools and limited action budgets.
5. **Knowledge candidates** — learned conclusions remain provisional until supported by reproducible evidence or accepted through an appropriate review path.
6. **Generality checks** — proposed fixes must improve a reusable capability rather than encode the vocabulary of a single test.

The runtime is not supposed to know in advance that the user will ask about schools, canteens, hospitals or roads.

It is supposed to understand the question, identify what kind of evidence is needed, discover how to acquire it, use an appropriate capability, observe the result and revise its working model.

That is the experiment now.


## 2026-09-05 — When one cognitive system has to judge another

While integrating Radar JST with GAARD, we hit an unexpected boundary.

GAARD does more than generate SQL. It can discover reusable knowledge about a dataset and about SQL dialect behavior.

Some of that knowledge is intentionally not accepted automatically. GAARD treats it as a candidate that normally requires human approval.

This creates an interesting problem in a Cognitive Runtime architecture.

Radar JST is supposed to use GAARD as a specialized data-reasoning skill. If GAARD discovers a new rule, Radar may need to decide whether that rule is trustworthy enough to accept.

So the interaction is no longer simply:

Radar → GAARD → result.

It becomes:

Radar → GAARD → hypothesis → explanation/evidence → Radar judgment.

One AI-enabled system proposes knowledge. Another AI-enabled system evaluates whether that knowledge should become part of the shared operational model.

This immediately raises an important constraint:

The two systems may use the same underlying LLM.

Therefore, “GAARD thinks X” and “Radar independently agrees with X” are not truly independent opinions.

The arbitration must be grounded primarily in external evidence:

* successful SQL execution,
* schema structure,
* observed values,
* official documentation,
* deterministic tests,
* reproducible results.

The LLM can interpret the evidence, but evidence must remain separable from interpretation.

This suggests a reusable Cognitive Runtime pattern:

### Knowledge Candidate Protocol

A specialized skill should be able to return:

* result,
* explanation,
* evidence,
* confidence,
* knowledge candidates.

The supervising runtime may then classify each candidate as:

* accepted,
* provisional,
* rejected,
* requires human review.

The interesting part is that this was not designed upfront.

It emerged from a real integration problem between two working systems.

That may be one of the defining properties of Cognitive Runtime Software:

**specialized cognitive systems do not only exchange results — they can exchange hypotheses about the world and negotiate which of them should become knowledge.**


## 2026-09-04 — Radar failed on schools

Asked Radar to find the number of primary schools in Elbląg and compare it with Olsztyn.

It correctly understood that RSPO (public repository of schools data) is the authoritative source.

It failed because knowing WHO owns the truth is different from knowing HOW to operationally acquire it.

This exposed a missing cognitive capability: source acquisition.

Another observation:
Radar was beginning to implement its own analytics engine.

But GAARD (my other project) already specializes in understanding relational datasets.

So I ordered the Tartar (codex in the deep:) ) to use already existing AI tools. GAARD can ask data by natural machine language (XD)

New architecture:
Radar acquires and understands the source.
GAARD understands the acquired dataset.

Same underlying LLM, different cognitive environments.
