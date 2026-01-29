Y# CLI-First Development Plan

**Created:** January 29, 2026  
**Status:** Planning

---

## Project State Assessment

### What's Built and Working

| Component | Status | Notes |
|-----------|--------|-------|
| **Gemini Image Provider** | ✅ Working | Successfully generated 40 images in test run |
| **Gemini Text Provider** | ✅ Working | Name/text generation functional |
| **Pipeline Orchestrator** | ✅ Working | Multi-step execution, auto-approve mode |
| **Input Parsers** | ✅ Working | text, CSV, JSON, JSONL formats |
| **Background Removal** | ✅ Working | rembg integration in sprite pipeline |
| **Project State** | ✅ Working | progress.jsonl persistence |
| **REST API** | ✅ Working | Full CRUD + processing endpoints |
| **WebSocket** | ✅ Working | Real-time updates for interactive mode |
| **Frontend UI** | 🔶 Partial | Basic wizard flow, needs polish |
| **CLI** | ✅ Working | Full CLI-first workflow implemented |

### What's Fixed (Previously NOT CLI-Ready)

From the User Experience Report (Jan 26, 2026) - **ALL RESOLVED**:

1. ~~**No Direct CLI Generation**~~ → ✅ `artgen <file>` works directly without server
2. ~~**No Progress Feedback**~~ → ✅ Rich progress bars during generation
3. ~~**Undocumented Batch Mode**~~ → ✅ CLI mode is auto-approve by default
4. ~~**Style Config Not Respected**~~ → ✅ `--style` flag applies to all prompts

### Current CLI Commands

```bash
# Core Generation
artgen <file>                  # ✅ Direct generation from input file
artgen <file> --transparent    # ✅ Generate sprites with transparency
artgen <file> --style "..."    # ✅ Apply style to all prompts
artgen <file> -n 4             # ✅ Generate multiple variations

# Project Management
artgen init                    # ✅ Initialize new project
artgen status                  # ✅ Show project and API status
artgen list                    # ✅ List assets with status
artgen show <id>               # ✅ Show asset details

# Pipeline Control
artgen run <step> <file>       # ✅ Run specific step on input
artgen resume                  # ✅ Continue pending/failed assets

# Interactive Mode
artgen interactive             # ✅ Launch browser UI
```

---

## CLI-First Goals

The goal is to make this workflow seamless:

```bash
# Simple generation
artgen birds.txt

# With options
artgen birds.txt --style "pixel art, 16-bit" --variations 4

# Sprites with transparent backgrounds
artgen units.txt --transparent --output ./sprites

# Full batch with auto-approve
artgen cards.csv --auto --variations 4 --provider gemini-pro
```

**No server required.** Direct execution, progress bars, results.

---

## Implementation Plan

### Phase 1: Direct CLI Generation (Priority: HIGH)

**Goal:** `artgen <file>` works end-to-end without starting a server

#### 1.1 Fix `cmd_generate` in artgen.py
- [x] Basic structure exists
- [ ] Wire up to Pipeline Orchestrator directly (not via HTTP)
- [ ] Add proper async execution with rich progress
- [ ] Support all pipeline step types

```python
# Target implementation
async def cmd_generate(args):
    # Load items from file
    items = parse_input_file(args.file)
    
    # Create temporary project or use cwd
    project = await Project.load_or_init()
    
    # Process each item through pipeline
    with Progress(...) as progress:
        for item in items:
            asset = await project.create_asset(item)
            await orchestrator.process_asset(asset, auto_approve=True)
            progress.advance(task)
    
    print_summary(results)
```

#### 1.2 Add CLI Options
```bash
--output, -o      Output directory (default: ./outputs)
--style, -s       Style prompt to apply
--variations, -n  Number of variations (default: 1)
--provider, -p    Image provider (gemini, gemini-pro, dalle)
--transparent     Auto-remove backgrounds
--auto            Auto-approve all steps (default for CLI)
--parallel        Parallel generation count (default: 1)
--verbose, -v     Show detailed output
--dry-run         Show what would be generated without calling APIs
```

#### 1.3 Progress Display
```
  AI Art Generator

  ✓ Using env: ~/.config/artgen/.env
  ✓ Loaded 10 items from units.txt
  ✓ Output: ./outputs

  Generating...
  [████████████████░░░░░░░░] 7/10  Quantum Archer...
  
  ✓ Done! 10 items generated (40 images)
  ✗ 1 item failed: Bio-Titan (rate limited)
  
  Output: /home/user/project/outputs
```

### Phase 2: Pipeline CLI Commands (Priority: MEDIUM)

**Goal:** Fine-grained control over pipeline execution

#### 2.1 New Commands

```bash
# Run specific pipeline step
artgen run generate_sprite --input units.txt

# Continue from where we left off
artgen resume

# Show detailed status of items
artgen list
artgen list --status failed

# Regenerate specific item
artgen regenerate item-007

# Approve/reject from CLI (for interactive use)
artgen approve item-007 --select 2
artgen reject item-007 --reason "wrong colors"
```

#### 2.2 Pipeline Step Selection
```bash
# Only run certain steps
artgen birds.txt --steps generate_image,remove_background

# Skip steps
artgen birds.txt --skip research
```

### Phase 3: Configuration CLI (Priority: MEDIUM)

**Goal:** Configure projects without editing JSON

```bash
# Set style
artgen config style --prefix "pixel art, 16-bit"
artgen config style --suffix "transparent background"

# Set provider
artgen config provider --image gemini-pro
artgen config provider --text claude

# Set pipeline
artgen config pipeline --preset sprites
artgen config pipeline --add remove_background

# Show current config
artgen config --show
```

