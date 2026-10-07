# Architecture Decision Records

An ADR records one important design decision: the context, what was decided, and why. Code shows *what* was built; ADRs keep the *why*, so neither a person nor an agent "fixes" something that was deliberate.

## Index

| # | Decision | Status |
|---|---|---|
| [0001](0001-ui-free-core-with-thin-streamlit-ui.md) | A UI-free core package with a thin Streamlit UI | accepted |
| [0002](0002-local-single-user-sqlite-no-login.md) | A local single-user app on SQLite, with no login but a `user_id` on every row | accepted |
| [0003](0003-model-judges-code-computes.md) | The model judges, code computes: a two-tier evaluation | accepted |
| [0004](0004-judge-from-another-family-median-of-three.md) | The final judge comes from another model family and runs three times | accepted |
| [0005](0005-layered-injection-guard.md) | A layered prompt-injection guard: answers are blocked, documents are flagged | accepted |

Smaller, dated decisions are in the [decision log](../decision-log.md); the current design as a whole is in the [design spec](../04-design-spec.md).

## When to write one

Write an ADR only when all three are true: the decision is **hard to reverse**, a future reader would find it **surprising** without context, and it was a **real trade-off** between genuine alternatives. Everything else is a one-line row in the decision log.

## How

- Name the file `NNNN-short-slug.md`, numbered one above the highest existing file.
- Start with a frontmatter `status` (`proposed`, `accepted`, `deprecated` or `superseded by NNNN`) and a `date`, then a title and one short paragraph: context, decision, reason. Add **Considered Options** or **Consequences** only when they say something non-obvious.
- Never rewrite the decision of an accepted ADR. To change your mind, write a new ADR and set the old one's status to `superseded by NNNN`, so the history of the reasoning stays readable.
- Add the ADR to the index above and a one-line row pointing at it in the decision log.
