## 2026-09-06 — Criticism Is Unnecessary Because It Is Inevitable

Today began with what looked like a failed database question.

The user asked a simple and useful question: which hospital has the longest queue for a cardiologist? The answer should include not only the department, but above all the hospital and its location.

GAARD did not simply fail to find data. In fact, it found quite a lot. It discovered cardiology-related service categories, executed ranking queries, connected the winning value to a provider and facility, and produced evidence that could be independently rerun. Yet Radar refused the answer.

The first technical cause was embarrassingly ordinary. GAARD returned a result truncated to its configured limit of 1,000 rows. Radar independently executed the same SQL without applying the same limit and obtained 9,418 rows. It then compared both lists for exact equality:

```text
GAARD: 1,000 rows
Radar: 9,418 rows
Result: fatal mismatch
```

Nothing was wrong with the data. The verifier had compared two executions with different semantics.

That bug was easy to understand and relatively easy to fix. The more interesting failure happened one layer above it.

## The system had an answer and talked itself out of it

GAARD had used one query to establish a maximum and another query to identify the provider associated with that value. A human looking at the evidence sees a perfectly normal analytical chain:

```text
query A establishes the maximum
query B identifies the owner of that maximum
therefore the answer is supported
```

The critic saw something else:

```text
the final lookup query does not calculate the maximum by itself
therefore the answer may not be sufficiently proven
```

This was technically defensible and practically destructive.

The critic ignored the accumulated evidence and evaluated the final SQL as if it were required to reproduce the entire investigation in one statement. Its objection triggered another investigation. That investigation introduced a new temporal assumption, selected the global maximum observation date, encountered rows in which the relevant measure was null, and eventually caused the system to reject an answer it had already found.

At first, the obvious response was to make the critic less powerful. We replaced its veto with a network of cognitive signals. Each component could emit a short statement, a confidence value, a criticism or limitation, and references to evidence. An integrator would see the whole chain rather than obeying one adversarial opinion.

This was an improvement, but it did not yet remove the underlying error. The critic no longer had a formal veto, yet its doubt still dominated the next action. It had become one weighted input among several, but it was still being asked to search for a problem.

That question itself was the mistake.

## An LLM asked for doubt will produce doubt

A language model asked, “What could be wrong with this answer?” will almost always find something.

This is not evidence that a problem exists. It is evidence that the model is following its instruction.

The distinction matters. A critic is not passively detecting an objective defect. It is generating the most plausible continuation under a critical role. Even a strong answer can always be challenged:

- the final query could be written differently;
- a newer period might exist;
- another interpretation might be possible;
- an intermediate value could be recalculated;
- the evidence could be presented more elegantly;
- one more verification might increase confidence.

Every new investigation produces more observations. Every new observation creates more possible qualifications. A system organized around the elimination of all possible doubt does not converge. It expands the surface on which doubt can be generated.

This is the model's inner imperative: when assigned the role of critic, it must criticize. The absence of a material defect does not terminate the role. It merely forces the criticism to become more subtle.

The conclusion from today's work is therefore stronger than “the critic should have a lower weight.”

**The global critic is unnecessary because criticism is inevitable.**

Uncertainty, conflict and limitation already appear naturally in every meaningful component. We do not need a privileged agent whose purpose is to invent them.

## From judgment to accounting

The replacement is not another judge. It is a deterministic accounting mechanism.

The user's question is first decomposed into a dynamic set of atomic success criteria. For example:

1. identify the relevant service;
2. establish the value that determines the result;
3. associate that value with a hospital;
4. provide the requested department;
5. provide the requested location;
6. establish the applicable data period.

The exact criteria are not hard-coded. Another question—such as which departments experienced the largest increase in waiting time over six months—must produce a different card. The runtime knows nothing about cardiology, hospitals or time series. It knows only that a question produced a set of requirements, that the requirements carry weights, and that evidence may or may not cover them.

Each useful result is then reduced to an atomic statement:

```json
{
  "criterion_id": "c3",
  "statement": "The provider associated with the selected result was identified.",
  "value": "Wojskowy Instytut Medyczny – PIB",
  "coverage": 1.0,
  "confidence": 0.98,
  "evidence_refs": ["query:164"]
}
```

The integrator does not ask whether this looks convincing. It calculates whether the required criteria are covered by material evidence:

```text
score = Σ(weight × coverage × evidence quality × effective confidence)
```

If every required criterion is sufficiently covered, the answer is released. If something is missing, the next investigation must be derived from that exact gap. There is no open invitation to invent a new concern.

A criticism may still exist, but it has to become an atomic, evidence-bearing claim. “The SQL could be better” is a diagnostic note. It cannot block an answer. “Another verified record in the same comparison has a larger value” is a material contradiction. It can block the affected criterion because it points to actual evidence.

This shift matters: the system no longer tries to prove that no objection can be imagined. It proves that the requirements of the question have been covered.

## The first success exposed the next failure

After removing the global critic from the termination path, Radar finally completed the cardiology question instead of rejecting it.

Mechanically, the new runtime behaved as designed:

- it created a goal card;
- GAARD supplied evidence;
- the deterministic integrator calculated 0.8 coverage;
- one specific gap remained: evidence that the selected value was the maximum;
- a second investigation addressed only that gap;
- the score reached 1.0;
- the answer was released without a global critic reopening the case.

This was an important success.

The answer was also semantically wrong.

