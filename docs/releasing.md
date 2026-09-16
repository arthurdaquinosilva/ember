# Releasing

ember is published to PyPI as **`ember-shell`** (the name `ember` was already taken); the installed command is `ember`.

Releases are built and uploaded by GitHub Actions (`.github/workflows/release.yml`) using PyPI **trusted publishing**, so no API token is stored anywhere.

## One-time setup

1. Create an account on [pypi.org](https://pypi.org/account/register/) and enable two-factor authentication.
2. Go to **Your account → Publishing → Add a new pending publisher** and fill in:
   - PyPI project name: `ember-shell`
   - Owner: `arthurdaquinosilva`
   - Repository name: `ember`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
3. On GitHub, open **Settings → Environments → New environment**, name it `pypi`. Optionally add yourself as a required reviewer so every upload needs a click.

The first successful release creates the project on PyPI and turns the pending publisher into a normal one.

## Cutting a release

1. Bump `version` in `pyproject.toml` and `__version__` in `src/ember/__init__.py`.
2. Add the changes to `CHANGELOG.md`.
3. Check the build locally:

   ```sh
   rm -rf dist && python -m build && python -m twine check --strict dist/*
   ```

4. Commit, push, then create a GitHub release with a `vX.Y.Z` tag:

   ```sh
   gh release create v0.2.0 --title "v0.2.0" --notes-file <(sed -n '/## 0.2.0/,/## 0.1.0/p' CHANGELOG.md | sed '$d')
   ```

Publishing the release runs the workflow, which builds the sdist and wheel, checks them, and uploads to PyPI. Afterwards:

```sh
pipx install ember-shell   # or: pip install ember-shell
```

## Trying a release first (optional)

To rehearse on [TestPyPI](https://test.pypi.org), add a pending publisher there too and upload manually with a TestPyPI token:

```sh
python -m twine upload --repository testpypi dist/*
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ ember-shell
```
