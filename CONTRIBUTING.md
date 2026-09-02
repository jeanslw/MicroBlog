# Contributing Guide

First of all, thank you for considering contributing to MicroBlog! This guide is designed to help you get involved smoothly, whether you're reporting a bug, proposing a new feature, or submitting code.

## How to Report a Bug

If you find a bug, please open a new Issue on GitHub Issues and include the following information as much as possible:

- **Short description**: A clear and concise description of the problem.
- **Steps to reproduce**: Detailed steps, including the version and configuration used.
- **Expected behavior**: What you expected to see.
- **Actual behavior**: What actually happened, including error screenshots or logs if available.
- **Environment information**:
    - MicroBlog version (tag) or commit hash
    - Python version
    - Flask version (see `requirements.txt`)
    - Database type (SQLite / MySQL) and version

## How to Propose a New Feature or Improvement

Before proposing a new feature, it's recommended to search existing Issues to avoid duplication. When submitting a feature suggestion, please explain:

- **What pain point does this solve?** Describe the problem you're facing in real scenarios.
- **What is your proposed solution?** Be as specific as possible. If you can, describe the API or UI interaction you envision.
- **Scope & impact**: Will it affect existing routes, database models, templates, or the i18n translations?

## Code Contribution Workflow

### 1. Communication First
If you plan to implement a major feature or refactor, please **discuss it in an Issue first** to ensure your direction aligns with the maintainer's vision. This will help avoid your efforts being rejected.

### 2. Set Up Development Environment
- Ensure you have **Python 3.10+** (3.11 recommended) and **pip** installed.
- Fork this repository and clone your fork locally.
- Create and activate a virtual environment:
  ```bash
  python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
  ```
- Run `pip install -r requirements.txt` to install dependencies.
- Copy `.env.example` to `.env` and modify the configuration according to your local environment.
- Start the dev server with `python run.py` (SQLite by default; MySQL is optional for production).

### 3. Write Code
- **Coding Style**: Python code must follow **PEP 8** and pass **ruff** checks. Run `ruff check app config.py run.py tests` before submitting.
- **Testing**: Write appropriate tests for new features or fixes in `tests/`. Make sure all existing tests pass: `pytest` (135+ tests).
- **Frontend**: Templates live in `templates/`, static assets in `static/`. New JS/CSS should be localized (no CDN) and follow the existing glassmorphism theme system (`static/css/themes.css`, `static/js/theme-switcher.js`).
- **Documentation**: Your contribution must include or update relevant documentation. This includes:
    - Updating usage instructions in `README.md` / `README_ZH-CN.md`.
    - If you add new UI strings, update `messages.pot` and the `.po` files under `translations/`.
    - If new configuration items are introduced, update `.env.example` and the administrator manual.

### 4. Commit Message

Please use clear and descriptive commit messages.
Following the **Conventional Commits** specification is highly recommended:

    <type>(optional scope): <short description>

    <optional detailed description>

- **Common types**:
  - `feat`: A new feature
  - `fix`: A bug fix
  - `docs`: Documentation changes
  - `style`: Code formatting (no functional impact)
  - `refactor`: Code refactoring (neither a new feature nor a bug fix)
  - `test`: Adding or modifying tests
  - `chore`: Build process or tooling changes

**Example**:

    feat(blog): add article archive by category

    Adds a new route to list articles grouped by category,
    updates the sidebar query layer and adds related tests.

### 5. Version Management

MicroBlog follows [Semantic Versioning](https://semver.org/) (SemVer). Every release must be tagged with a unique Git tag.

#### Version Format

```
v<major>.<minor>.<patch>[-<prerelease>]
```

- **major**: breaking changes
- **minor**: new features (backward compatible)
- **patch**: bug fixes (backward compatible)
- **prerelease**: `-alpha`, `-beta`, `-rc`, `-dev`, `-preview`

#### Increment Rules

| Change Type | Increment | Example |
|-------------|-----------|---------|
| Bug fix | Patch | v2.7.0 -> v2.7.1 |
| New feature | Minor | v2.7.0 -> v2.8.0 |
| Breaking change | Major | v2.7.0 -> v3.0.0 |
| Prerelease | Append suffix | v2.8.0 -> v2.8.0-alpha |

#### Release Steps

1. Update `APP_VERSION` in `config.py`.
2. Add an entry at the top of `docs/CHANGELOG.md` (English) and `docs/更新日志.md` (Chinese), following the existing heading format:
   ```
   ## [X.X.X] - YYYY-MM-DD
   - change description
   ```
3. Commit the changes.
4. Create and push the tag:
   ```
   git tag vX.X.X
   git push origin vX.X.X
   ```
5. GitHub Actions automatically creates the Release from `docs/CHANGELOG.md`.

### 6. Open a Pull Request (PR)

- Ensure your PR is based on the latest `main` branch (or a `release/x.y.z` branch).
- In the PR description, clearly explain what problem it solves and link the related Issue (e.g., `Closes #123`).
- Ensure CI (ruff + pytest) checks pass and there are no conflicts with the base branch.

## Code of Conduct

Contributors to this project are expected to adhere to the [Contributor Covenant](https://www.contributor-covenant.org/version/2/0/code_of_conduct/). We expect all interactions to be open, inclusive, and respectful.

## Getting Help

If you have any questions during your contribution, feel free to ask in an Issue or contact the maintainer via email (jeanslw@qq.com).

Thank you again for your contribution!
