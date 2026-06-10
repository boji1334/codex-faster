## Summary

Describe the change.

## Verification

- [ ] `python -m py_compile patch.py inject_models.py fast_search.py tests/test_patch_platform.py`
- [ ] `python -m unittest discover -s tests`
- [ ] `python patch.py --help`
- [ ] Windows launcher checked if touched
- [ ] macOS/Linux launcher checked if touched
- [ ] README updated if behavior changed

## Safety

- [ ] No API keys, tokens, auth files, session files, or extracted app files committed
- [ ] Filesystem deletion paths are bounded and documented
