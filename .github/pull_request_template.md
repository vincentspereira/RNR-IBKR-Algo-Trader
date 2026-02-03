<!-- Please ensure your PR follows the guidelines in CONTRIBUTING.md -->

## Description

Briefly describe the changes made in this pull request.

## Type of Change

Mark the type of change this PR introduces:

- [ ] **Bug fix** (non-breaking change which fixes an issue)
- [ ] **New feature** (non-breaking change which adds functionality)
- [ ] **Breaking change** (fix or feature that would cause existing functionality to not work as expected)
- [ ] **Documentation update** (improvements to documentation)
- [ ] **Performance improvement** (code changes that improve performance)
- [ ] **Code refactoring** (code changes that neither fix a bug nor add a feature)
- [ ] **Tests** (addition or modification of tests)
- [ ] **Infrastructure/CI** (changes to CI/CD, Docker, deployment)

## Context

Why is this change needed? What problem does it solve?

## Changes Made

List the key changes:

- [ ] 
- [ ] 
- [ ] 

### Code Quality

- [ ] Code follows project style guidelines (Black, isort, mypy)
- [ ] All tests pass: `pytest tests/ -v`
- [ ] Test coverage >= 95%: `pytest tests/ --cov --cov-report=term-missing`
- [ ] Pre-commit hooks pass: `pre-commit run --all-files`

### Documentation

- [ ] Code is well-documented with docstrings
- [ ] AGENTS.md has been updated (if this changes operational workflows)
- [ ] README.md has been updated (if this affects user-facing features)
- [ ] API documentation updated (if API changes)

## Testing

### Tests Added/Modified

- [ ] Unit tests added for new functionality
- [ ] Integration tests added for new functionality
- [ ] All existing tests still pass

### Manual Testing

Describe how this was tested manually:

```bash
# Paste commands used for manual testing
```

## Performance Impact

- [ ] This change improves performance
- [ ] This change has no performance impact
- [ ] This change may impact performance (explain below)

If performance is impacted, provide benchmarks:

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Metric 1 | X ms | Y ms | +/- Z% |
| Metric 2 | X ops/s | Y ops/s | +/- Z% |

## Breaking Changes

If this PR introduces breaking changes, describe them here and provide migration instructions:

- 

## Security Considerations

- [ ] No security implications
- [ ] Security implications (describe below)
- [ ] Requires security review before merge

## Related Issues

Closes #<issue_number>
Related to #<issue_number>

## Screenshots/Visuals

If this change affects UI/UX, include screenshots or diagrams:

![Before](before.png)
![After](after.png)

## Checklist

Before submitting, please ensure:

- [ ] PR title follows conventional commit format: `type(scope): description`
- [ ] Code style guidelines are followed (Black, isort, mypy, pylint)
- [ ] All tests pass locally with `pytest tests/ -v`
- [ ] Test coverage meets threshold (>=95%)
- [ ] Pre-commit hooks pass with `pre-commit run --all-files`
- [ ] Self-review completed and code is well-organized
- [ ] Documentation has been updated (if applicable)
- [ ] No new warnings or errors introduced
- [ ] Commit messages follow conventional commits format

## Additional Notes

Any additional information that reviewers should know:

---

**Note**: By submitting this PR, you agree to follow the project's [Code of Conduct](CODE_OF_CONDUCT.md) and [Contributing Guidelines](CONTRIBUTING.md).
