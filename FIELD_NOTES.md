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
