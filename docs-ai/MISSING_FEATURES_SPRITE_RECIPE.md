## Missing or Incomplete Features for Sprite Recipe

This document tracks the gaps for a pipeline recipe that:

- loads a base art description from file,
- loads sprite assets from CSV,
- generates prompts with an LLM,
- generates sprites,
- removes background with validation,
- and writes outputs to a flat folder while updating `.gitignore`.

### Missing

- **Load base art description from a file into pipeline context.**
  - Current pipelines only accept context values inline in YAML (`context:`). There is no built-in step or config to read a text file into `context` for template usage.

### Incomplete

- **Background removal validation in the pipeline.**
  - The `remove_background` executor only removes the background and saves the result. Validation of transparency (alpha channel + transparency percentage) exists in tests only and is not enforced during execution.

