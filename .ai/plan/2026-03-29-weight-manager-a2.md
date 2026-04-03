# Weight Manager A2 · Provider Cleanup
Date: 2026-03-29
Status: done

## Scope
- model/trellis2/pipeline/pipelines/__init__.py
- model/hunyuan3d/pipeline/shape.py
- model/hunyuan3d/pipeline/texture.py
- model/step1x3d/pipeline/step1x3d_geometry/models/pipelines/pipeline_utils.py
- model/trellis2/provider.py
- model/hunyuan3d/provider.py
- model/step1x3d/provider.py
- Additional model-side files if required to remove all snapshot_download/hf_hub_download usages from provider call paths and pass grep checks.
- tests/test_api.py (expectation updates for local-only model path behavior)

## Acceptance Targets
- Providers only accept existing local paths; missing path raises ModelProviderConfigurationError with Admin-download guidance.
- Remove network download fallback branches in specified pipeline files.
- grep snapshot_download / hf_hub_download in model code returns zero matches.
- pytest runs with only known existing unrelated failure allowed.

## Result
- Provider and pipeline loading paths are now local-only with explicit Admin-download guidance on missing paths.
- `snapshot_download` / `hf_hub_download` usages were removed from `model/` code.
- Tests updated for local-path resolver behavior.
