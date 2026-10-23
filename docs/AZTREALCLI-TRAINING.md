# AZTREÁL training control

Run `aztrealcli training` in a terminal for the curses interface. The project
executable is `./aztrealcli`; `~/.local/bin/aztrealcli` links to it.
`./azraelctl training` invokes the same interface without changing the lifecycle
commands. The launchers prefer a prepared `.training-venv`, otherwise use
`.slm-venv`. No native Codex
slash command was installed.

The verified execution backend is **local CPU**. A CUDA-enabled training
interpreter is now prepared; actual GPU execution remains unverified from the
restricted verification session. Podman remains the CLI's default
backend, but is unavailable from the verification session. Select `--backend local`
explicitly for the demonstrated workflow. No deployed service was restarted.

## What is implemented

| Capability | Behavior |
|---|---|
| Classifier training | Existing `model.py train` engine, isolated candidate weights, frozen reviewed splits, early stopping and resumable optimizer state |
| Coding SLM | Native PyTorch LoRA on Qwen's `q_proj`/`v_proj`; original base weights frozen |
| QLoRA | Rejected with an explicit unavailable/unvalidated error |
| Evaluation | Independent held-out classifier metrics; SLM held-out loss, pretrained comparison, optional bounded generation rubrics |
| Registry | Original model discovery plus evaluated candidate selection and selection rollback |
| Production deployment | Separate operator work; selecting a candidate does not load an adapter into the dashboard or replace deployed weights |
| Podman / Docker | Guarded OCI execution code and image recipe; live operation remains unverified |
| Kubernetes | Explicitly unavailable until a verified cluster, namespace and persistent-storage integration are implemented |
| Distributed training | Unavailable; GPU memory is never pooled |

