# The Story of Engram

Engram is an open-source memory *brain* for AI agents. It came together from two lineages that turned out to be the same idea seen from two sides.

One was a structured-knowledge engine: fold verified, source-cited facts about an entity into a compact, weighted, semantically-indexed object an agent can consume. The other was an agent's working memory: free-form notes that get richer the more they're used — found by theme and by the *questions they answer*, linked by use, strengthened by recall, and quietly forgotten when neglected.

Merging them produced a single substrate where anything you attach — text or structured data — becomes memory that:

- is indexed from **multiple perspectives at once** (its themes, the questions it answers, the names it goes by);
- grows an **association graph** from how it's actually used (spreading activation surfaces what's linked by use, not just by meaning);
- **strengthens with retrieval and decays without it** — importance emerges from use, not assignment;
- can be **scoped to a project** and **distilled** (a corrected memory ranks below its replacement without erasing it).

It tries to behave the way memory actually *feels* — inspired by Tony Buzan's work on radiant, associative thinking and by the lived human experience of remembering.

**Engram** — the engine is **100% coded by AI (Claude)**, from the inspiration and direction of its human author (David Dand). The vision and the ideas are human; every line of code is the AI's. (For the release-by-release history, see [`CHANGELOG.md`](CHANGELOG.md); for where it's going, [`ROADMAP.md`](ROADMAP.md).)

## Honest status

Experimental, and **untested in long trials.** The open question we most want help with is how retention and retrieval hold up over weeks and months of real use. If you run it, tell us what your brain remembered and what it forgot.
