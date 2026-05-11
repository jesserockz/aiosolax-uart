# Contributing to aiosolax-uart

Thanks for your interest! This is a small async library for talking to SolaX
inverters over UART — contributions are very welcome.

## Before opening a pull request

1. Read and sign the [Contributor License Agreement](CLA.md) — once your first
   PR is open the CLA bot will leave a comment with the one-liner you reply
   with to sign.
2. Open an issue first if your change is more than a small fix. Bigger changes
   (new inverter family decoders, protocol additions, breaking API shifts) are
   easier to land if we agree on the shape upfront.

## Dev setup

```bash
git clone https://github.com/jesserockz/aiosolax-uart
cd aiosolax-uart
uv sync                       # install deps into .venv
uv run pre-commit install     # install pre-commit hooks (ruff, yamllint, pytest)
uv run pre-commit install --hook-type pre-push   # optional pre-push hook
```

That's it — the venv is ready and any `git commit` will run the linting + test
suite locally.

## Running things

```bash
uv run pytest                                                # tests
uv run pytest --cov=aiosolax_uart --cov-report=term-missing  # coverage report
uv run ruff check .                                          # lint
uv run ruff format .                                         # auto-format
uv run pre-commit run --all-files                            # full pre-commit
```

## Adding support for a new inverter

The library is built to grow protocol family by family. If your inverter
isn't in [`MODELS`](src/aiosolax_uart/models.py) yet:

1. Run a small script that opens a `SolaxClient` against your inverter and
   prints `await client.get_device_info()`. The interesting field is
   `inverter_model_code`.
2. Open an issue with the model code and the inverter's product name (off the
   sticker on the side of the unit).
3. If you can, attach a hex dump of a full `await client.get_live_data()`
   response captured at a moment when you know what the battery / AC values
   ought to be — that lets us verify the field offsets.

Hybrid-family decoders in particular are still unverified. If you have hybrid
hardware, capturing a few labelled live-data frames is the single most useful
thing you can contribute.

## Style

- Type hints everywhere; `mypy --strict` should pass.
- Docstrings in Google style on public API and on anything non-trivial. Tests
  don't need full docstrings.
- 100% test coverage is the goal — new code should land with tests, and CI
  will report coverage on every PR.
- Conventional-commit-style PR titles (`feat:`, `fix:`, `chore:`, etc.) so
  Release Drafter can categorise them automatically in the changelog.

## Releases

Releases are automated:

1. PRs merged into `main` trigger `release-drafter` which maintains a draft
   release with a calculated next version (major/minor/patch based on PR
   labels) and attaches a fresh build of the dist.
2. When a maintainer publishes the draft via the GitHub UI, the
   [`publish.yml`](.github/workflows/publish.yml) workflow uploads the
   attached dist to PyPI via OIDC Trusted Publishing.

You don't need to bump versions or build anything manually.