Radar had transformed the Polish phrase *najdłuższa kolejka*—the longest queue—into “the longest wait time.” GAARD narrowed it further to `forecast_waiting_days`, the predicted time until the first available appointment. It then used a broad text filter matching every service name containing “kardiolog,” which included cardiac rehabilitation. The resulting answer reported 30 days for a cardiac rehabilitation department in Legionowo.

The database contained at least three different defensible values:

- 352 for the largest number of waiting patients;
- 246 for the largest provider-reported average waiting time;
- 30 for the largest forecast waiting time in a broader set that included rehabilitation.

These are valid answers to three different questions.

The system confidently answered the third question. The human had asked the first.

The deterministic integrator had made no arithmetic mistake. It had perfectly verified a coherent evidence chain for a meaning that had silently drifted away from the original words.

## Determinism cannot repair lost meaning

This failure clarified the next architectural boundary.

A flat checklist is not enough. It can confirm that a hospital, value, department, location and maximum were all found, while failing to preserve what was being maximized and what “cardiologist” meant in the user's question.

The runtime needs semantic continuity from the original phrase to the final field and record.

That does not mean introducing a permanent domain ontology into Radar. We must not add fixed fields for hospitals, waiting times, medical specialties or observation policies. Such a schema would solve today's question and constrain tomorrow's.

Instead, the goal representation must preserve the user's original semantic anchors:

```json
{
  "source_text": "kolejka",
  "resolved_meaning": null,
  "status": "unresolved"
}
```

The available data may then reveal several candidate meanings:

```text
waiting_patient_count
provider_average_waiting_days
forecast_waiting_days
```

If those interpretations lead to materially different answers, the system must not silently select one. It must either ground the choice in evidence and language, present the alternatives, or ask the user to clarify.

The same principle applies to “do kardiologa.” Radar's candidate search had already found precise categories such as `ODDZIAŁ KARDIOLOGICZNY` and `ODDZIAŁ KARDIOLOGICZNY DLA DZIECI`. Yet the resolver discarded them because those dictionary records did not also contain the hospital and queue length.

That was the same category error at an earlier stage. A dictionary finding does not need to answer the whole question. It only needs to resolve its local uncertainty. By discarding it, Radar sent GAARD no confirmed data references, and GAARD fell back to the much broader `LIKE '%kardiolog%'`.

Useful local knowledge was found, then rejected for not being a complete global answer.

## What changed today

Today's work produced several concrete improvements:

- independent SQL verification now understands truncated results instead of treating 1,000 and 9,418 rows as contradictory;
- a failed supporting query no longer destroys previously confirmed evidence;
- later iterations no longer automatically erase an earlier valid candidate;
- criticism is represented as a signal rather than a veto;
- Business Logic findings can be evaluated for temporary use within an investigation without becoming globally enabled rules;
- the global critic was removed from the normal completion decision;
- the answer decision is now calculated from a weighted goal card and evidence coverage;
- a continuation must point to a specific missing criterion;
- technical JSON variations can be normalized without repeatedly calling an LLM;
- the runtime completed a case that previously collapsed into self-rejection.

Just as importantly, the successful mechanics exposed the next problem cleanly:

- semantic interpretation can drift before evidence accounting begins;
- input references, analytical operations and requested outputs are still confused during grounding;
- useful dictionary candidates can be discarded because they do not contain the final result;
- independent criterion values can form a complete-looking but semantically incoherent answer;
- verified SQL proves that a query returned a value, not that the query represents the user's meaning.

This is progress. A failure that moves from uncontrolled orchestration to a precise semantic boundary is a much better failure.

## The emerging runtime

The architecture emerging from this work is not a traditional agent workflow and not a chain of increasingly skeptical judges.

It is a network of small cognitive units. Each unit contributes a compact statement, confidence, limitation and evidence. A dynamic goal card defines what must be established. A deterministic integrator measures coverage. Investigation continues only where knowledge is missing. Previously verified knowledge remains available unless material contradictory evidence appears.

No single LLM decides whether the whole answer is good.

The LLMs perform the work they are good at:

- understanding language;
- proposing semantic decompositions;
- mapping observations to local questions;
- formulating concise findings;
- interpreting evidence within a bounded responsibility.

The runtime performs the work that must remain governable:

- preserving state;
- tracking provenance;
- normalizing weights;
- calculating coverage;
- enforcing completion thresholds;
- preventing speculative objections from becoming obligations;
- ensuring that later steps cannot silently erase earlier knowledge.

The next step is to preserve semantic identity through that structure: from the exact words used by the user, through candidate meanings and database fields, to one coherent answer candidate. The integrator must calculate completeness for that candidate, not assemble unrelated values merely because each fills a box.

## Final note

The most useful lesson today was not that criticism is bad. Criticism is everywhere.

Every uncertain mapping contains criticism. Every confidence below one contains criticism. Every limitation attached to a finding contains criticism. Every material contradiction in evidence contains criticism. Every uncovered criterion is already a precise criticism of the current answer.

A dedicated global critic adds little information. What it adds is pressure to continue.

That pressure is dangerous because a language model can always satisfy it. There is always another possible doubt, another reformulation, another query, another interpretation and another way to demand a stronger proof.

A governable cognitive runtime should not ask a model when it feels satisfied. It should know what the user asked, know which parts have been established, know what evidence supports them, and stop when the defined work is complete.

Criticism does not need a special seat at the table.

It is already present in every empty chair.


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
