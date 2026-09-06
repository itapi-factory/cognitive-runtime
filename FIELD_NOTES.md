## 2026-09-06 — Criticism Is Unnecessary Because It Is Inevitable

Today we moved Radar's completion decision from an LLM critic to deterministic integration of small, evidence-backed contributions.

The change grew out of a recurring failure. GAARD discovered useful facts and delivered the data needed to build an answer. Radar then asked another LLM to find problems with that answer. The resulting objections triggered further investigation, sometimes displacing findings that had already been established.

### The critic was doing its job

The crucial observation was about the instruction itself.

Ask an LLM “What is wrong?” and finding something wrong becomes the requested output. There is always another possible interpretation, another qualification or another way to demand more proof. The model can fulfil its task without discovering an actual contradiction.

In this role, the model “must” criticize: criticism is what we have instructed it to produce. That is its operational imperative. We were treating the fulfilment of that imperative as evidence that the analysis was incomplete.

One objection concerned a result established through several queries: the final query did not repeat the whole calculation. The runtime let that observation create a new obligation, although the earlier evidence was still available.

Our first response was to remove the critic's veto and make its opinion one weighted input among others. That changed its formal authority, but its objections still steered the investigation. Another LLM acting as integrator could adopt the same doubt and continue the loop.

The necessary change was to stop asking for an unrestricted judgment at the point of completion.

### The bubble model

We developed the runtime as a network of small cognitive bubbles.

A bubble represents a local contribution: a short statement, a numerical assessment, supporting evidence and any relevant limitation. It does not have to be an entire agent or solve the whole task.

The model brings together weighted inputs, a goal that gives them meaning, integration and an activation condition. A finding contributes according to what it establishes for the current goal. The combined contributions determine whether to act, continue investigating or produce an answer.

For example, discovering how a dataset represents a term is useful before any final result exists. That finding resolves a local unknown. Demanding that it also contain the complete answer defeats the purpose of dividing cognition into small contributions.

This applies directly to GAARD's Business Logic discoveries. They need a path into the investigation as supported working knowledge, with permanent acceptance handled separately. Today's traces showed that this local-versus-global distinction was still not respected consistently.

The longer-term idea is to strengthen or weaken connections according to their demonstrated usefulness in reducing goal-relevant ignorance. We have not yet demonstrated that learning mechanism. Declared confidence alone would not be an adequate learning signal.

### What the implementation demonstrated

The revised runtime builds a dynamic set of success criteria from the user's question. Local LLM assessments associate findings with those criteria. A deterministic integrator then calculates weighted coverage.

The LLM still interprets meaning. It no longer supplies the global verdict.

In the final run, the first investigation left one recorded gap. The second addressed that gap, earlier evidence remained available, and the runtime completed the answer without calling a global critic.

That is the concrete gain from today: further work became attributable to a specific missing contribution, and completion followed from the accumulated state. We could inspect why the system continued and why it stopped.

Verification remains necessary. It must establish what an observation supports, rather than invite an unlimited search for conceivable objections.

### What the final answer exposed

The completed answer was still wrong.

The system had silently selected a narrower interpretation of the requested measure and a broader interpretation of the relevant services. It then correctly calculated a result for that altered question.

The integrator counted the supplied contributions correctly. The meaning supplied to it was wrong.

This is the limit of today's result. Deterministic integration makes the decision reproducible; it does not make LLM interpretation infallible. The bubbles must preserve their relationship to the original question and to each other. Useful local discoveries must survive the journey between components.

### What follows

The remaining case-specific branches must be dismantled and generalized into reusable capabilities. Encoding one more service name, column choice or phrasing would only teach the software to recognize another example.

The runtime needs general mechanisms for retaining observations, relating contributions and identifying unresolved meaning. Safety, permissions and execution remain deterministic boundaries. The meaning of future questions cannot be enumerated in conditional code.

Today's progress is a tested separation of responsibilities: local models contribute meaning and evidence; the runtime integrates those contributions and determines completion. Semantic continuity and adaptive connection weights remain unfinished work.

The central result is this:

> A model's ability to produce criticism is not evidence that criticism was needed.

Giving it the job of finding objections makes objections an expected product. Completion must depend on what the cognitive bubbles have established, not on whether another LLM can invent a reason to keep going.


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
