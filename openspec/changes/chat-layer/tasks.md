# Tasks

## 1. Console routes for the model

- [ ] 1.1 `/day/{date}.json` and `/questions.json` in `domestique.web` with the same data as the HTML pages; test: fixture day returns the rail wording and the question text verbatim in JSON

## 2. Chat service

- [ ] 2.1 `src/domestique/chat/modes.py`: load `skills/*.md` verbatim as system prompts with the config prefix; test: a mode's prompt ends with the file's exact content and starts with the prefix
- [ ] 2.2 `src/domestique/chat/tools.py`: the static allow-list, HTTP tools against the console, MCP tools against the claims server; test: the gated tool names are absent from the list the model receives
- [ ] 2.3 `src/domestique/chat/check.py`: `check_layers`; test: labelled bullets pass, an unlabelled bullet is returned as a fragment, tool-sourced rail wording is exempt
- [ ] 2.4 `src/domestique/chat/app.py`: Chainlit app with mode selection, the SDK tool loop, the retry-then-mark behaviour of the check; test: with a fake model client, an unlabelled reply is retried once and then shown marked

## 3. Containers

- [ ] 3.1 `chat/Dockerfile` and the `chat` service in `docker-compose.yml` (loopback port, `ANTHROPIC_API_KEY` and `DOMESTIQUE_HUMAN_TOKEN` absent, `/data` named volume, depends on `app`), `UID` build argument on both images, `just chat`; test: compose config shows no human token in the chat service environment and a non-root user in both images
- [ ] 3.2 `docs/stack.md`, `README.md`: the three services and what each may touch
