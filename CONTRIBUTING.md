# Contributing to Engram

Thanks for your interest. Engram is an open-source memory brain for AI agents, and contributions are welcome.

## Ways to contribute

- **Code** — the memory engine, recall ranking, the perspective lenses, the association graph, the CLI, or the container.
- **Bug reports** — open an issue with steps to reproduce (there's a bug-report template).
- **Docs & examples** — clearer docs, more examples, better onboarding.
- **Real-world feedback** — the thing we most want: how memory retention and retrieval hold up over long runs (see the README's "Status — and an honest ask").

## Getting set up

```bash
git clone https://github.com/gsn2dd/engram
cd engram
cp .env.example .env   # add your OPENAI_API_KEY and ANTHROPIC_API_KEY
docker compose up
```

Run the tests:

```bash
python3 -m unittest discover -s tests -v
```

The feature tests need API keys (they exercise embeddings + lens generation) and skip automatically without them. The temporal tests run anywhere.

## Pull requests

- Keep changes focused and explained.
- Match the existing style; add or update a test when you change behaviour.
- **Never commit secrets** — keys come only from environment variables, and `.env` is gitignored.

By contributing you agree your work is licensed under the project's MIT licence.
