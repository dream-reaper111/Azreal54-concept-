# Shared local coding model

The auxiliary SLM is Qwen/Qwen2.5-Coder-1.5B-Instruct, pinned by `slm-model-manifest.json`. Local host inference has been exercised. Container inference is not yet verified. This single service supplies admin chat, coordinated role briefs, code drafting and fixed-recipe proposals; it is not 57 independently trained language models.

`run.sh` prepares missing weights with `setup_slm.py`. If a manifest exists, setup preserves its revision. Weight downloads use Hugging Face; inference uses offline loading, `trust_remote_code=False` and safetensors. Dependencies are installed in the container; optional download-only bootstrap dependencies use `.bootstrap-venv/` on the host.

CPU is the default and fallback. With the opt-in GPU Compose overlay, the dashboard image installs the PyTorch CUDA 12.8 wheel and the worker selects `cuda:0` when CUDA is visible. Rootless Podman CDI restricts the container to one selected physical GPU; selection defaults to the RTX 3080 and accepts a host index, UUID, or model name via `AZRAEL_GPU_DEVICE`. RTX 5060 and RTX 3060 Ti are supported choices. `AZRAEL_GPU_MEMORY_FRACTION` defaults to `0.85` and caps the PyTorch allocator's per-process usage; it is not a hardware partition. If CUDA is unavailable, ordinary inference reports the reason and falls back to CPU. `--verify-gpu` rejects fallback and requires live CUDA metadata, a real model inference, allocated CUDA memory, and observed host GPU utilization. This environment has not yet passed that hardware check.

The worker accepts at most 4,096 input tokens and generates at most 192 new tokens. Oversized prompts fail rather than silently losing user input. Answers may be incomplete or wrong. A 50-role admin smoke run completed but did not adequately answer the privacy question; its quality review is retained in `slm-admin-validation.json`. Successful generation is not successful task evaluation. The parent applies a 180-second timeout. Generated code is never executed. Python generation was smoke-tested; language selection for C#, Java and C++ is implemented but output quality has not been independently evaluated.

Pretraining data quality and absence of synthetic content are not certified. Role-specific training and online learning are not implemented by this shared service. Changes to training data do not automatically retrain or promote any model.

Official model source: https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct

Online planning performs one bounded crawler pass before local inference; the SLM process itself has no network access. Context includes up to three latest stored metadata versions and bounded documentation/repository matches, not complete web coverage. The council performs three sequential role-context generations and retains a collective report for admin review. Generated text can be wrong, incomplete or mutually repetitive. Accepting its report never applies changes.

`coordination-validation.json` records the latest explicitly invoked live integration check. It reports actual source retrieval and generated passes separately from output-quality review. It does not establish independent reasoning by 57 models or continuous self-improvement.
