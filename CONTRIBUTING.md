# Contributing to YouTube Downloader

Thank you for considering contributing to YouTube Downloader! This document outlines the process and guidelines for contributing.

## How to Contribute

### Reporting Bugs

1. Check if the bug has already been reported in [Issues](https://github.com/yourusername/youtube-downloader/issues)
2. If not, create a new issue with:
   - Clear title and description
   - Steps to reproduce
   - Expected vs. actual behavior
   - Your environment (OS, Python version, yt-dlp version)
   - Relevant logs (remove sensitive information!)

### Suggesting Features

1. Check if the feature has been suggested in [Issues](https://github.com/yourusername/youtube-downloader/issues)
2. If not, create a new issue with:
   - Clear title and description
   - Use case / problem it solves
   - Proposed solution (if you have one)

### Pull Requests

1. **Fork the repository**

2. **Create a feature branch:**
   ```bash
   git checkout -b feature/your-feature-name
   ```

3. **Make your changes:**
   - Follow the code style (see below)
   - Add tests if applicable
   - Update documentation if needed

4. **Test your changes:**
   ```bash
   # Install dev dependencies
   pip install -e .[dev]

   # Run tests
   pytest

   # Format code
   black src/

   # Lint
   ruff check src/
   ```

5. **Commit your changes:**
   ```bash
   git commit -m "Add feature: your feature description"
   ```

   Use conventional commits:
   - `feat:` - New feature
   - `fix:` - Bug fix
   - `docs:` - Documentation changes
   - `style:` - Code style changes (formatting)
   - `refactor:` - Code refactoring
   - `test:` - Adding/updating tests
   - `chore:` - Maintenance tasks

6. **Push to your fork:**
   ```bash
   git push origin feature/your-feature-name
   ```

7. **Create a Pull Request:**
   - Fill out the PR template
   - Link related issues
   - Wait for review

## Code Style

- **Python:** Follow PEP 8
- **Formatting:** Use Black (automatic with `black src/`)
- **Linting:** Use Ruff (check with `ruff check src/`)
- **Type hints:** Use type annotations where reasonable
- **Docstrings:** Use Google-style docstrings for public functions/classes

Example:
```python
def download_video(url: str, quality: str = "best") -> bool:
    """Download a video from YouTube.

    Args:
        url: YouTube video URL
        quality: Quality selector for yt-dlp

    Returns:
        True if download succeeded, False otherwise

    Raises:
        ValueError: If URL is invalid
    """
    pass
```

## Development Setup

1. **Clone your fork:**
   ```bash
   git clone https://github.com/yourusername/youtube-downloader.git
   cd youtube-downloader
   ```

2. **Create virtual environment:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows
   ```

3. **Install in development mode:**
   ```bash
   pip install -e .[dev,plex]
   ```

4. **Run tests:**
   ```bash
   pytest
   ```

## Testing

- Write tests for new features
- Ensure existing tests still pass
- Aim for good code coverage
- Test with different configurations (auth enabled/disabled, Plex enabled/disabled, etc.)

## Documentation

- Update README.md if you add new features or change behavior
- Update docstrings for modified functions/classes
- Add examples for new CLI commands

## Commit Message Guidelines

Good commit messages help reviewers understand your changes:

**Good:**
```
feat: add support for playlist downloads

- Add --playlist flag to CLI
- Update DownloadManager to handle playlists
- Add tests for playlist functionality
```

**Bad:**
```
update stuff
```

## Questions?

- Open a discussion in [Discussions](https://github.com/yourusername/youtube-downloader/discussions)
- Reach out in existing issues
- Be respectful and patient - maintainers are volunteers!

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