The SLM adapter uses `aztreal-native-lora-v1`, **not a PEFT-compatible checkpoint**.
Only adapter tensors are trained and saved; this is not full-weight fine-tuning.
The recovered base is `Qwen/Qwen2.5-Coder-1.5B-Instruct`, local manifest revision
`2e1fd397ee46e1388853d2af2c993145b0f1098a`. Its local LICENSE and the
[official model card](https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct)
identify Apache 2.0. Quantized training would require a separately validated
stack; see the [PEFT quantization documentation](https://huggingface.co/docs/peft/developer_guides/quantization).

## Interactive use

Use `1` for models, `2` for datasets, `3` for jobs and `4` for measured NVIDIA
telemetry. `s` prompts for an admitted dataset, model and backend, `x` requests a
checkpointed stop of the latest active job, `r` resumes the latest paused job and
`q` exits. Advanced recipes and GPU UUIDs use the explicit commands below.

The screen displays recorded epochs, optimizer steps, losses, learning rates,
checkpoints and job states. Missing observations remain empty. It does not
invent percentages or completion estimates. In a pipe, `training` returns a JSON
snapshot. `training --once` renders one frame in a real terminal. A working TERM
and POSIX curses are required for the interactive interface.

## Models and datasets

```bash
aztrealcli models list
aztrealcli models inspect --model coding-slm
aztrealcli datasets validate --input /path/to/reviewed.jsonl
aztrealcli datasets import --input /path/to/reviewed.jsonl --kind slm \
  --source 'local reviewed coding examples' --license CC0-1.0 \
  --synthetic no
aztrealcli datasets list
aztrealcli datasets inspect --dataset DATASET_ID
```

Supported formats are UTF-8 JSONL, JSON arrays and CSV, bounded to 32 MiB.
Classifier rows use `text`/`label` or `description`/`type`. SLM rows use
`instruction`/`response` or `prompt`/`output`. Example rows:

```json
{"instruction":"Write a two-argument addition function.","response":"def add(a, b):\n    return a + b"}
```

```json
{"text":"Synthetic harmless application log example","label":"benign"}
```

Validation checks encoding, schema, contradictory labels, duplicate inputs and
recognizable secret patterns. Secret screening is a heuristic and does not
replace human review. Secret-classifier labels are `benign` and
`potential_secret`. Classifier admission to a job requires at least two classes
and ten unique examples per class. Small SLM fixtures require enough records for
nonempty train/validation/test partitions.

Import alone does not authorize training. After reviewing the dataset and its
license, repeat the import with the same metadata and explicit approval:

```bash
aztrealcli datasets import --input /path/to/reviewed.jsonl --kind slm \
  --source 'local reviewed coding examples' --license CC0-1.0 \
  --synthetic no --approve --reviewer 'operator name'
aztrealcli datasets split --dataset DATASET_ID
```

Use `--synthetic yes` for synthetic examples and `--synthetic model-generated`
for model-generated examples. Unknown-license data cannot be approved. Research
ingestion never automatically imports or admits training data. Approval records
an operator assertion; it cannot independently verify ownership or license.

Version manifests contain content hashes, provenance and review metadata.
Splits are deterministic, stratified for classifiers, disjoint and hash-checked.
Each job freezes a separate input manifest so subsequent manager actions cannot
silently alter its evaluation split. A dataset file path supplied to `start`
must match exactly one already approved imported version; an ID is clearer.

## Bounded training

```bash
aztrealcli training preflight --model secret-classifier --backend local
aztrealcli training start --model secret-classifier --recipe classifier \
  --dataset CLASSIFIER_DATASET_ID --backend local --device cpu \
  --epochs 1 --batch-size 8 --wait

aztrealcli training preflight --model coding-slm --recipe lora \
  --backend local --device cpu --max-length 64
aztrealcli training start --model coding-slm --recipe lora \
  --dataset SLM_DATASET_ID --backend local --device cpu \
  --epochs 1 --max-steps 1 --max-length 64 --rank 2 \
  --batch-size 1 --gradient-accumulation 1 --wait
```

The classifier engine fits a new candidate using existing training behavior;
it does not overwrite the original classifier. The SLM engine freezes the base,
uses response-only supervised loss, gradient checkpointing, gradient
accumulation and clipped gradients. CUDA selects BF16 when supported, otherwise
FP16 with loss scaling; CPU uses FP32. Inputs are right-truncated to the selected
length, preserving at least response space. Short lengths are smoke tests, not
recommended settings for a real corpus.

More than three epochs or 200 SLM optimizer steps requires the explicit
`--confirm-resource-intensive` flag on start/resume. This flag should only be
used after operator authorization. A step-limited completion can have epoch 0:
it means the requested optimizer-step budget completed before a full epoch.

```bash
aztrealcli training status
aztrealcli training status --job JOB_ID
aztrealcli training logs --job JOB_ID --lines 100
aztrealcli training stop --job JOB_ID --wait
aztrealcli training resume --job JOB_ID --wait
aztrealcli training evaluate --job JOB_ID
aztrealcli training evaluate --job SLM_JOB_ID --code-tests
aztrealcli training checkpoints --job JOB_ID
```

Stops are cooperative at durable checkpoint boundaries. Resume verifies the
base, inputs, recipe fingerprint and checkpoint integrity; epochs/step budgets
may change, architecture/dataset/device recipe may not. Classifier checkpoints
include optimizer state at epoch boundaries; SLM checkpoints include adapters,
optimizer, scaler, CPU RNG and the dataset cursor at optimizer-step boundaries.
Deterministic CUDA resume has not been verified.

For short validation runs, use `--wait`. It has a five-minute observation
deadline; expiry does not stop the job. A normal persistent terminal can launch
background children, but the verification sandbox cleaned up one detached
driver. Use a persistent supervisor for unattended runs. Same-namespace dead
drivers become `failed`; PID start times guard against PID reuse. Foreign PID
namespaces cannot be conclusively checked and retain conservative reservations.
Heartbeat telemetry helps diagnose them; automatic host-reboot recovery and an
administrative stale-reservation release workflow are not implemented.

Classifier evaluation reports accuracy, precision, recall, F1, confusion matrix
and per-class false-positive/false-negative rates. SLM evaluation reports held-out
response-token loss against the same frozen pretrained base. `--code-tests`
generates two bounded baseline/candidate answers. Addition is assessed using a
restricted AST interpreter and four numeric fixtures; SQL handling uses an AST
structural rubric. Arbitrary generated Python is never executed. These small
rubrics are not a general coding benchmark or security certification.

## GPUs, storage and backends

The CUDA interpreter repair uses `.training-venv/bin/python` with PyTorch
`2.11.0+cu128`. It reuses the host's installed CUDA packages and the application's
Python dependencies through symlinks, with a recorded dependency manifest;
`.slm-venv` remains the original CPU application environment. The two launchers
and local workers use the same selected interpreter. `gpu list` reports its
absolute path, actual Torch/CUDA build and compiled architecture targets.
Those targets are build metadata, not evidence that a kernel ran.

For an explicit CPU-environment rollback without changing stored jobs or models:

```bash
AZTREAL_PYTHON="$PWD/.slm-venv/bin/python" ./aztrealcli training status
```

`setup_training_cuda.py` prepares the linked environment from an already
installed CUDA Torch using the host Python. It refuses to overwrite an existing
training environment. The readiness marker is written after imports, a real CPU
tensor operation and dependency-version validation. This linked environment is
not self-contained: replacing the source packages in `.local` or `.slm-venv`
requires revalidation. It is a local backend environment, not an OCI image.
Keep it managed by the provisioner: package installation/removal commands inside
the linked environment can follow links into the source package trees.

```bash
./aztrealcli training preflight --model secret-classifier \
  --backend local --device auto
```

Run this from the host terminal before requesting GPU training. When it passes,
the `selected_gpu` UUID identifies the assigned device and CUDA tensor smoke
test. A bounded GPU training job must still establish model-training behavior.

For sequential verification of all three configured GPUs, including one-epoch
classifier smoke jobs and available container engines:

```bash
./verify_training_cuda.py
```

This uses the already approved synthetic classifier fixture, creates separate
candidate directories, and rejects CPU fallback as GPU proof. It records live
UUID/compute capability, tensor math, actual parameter/gradient/loss devices,
optimizer updates, CUDA timing, allocation peaks, NVML utilization samples,
checkpoint hashes and owned-process disappearance. Busy GPUs are skipped.
Podman/Docker probes use only existing images and isolated transient containers;
`--podman-image` / `--docker-image` select compatible images already present.
No image/model downloads or production database mounts are performed. Runtime
access failures remain BLOCKED. Results go to a new timestamped directory under
`recovery/final-verification/cuda-runtime-*` and append to
`AZTREALCLI-CUDA-REPAIR.md`. GPU execution of this verifier still needs a host
terminal with accessible devices and engines.

```bash
aztrealcli gpu list
aztrealcli gpu monitor --samples 10 --interval 2
aztrealcli training preflight --model coding-slm --recipe lora \
  --backend local --device GPU-UUID --memory-fraction 0.75
```

Explicit UUID selection is stable. `--device auto` chooses an eligible device,
preferring RTX 3080. It fails if CUDA/VRAM prerequisites cannot be established;
it does not silently switch a GPU job to CPU. Use `--device cpu` explicitly for
CPU operation. The managed reservation lock prevents two CLI jobs from sharing
an assigned device; external applications remain outside that lock. No CUDA
training result is claimed for the RTX 3080, RTX 5060 or RTX 3060 Ti in this
session. In particular, Blackwell compatibility needs actual CUDA execution.

State defaults to `/data/work/azrael54/training/aztrealcli` if writable, otherwise
`PROJECT/training-state`. `AZTREAL_STATE_DIR` may select a user-owned 0700
directory inside the project or `/data`, outside `/tmp`, without a symlink root.
JSON files are atomic 0600 writes. Jobs keep persistent caches, metadata,
logs, checkpoints, frozen inputs and evaluation results. Preflight checks
available RAM/VRAM and checkpoint/optimizer disk estimates plus a 5 GiB reserve
(`AZTREAL_MIN_FREE_GB`). Estimates cannot guarantee against external resource
consumption or OOM. No base-model copy is created.

The OCI image recipe is `container/Dockerfile.training`; it has not been built
or executed here. With separately verified engine/image access, the implemented
Podman/Docker paths accept `--backend podman|docker --image IMAGE`. They probe
imports (and a CUDA tensor for GPU jobs) before launch, mount production code
and model read-only, grant write access only to private job state, disable
networking, drop capabilities and apply CPU/memory/PID limits. There are no
engine-socket mounts or production-network connections. CUDA image/toolkit
versions must be validated independently. Kubernetes selection currently
returns a clear unavailable error and creates no cluster or Job.

## Candidate selection and rollback

```bash
aztrealcli training promote --job JOB_ID --confirm MODEL_ID
aztrealcli training rollback --model MODEL_ID --confirm MODEL_ID
```

Selection requires completion, held-out evaluation, checkpoint integrity and
the exact model-ID confirmation. Evaluation existence is required; deciding
whether quality is sufficient remains the approving operator's responsibility.
Selection and rollback modify only private registry references. Production
checkpoint replacement, adapter serving and deployment approval are separate
work; this command does not perform them.

For verification results, actual job IDs and unresolved infrastructure blockers,
see [the training verification report](../recovery/final-verification/AZTREALCLI-TRAINING-VERIFICATION.md).
