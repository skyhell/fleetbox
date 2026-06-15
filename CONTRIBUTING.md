# Contributing to FleetBox

Thanks for your interest in improving FleetBox!

## Getting started

See [docs/development.md](docs/development.md) for the local setup.

## Guidelines

- **Language:** code, comments, commit messages and documentation are written in
  **English**. Only the user-facing UI strings (in `app/locales/`) are
  translated to German and English.
- **Style:** run `ruff check app tests` and `ruff format app tests` before
  committing.
- **Tests:** add or update tests under `tests/` and make sure `pytest` passes.
- **Translations:** when you add a UI string, add the key to **both**
  `app/locales/de.json` and `app/locales/en.json`.

## Pull requests

1. Fork and create a feature branch.
2. Keep changes focused and add tests.
3. Ensure CI (lint + tests) is green.
4. Describe the change and the motivation in the PR description.

## Reporting issues

Please include your installation method (Proxmox / Docker / bare metal),
the FleetBox version (see the footer), and steps to reproduce.