### Phase 4: Testing & Quality (Priority: HIGH)

**Goal:** Comprehensive test coverage for CLI mode

#### 4.1 Unit Tests
- [x] Test `parse_input_file` with all formats (test_parsers.py)
- [x] Test CLI argument parsing (test_cli.py)
- [x] Test progress display (via integration tests)
- [x] Test error handling (test_cli.py)

#### 4.2 Integration Tests (Mock API)
- [x] Test full `cmd_generate` flow with mocked providers (TestGenerateCommand)
- [x] Test resume functionality (TestResumeCommand)
- [x] Test `artgen run` functionality (TestRunCommand)
- [ ] Test parallel generation

#### 4.3 Live Tests
- [x] Test with real Gemini API (marked with `@pytest.mark.live`)
- [x] Test background removal pipeline
- [x] Test multi-step pipeline

**Status: MOSTLY COMPLETE** (Jan 29, 2026)

Test suite: 90 tests passing
- test_cli.py: 33 tests (CLI commands)
- test_parsers.py: 13 tests (input parsing)
- test_api.py: 17 tests (REST API)
- test_image_utils.py: 11 tests (image processing)
- test_interactive.py: 16 tests (interactive mode)

### Phase 5: Documentation (Priority: MEDIUM)

- [ ] Update README with CLI-first examples
- [ ] Add `artgen --help` examples
- [ ] Document all CLI options
- [ ] Add troubleshooting section

---

## Technical Decisions

### 1. Direct vs Server Mode

**Decision:** CLI mode runs directly, no server.

The current `cmd_generate` tries to use providers directly. We should:
- Keep this approach for simple generation
- Use `PipelineOrchestrator` for multi-step pipelines
- Add `--serve` flag if user wants server mode

### 2. Project State in CLI Mode

**Decision:** Auto-initialize if no project exists.

```python
if Project.exists():
    project = await Project.load()
else:
    # Create minimal project for this run
    project = await Project.init(config=ProjectConfig(
        name="CLI Generation",
        pipeline=[default_pipeline_for_args(args)]
    ))
```

### 3. Output Organization

**Decision:** Use consistent output structure.

```
./outputs/
├── item-001/
│   ├── generate_image_v1.png
│   ├── generate_image_v2.png
│   └── metadata.json
├── item-002/
│   └── ...
└── summary.json
```

### 4. Error Handling

**Decision:** Fail gracefully, continue by default.

```python
# Don't stop on single failure
try:
    await process_item(item)
except Exception as e:
    failed.append((item, e))
    if args.strict:
        raise
    continue
```

---

## File Changes Required

### Backend Files to Modify

| File | Changes |
|------|---------|
| `backend/artgen.py` | Major rewrite of `cmd_generate` |
| `backend/pipeline/orchestrator.py` | Add CLI-friendly methods |
| `backend/app/models.py` | Add CLI-specific config options |
| `backend/providers/base.py` | Ensure async works without server |

### New Files to Create

| File | Purpose |
|------|---------|
| `backend/cli/commands.py` | Refactored CLI commands |
| `backend/cli/progress.py` | Rich progress display helpers |
| `backend/cli/config.py` | CLI configuration management |
| `backend/tests/test_cli.py` | CLI-specific tests |

---

## Success Criteria

### Phase 1 Complete When:
- [x] `artgen birds.txt` generates images directly
- [x] Progress bar shows during generation
- [x] Output organized in `./outputs/item-XXX/`
- [x] Works without any server running

**Status: COMPLETE** (Jan 29, 2026)

Tested successfully with:
```bash
python artgen.py ../test-cli.txt --env ../.env.local -o ../test-outputs -v
# Generated 2 items → 2 images in ~15 seconds

python artgen.py ../test-cli.txt --env ../.env.local -o ../test-outputs-v2 -n 2 -v
# Generated 2 items → 4 images (2 variations each) in ~32 seconds
```

### Phase 2 Complete When:
- [x] `artgen run <step>` works
- [x] `artgen resume` continues failed runs
- [x] `artgen list` shows all items with status
- [x] `artgen show <id>` shows asset details

**Status: COMPLETE** (Jan 29, 2026)

All Phase 2 commands implemented and tested:
- `artgen list` - Shows assets with status, supports filtering (`--status`, `--limit`)
- `artgen show <id>` - Shows detailed asset information
- `artgen resume` - Continues processing pending/failed assets (`--failed-only`)
- `artgen run <step>` - Run specific pipeline step on input files or project assets
  - Supports all step types: generate_image, generate_sprite, generate_name, generate_text, research, remove_background
  - Can run on input files or existing project assets
  - Supports `--asset <id>` to run on specific asset

### Phase 3 Complete When:
- [ ] `artgen config` manages all settings
- [ ] No need to edit artgen.json manually

### Phase 4 Complete When:
- [ ] 80%+ test coverage on CLI code
- [ ] All live tests pass

### Phase 5 Complete When:
- [ ] README has clear CLI-first examples
- [ ] `artgen --help` is comprehensive

---

## Next Steps

1. ~~**Phase 1: Direct CLI Generation**~~ - ✅ COMPLETE
2. ~~**Phase 2: Pipeline CLI Commands**~~ - ✅ COMPLETE
3. **Phase 3: Configuration CLI** - `artgen config` commands (Priority: MEDIUM)
4. **Phase 5: Documentation** - Update README with CLI-first examples

---

## Notes

- Browser-based interactive mode is still valuable for approval workflows
- CLI-first means CLI is the *primary* interface, not the *only* one
- Server mode should remain available for API integrations
