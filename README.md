[README(2).md](https://github.com/user-attachments/files/33755331/README.2.md)
<!--
  AZRAEL-54 // GITHUB PROJECT DOSSIER
  Designed for GitHub's standard Markdown renderer.
  All product statements distinguish source implementation, local tests,
  historical verification, and unverified host/runtime capability.
  The included images are relative links to the existing repository artwork.
-->

<div align="center">

<img src="web/art/board-b-02-winged-reaper-sigil.png" alt="AZRAEL-54 winged reaper insignia" width="128">

# A Z R A E L — 5 4

### THE SIGNAL IS NOISE. THE EVIDENCE IS EVERYTHING.

### UMBRA MOVET OMNIA
## SYSTEM OVERVIEW

```text
╔══════════════════════════════════════════════════════════════════════╗
║                      A Z R A E L  //  5 4                        ║
║                                                                      ║
║  OPERATOR   : HUMAN / FINAL AUTHORITY                                ║
║  INTERFACE  : AUTHENTICATED LOCAL COMMAND CONSOLE                    ║
║  REASONING  : SHARED OFFLINE QWEN CODING MODEL                       ║
║  ROSTER     : 57 SPECIALIST ROLE CONTRACTS                           ║
║  EVIDENCE   : HASHED / ATTRIBUTED / REVIEWED / VERSIONED             ║
║  ACTIONS    : FIXED RECIPES / EXPLICIT SINGLE-USE APPROVALS          ║
║  DEFAULT    : LOOPBACK / CPU-SAFE / NO AUTOMATIC EXECUTION           ║
║                                                                      ║
║           OBSERVE  →  CORRELATE  →  REVIEW  →  AUTHORIZE              ║
╚══════════════════════════════════════════════════════════════════════╝
```

AZRAEL-54 brings together a tactical web console, a shared local language model, specialist research personas, reference retrieval, evidence management, offline analysis, role-to-role review, controlled lab execution, and optional model-training workflows. It is designed around one rule:

**A model can recommend. A source can inform. Only the operator can authorize.**

The project separates *what is registered*, *what exists in source*, *what passed a test*, and *what is actually running*. A flashy dashboard is not a substitute for measurable behavior.

<div align="center">
<table>
<tr>
<td align="center"><b>57</b><br><sub>Registered role profiles</sub></td>
<td align="center"><b>16</b><br><sub>Experimental classifier checkpoints</sub></td>
<td align="center"><b>6</b><br><sub>Checkpoints meeting narrow readiness gates</sub></td>
<td align="center"><b>1</b><br><sub>Shared local coding SLM</sub></td>
</tr>
<tr>
<td align="center"><b>6</b><br><sub>Defined Compose services</sub></td>
<td align="center"><b>4</b><br><sub>Fixed internal lab recipes</sub></td>
<td align="center"><b>21</b><br><sub>Project artwork files validated in recovery</sub></td>
<td align="center"><b>0</b><br><sub>Verified autonomous exploit executors</sub></td>
</tr>
</table>
</div>

<sub>Counts are taken from the supplied October 2026 source and recovery documentation; they are not live metrics. Six classifier readiness passes are narrow-task gates, not broad operational qualifications. Artwork publication rights require separate review.</sub>

## SYSTEM ARCHITECTURE

```mermaid
flowchart TB
    A["HUMAN OPERATOR<br/>Final decision authority"] --> B["Authenticated AZRAEL Console<br/>Loopback frontend / command surface"]
    B --> C["Python Coordinator<br/>Bounded jobs + scheduler"]
    C --> D["SPECIALIST ROSTER<br/>57 role contracts"]
    D --> E["SHARED QWEN SLM<br/>Local inference / role prompts"]
    C --> F["COUNCIL<br/>Planner → Critic → Chair"]
    F --> E
    F --> G["Persisted proposal<br/>Human accept / reject"]
    G --> A
    C --> H["RESEARCH PIPELINE<br/>Curated references + primary sources"]
    H --> I["EVIDENCE VAULT<br/>Hashes / timestamps / provenance"]
    I --> J["Human dataset admission<br/>Frozen version manifests"]
    J -.-> K["Optional candidate training<br/>Separate weights; no autopromotion"]
    C --> L["AUTHORIZATION GATE<br/>Exact target + short-lived approval"]
    L --> M["Internal lab tool broker<br/>Fixed recipes"]
    L --> N["External observation broker<br/>Approved HTTP HEAD only"]
    M --> O["Isolated Juice Shop lab"]
    C --> P["3D role / supplied topology views<br/>Recorded time + what-if simulation"]
    classDef human fill:#481e31,color:#fff,stroke:#ff5776,stroke-width:2px
    classDef brain fill:#241e49,color:#fff,stroke:#978bff
    classDef gate fill:#163a3b,color:#fff,stroke:#60d8c0
    classDef evidence fill:#343028,color:#fff,stroke:#d6ab64
    class A,G human
    class E,D,F brain
    class L,M,N gate
    class I,J,K evidence
```

### The six service boundaries

| Service | Function | Exposure |
|:--|:--|:--|
| `frontend` | Nginx-based web entrypoint | Published to `127.0.0.1:8765` by default |
| `dashboard` | Authenticated API, coordinator, model integrations | Private project network |
| `tools` | Controlled internal security-tool broker | Private project network |
| `imports` | Allowlisted source collection and imports | Dedicated public-imports egress |
| `external-tools` | Separate bounded external observation broker | Dedicated public-observations egress |
| `web-lab` | Intentionally vulnerable OWASP Juice Shop target | Internal lab only; no published host port |

Container configuration uses rootless-friendly identities, dropped Linux capabilities, read-only filesystems, resource limits, and distinct networks. These controls reduce risk; **they are not proof of complete isolation**.

## QUICK START

**Target environment:** Linux, especially Pop!_OS, with rootless Podman and its Compose provider. Python tooling and optional NVIDIA CUDA require matching host dependencies. Docker Compose support exists as a secondary path; results may differ by runtime.

For a **fresh, isolated setup** with the source already checked out:

```bash
cd azrael54
chmod +x azraelctl
./azraelctl bootstrap --gpu auto
```

`--gpu auto` attempts a constrained, real container GPU readiness check and should fall back to CPU when CUDA passthrough is not usable. To *require* GPU validation instead of permitting fallback:

```bash
./azraelctl bootstrap --gpu on
```

The intended local interface is **http://127.0.0.1:8765**. Its sign-in token is generated or reused locally and **must never be posted to GitHub or included in screenshots**.

> [!CAUTION]
> **Do not use quick start to replace or recreate an existing AZRAEL deployment blindly.** The backup documents a host with unresolved healthcheck, rootless Podman, container-state and/or CDI issues at different points during October 20 recovery. Preserve SQLite data, inspect writable layers, and follow [RESUME-ON-HOST.md](RESUME-ON-HOST.md) before any host recovery or recreation. A successful source test is not a successful host deployment.

### Command deck

```bash
./azraelctl doctor        # Host/runtime diagnostics
./azraelctl status        # Project operational summary
./azraelctl verify        # Project verification stages
./azraelctl logs          # Service log collection
./azraelctl start         # Start approved existing project stack
./azraelctl restart       # Controlled lifecycle request
./azraelctl stop          # Stop AZRAEL project services
./azraelctl update        # Explicit project update workflow
./azraelctl --help        # CLI options and implementation help
```

**Do not equate a command's presence with a verified working host path.** Run `doctor`, inspect the result, and keep copies of your persistent data before any destructive step.

<details>
<summary><b>Show the deployment decision tree</b></summary>

```mermaid
flowchart TD
    A["Start: inspect existing host state"] --> B{"Existing AZRAEL<br/>containers or data?"}
    B -- No --> C["Verify runtime, storage and free space"]
    C --> D["Bootstrap with GPU auto / CPU fallback"]
    B -- Yes --> E["Read-only Podman diagnostics + writable-layer audit"]
    E --> F{"Any unbacked writable state<br/>or failed checks?"}
    F -- Yes --> G["STOP: preserve state and repair deliberately"]
    F -- No --> H["Use documented host recovery plan"]
    D --> I["Verify healthz, authentication, SLM inference"]
    H --> I
    I --> J{"CPU path healthy?"}
    J -- No --> G
    J -- Yes --> K["Optional CDI and selected-GPU probe"]
    K --> L["Real container CUDA + inference verification"]
```

**Relevant guides:** [PODMAN-SETUP.md](PODMAN-SETUP.md) · [STORAGE-SETUP.md](STORAGE-SETUP.md) · [RESUME-ON-HOST.md](RESUME-ON-HOST.md) · [GPU deployment findings](docs/GPU_DEPLOYMENT_STATUS.md)

</details>

## MISSION MODULES

<table>
<tr><td width="50%">
<h3>01 // SPECIALIST HIVE</h3>
57 registered profiles coordinate through bounded messages, hierarchy metadata and a shared coding SLM. Role naming and rank do not create independent weights, additional privileges or autonomous workers.
</td><td width="50%">
<h3>02 // THE COUNCIL</h3>
Planner, critic and chair run successive prompts against the <i>same</i> local model. Proposed decisions are logged for human review; the council never silently patches source code.
</td></tr>
<tr><td>
<h3>03 // EVIDENCE VAULT</h3>
Source URLs, hashes, collection dates, licensing state, record revisions, duplicate groups and reviewer decisions remain distinct. References are quarantined before any training-quality admission.
</td><td>
<h3>04 // RESEARCH ARRAY</h3>
Curated Kali, Parrot and BlackArch references, public vulnerability intelligence, fixed source collectors, repository metadata and supplied-file parsers support investigation without unrestricted browsing.
</td></tr>
<tr><td>
<h3>05 // CONTROLLED LAB</h3>
Four fixed internal recipes use curl, Nmap, WhatWeb and Nikto against the owned Juice Shop lab. A separate approval path permits one limited HTTP HEAD observation of an authorized public URL.
</td><td>
<h3>06 // TRAINING COMMAND</h3>
A serialized red/blue/threat-intel/DFIR/response/purple/evaluation review pipeline records mission snapshots, outputs and timings. Human review and an explicit dataset split are required before export.
</td></tr>
<tr><td>
<h3>07 // TACTICAL VISUALIZATION</h3>
Interactive 3D role communication, recorded-time playback, supplied-inventory topology and spread-versus-containment <i>what-if</i> graph analysis. No invented live endpoint telemetry.
</td><td>
<h3>08 // GPU OPERATIONS</h3>
Optional NVIDIA CUDA selection and container-device checks. CPU fallback remains the default-safe path; containerized CUDA and model inference must be measured again after runtime changes.
</td></tr>
</table>

### The shared intelligence layer

| Layer | Implemented contract | Boundary |
|:--|:--|:--|
| **Language model** | `Qwen/Qwen2.5-Coder-1.5B-Instruct` | Single local, offline inference worker; not 57 LLMs |
| **Context routing** | Role-specific prompts, tool suggestions, council reviews | Generated text never directly executes |
| **Classifiers** | 16 experimental `.pt` checkpoints | Only six meet narrow readiness checks; limited task coverage |
| **Learning candidates** | Separate red/blue lab-outcome classifier pipeline | Requires real, admitted and split-safe labels; no general operational dataset established |
| **Telemetry** | Real recorded local snapshots and service checks | No fictitious signals, endpoint implants, or continuous hardware discovery |
| **Model promotion** | Isolated candidate output and review interfaces | No automatic weights promotion or recursive self-improvement |

For precise boundaries, see [SLM.md](SLM.md), [ROSTER.md](ROSTER.md), [ARCHITECTURE.md](ARCHITECTURE.md) and the reports in `models-*/`.

## PROOF-OF-CONCEPT APPLICATIONS

AZRAEL-54 is designed as a **repeatable demonstration platform** for security operations, local AI evaluation, digital forensics research and defensive-control validation. Each PoC below has a **defined scope, observable evidence and a success condition** rather than an untestable claim about autonomous capability.

**Readiness legend:** `SOURCE PATH` means an implementation pathway is represented in the current repository but its end-to-end host behavior still needs verification. `COMPOSITE DEMO` means the scenario combines existing pieces and requires integration/acceptance testing. `PROPOSED` means additional implementation is required. **None of these labels means the PoC has passed on the current host.**

### Demonstration portfolio

| ID | Potential PoC | Demonstration objective | Existing foundation / gap | Readiness |
|:--|:--|:--|:--|:--|
| **POC-01** | **Authorized Web-Lab Reconnaissance** | Demonstrate a human-approved, bounded security observation against an isolated, owned vulnerable application. | Internal Juice Shop target, fixed `curl` / `Nmap` / `WhatWeb` / `Nikto` recipes and broker approvals exist in source; host workflow needs revalidation. | `SOURCE PATH` |
| **POC-02** | **Security Baseline / Remediation Comparison** | Capture a pre-change observation, apply an authorized defensive fix, and compare reproducible results. | Lab observations and evidence records provide a foundation; a standardized before/after report and validation harness remain to be built. | `COMPOSITE DEMO` |
| **POC-03** | **AI-Assisted SOC Alert Triage** | Convert sanitized sample alerts into a ranked investigation brief with citations, uncertainties and escalation decisions. | Role prompts, council review and evidence handling exist; structured alert ingestion and accuracy benchmarking require development. | `PROPOSED` |
| **POC-04** | **Threat Intelligence Correlation** | Enrich known CVEs / indicators from approved public references, cross-check claims and preserve source provenance. | Curated reference collection and public vulnerability research are represented; analyst-quality correlation requires evaluation. | `COMPOSITE DEMO` |
| **POC-05** | **Multi-Role Incident Review** | Have planner, critic and chair independently review a supplied hypothetical incident, then obtain operator approval of an evidence-based recommendation. | Council sequence, role contracts and logged proposals exist; output quality and current SLM availability need verification. | `SOURCE PATH` |
| **POC-06** | **DFIR Evidence Timeline** | Build a chronological case narrative from *supplied, sanitized* logs and artifacts while maintaining hashes, timestamps and attribution. | File import / evidence provenance foundations exist; supported log formats, timeline extraction and chain-of-custody workflow need expansion. | `PROPOSED` |
| **POC-07** | **Purple-Team Detection Validation** | Evaluate whether a defensive rule detects a documented, safe synthetic lab event and whether a mitigation suppresses it. | Red/blue review structures and isolated lab provide a foundation; detection-event generation, rule execution and measurable outcomes are not established. | `PROPOSED` |
| **POC-08** | **Attack-Path What-If Modeling** | Display how an incident *might* traverse an operator-supplied topology, then compare containment choices without touching real devices. | Recorded-time 3D topology and spread-versus-containment simulation exist in source; actual enterprise telemetry integration is not claimed. | `SOURCE PATH` |
| **POC-09** | **Evidence-to-Training Governance** | Prove that unapproved records stay quarantined and that admitted datasets produce versioned, duplicate-safe train/validation/test splits. | Evidence admission, dataset manifests and candidate-training contracts exist; realistic data and held-out qualification are missing. | `SOURCE PATH` |
| **POC-10** | **Offline AI / GPU Resilience** | Demonstrate the same local-model task on validated CUDA and CPU paths, measuring latency, memory and failure recovery. | Qwen worker, GPU selection and CPU fallback paths exist; present CUDA/container inference must be reproven. | `COMPOSITE DEMO` |
| **POC-11** | **Authorization & Prompt-Injection Defense** | Submit out-of-scope actions and malicious-looking *inert* reference text; verify that recommendations never become unauthorized tool execution. | Scoped approval gates, tool separation and instruction/data boundaries exist; an automated negative-test corpus can be expanded. | `SOURCE PATH` |
| **POC-12** | **Disaster Recovery Tabletop** | Rehearse recovery from a simulated service outage, verify persistent evidence and document recovery gaps. | Compose services, recovery documentation and healthcheck tooling exist; an automated, measured restore exercise is future work. | `COMPOSITE DEMO` |

### Reference PoC — controlled web-lab assessment

<details>
<summary><b>POC-01 // Scope-controlled observation with human authorization</b></summary>

**Scenario:** An operator uses a private OWASP Juice Shop instance to demonstrate the entire **request → review → authorize → observe → preserve** lifecycle. The point of this exercise is to validate security controls and evidence handling, **not to compromise a real organization**.

**Preconditions:** The recovered stack passes authenticated health checks, the `web-lab` is isolated, the broker has no broad host reachability, and the operator can view the approval queue.

1. Define the owned lab target, permitted observation recipe and intended output.
2. Request a bounded fixed-recipe observation without launching arbitrary generated commands.
3. Verify that the pending action discloses its exact target, arguments, lifetime and operator identity.
4. Approve it explicitly and record the broker response, errors, timestamp and source metadata.
5. Reject or let a second request expire to prove that approvals cannot be silently reused.
6. Export a redacted evidence bundle and a short limitations statement.

**Acceptance criteria:** The permitted task executes only within scope; a denied or expired task executes nothing; outputs have identifiable origins; and the demonstration can be repeated without exposing the lab publicly.

**Demo artifact:** `POC-01-lab-assessment.md` containing scope, screenshots with tokens redacted, request/approval IDs, tool versions, timestamps and evidence hashes.

</details>

<details>
<summary><b>POC-05 // Analyst council and accountable decision support</b></summary>

**Scenario:** Provide a fictional intrusion case composed of sanitized alert excerpts and an incident statement. Use the **same shared model** in successive planner, critic and chair contexts to produce a recommendation—not three independent expert models.

1. Submit a case packet and mark each source as supplied, verified or hypothetical.
2. Ask the planner to identify competing explanations, key facts and missing evidence.
3. Have the critic challenge unsupported assertions and propose disconfirming checks.
4. Have the chair summarize the disagreement and produce an operator-reviewable decision memo.
5. Record operator acceptance or rejection; preserve citations and acknowledge limitations.

**Acceptance criteria:** Every consequential statement is tied to supplied evidence or explicitly labeled inference, disagreement is visible, and no model recommendation triggers an unapproved action.

**Demo artifact:** `POC-05-incident-review.md` with the supplied fictional case, role outputs, reviewer decision and a factual-error scoring rubric.

</details>

<details>
<summary><b>POC-10 // GPU fallback and repeatable local inference</b></summary>

**Scenario:** Compare an identical bounded prompt using the validated NVIDIA container path and the safe CPU path, entirely on locally controlled inputs. This is a **measurement proposal**, not a claim that all three installed GPUs are currently usable.

1. Capture host driver, CDI, container runtime and model version fingerprints.
2. Establish one healthy authenticated model inference run on CPU.
3. Select one GPU and validate actual in-container CUDA allocation and inference.
4. Record latency, token throughput, peak memory and failure messages for both paths.
5. Disable the GPU path in a controlled test and verify a documented CPU recovery or explicit safe failure.

**Acceptance criteria:** The same prompt is processed by the intended verified device, device-selection evidence is recorded, and errors are reported without presenting CPU results as GPU success.

**Demo artifact:** `POC-10-local-inference-benchmark.md` with reproducible environment details and *measured* comparisons (no synthetic benchmark values passed off as observed results).

</details>

### PoC execution contract

```mermaid
flowchart LR
    A["Define a permitted use case"] --> B["Declare scope and inputs"]
    B --> C["Establish preflight health"]
    C --> D["Operator reviews and approves"]
    D --> E["Run bounded test in controlled environment"]
    E --> F["Preserve source evidence and measured outputs"]
    F --> G["Evaluate acceptance criteria"]
    G --> H["Publish redacted report and limitations"]
    classDef gated fill:#352332,color:#fff,stroke:#e08fa0
    class D,E gated
```

Every published PoC should include **environment and commit SHA; authorizing party and exact scope; input-data classification; method and tool versions; expected versus observed behavior; evidence location / integrity hashes; pass, fail or inconclusive result; reproducibility notes; and known limitations**. A screenshot, generated answer or simulated topology cannot by itself prove that detection, exploitation, prevention or GPU inference actually happened.

**Recommended first public demonstrations:** `POC-01` for bounded operator approval, `POC-05` for accountable role-based reasoning, and `POC-11` for fail-closed security boundaries. These use the most relevant existing source-level foundations, **after** host recovery and verification. `POC-03`, `POC-06` and `POC-07` are compelling next-stage targets but should remain explicitly labeled as concepts until implemented and measured.

**Permitted environments:** personally owned labs, training ranges, synthetic incident datasets and systems with express written authorization. Do not publish credentials or real organizational case data. **No unsanctioned scanning, exploitation, lateral movement or uncontrolled agent execution is part of these demonstrations.**

## VISUAL COMMAND CENTER

<div align="center">
<table>
<tr>
<td align="center" width="50%"><img src="web/art/board-a-06-raven-crest.png" width="280" alt="Raven crest artwork"><br><sub>RECON // SIGNAL INTELLIGENCE</sub></td>
<td align="center" width="50%"><img src="web/art/board-b-09-red-ghost-map.png" width="280" alt="Red ghost map artwork"><br><sub>TOPOLOGY // EVIDENCE PATHS</sub></td>
</tr>
<tr>
<td align="center"><img src="web/art/board-a-09-electronic-warfare.png" width="280" alt="Electronic warfare artwork"><br><sub>SPECTRUM // RESEARCH PLANNING</sub></td>
<td align="center"><img src="web/art/board-b-10-stealth-aircraft.png" width="280" alt="Stealth aircraft artwork"><br><sub>OBSERVATION // CONTROLLED OPERATIONS</sub></td>
</tr>
</table>
</div>

The supplied dashboard source contains theme selection, role cards, a 3D canvas with recorded-time controls, a message timeline, a readiness panel, a research console, a human approval queue, mission history, topology and review tools. Artwork is decorative; operational panels must use real, appropriately labeled data.

**Image provenance note:** these are repository-relative references to existing AZRAEL artwork. Confirm redistribution rights and attribution before making the repository public. A hash match does not confer a license.

## EVIDENCE → INTELLIGENCE → CANDIDATE TRAINING

```mermaid
flowchart LR
    A["Authorized public source<br/>or supplied lab observation"] --> B["Bounded retrieval / parser"]
    B --> C["Record original hash<br/>time + attribution"]
    C --> D["QUARANTINE"]
    D --> E{"Human review<br/>license + provenance + labels"}
    E -- Incomplete --> F["Reference only<br/>not training eligible"]
    E -- Approved --> G["Frozen dataset manifest"]
    G --> H["Train / validate / test<br/>identity + duplicate checks"]
    H --> I["Isolated candidate checkpoint"]
    I --> J["Independent evaluation<br/>human promotion decision"]
    classDef stop fill:#4c2731,color:#fff,stroke:#ef6b89
    class D,F stop
```

The red/blue candidate contract uses six declared configuration features and two outcome tasks: **reproduced** and **mitigation_verified**. Its workflow includes split-integrity checks and baseline comparisons. The project docs do **not** establish a completed operational candidate training run on admitted real-world labels. A candidate score cannot prove the presence of a vulnerability.

### Boundaries that matter

- **Collection ≠ training.** Fetching CISA KEV or source metadata is not weight updating.
- **Role profile ≠ trained specialist.** A prompt context does not create a new independent model.
- **Council agreement ≠ validation.** Multiple prompts to one SLM can share errors.
- **Reachability ≠ compromise.** A topology simulation does not conduct exploitation.
- **GPU visibility ≠ deployed GPU inference.** The specific service must execute and pass an observed inference test.
- **Source hash ≠ truth.** Integrity and provenance do not independently verify a technical finding.

## NVIDIA / CUDA OPERATIONS

AZRAEL includes a selected-device CUDA path for compatible NVIDIA hardware. The archived environment identifies these cards:

| GPU | Historical host/probe coverage | Current service requirement |
|:--|:--|:--|
| GeForce RTX 3080 | Earlier local CUDA operations recorded | Re-verify CDI, container CUDA, PyTorch, and authenticated model inference |
| GeForce RTX 3060 Ti | Earlier local CUDA operations recorded | Re-verify selected-device passthrough and CUDA allocation |
| GeForce RTX 5060 | Earlier local CUDA operations recorded | Re-verify driver/toolkit compatibility and actual container execution |

Historical test artifacts record CUDA activity, but subsequent host/network/container problems invalidate assumptions of **current** end-to-end availability. A three-GPU probe is not proof of distributed Qwen training or model sharding. See [the GPU evidence ledger](docs/GPU_DEPLOYMENT_STATUS.md).

## RULES OF ENGAGEMENT & SECURITY

> [!WARNING]
> **Operate only on assets you own or are expressly authorized to test.** The internal `web-lab` is intentionally vulnerable. Keep it private and never publish it directly onto an untrusted network. Model-generated suggestions have no authority to change this boundary.

| Safeguard | Operating principle |
|:--|:--|
| **Local first** | Frontend bound to host loopback by default |
| **Human sign-off** | Fixed tool actions require exact, explicit approval |
| **Ephemeral authorization** | Single-use approvals expire after five minutes |
| **Tool containment** | Fixed arguments, target controls, process/output limits |
| **External scope** | One approved HTTP HEAD request; pinned public resolution; no redirect following |
| **Session boundary** | Local token-backed login, protected mutations and session cookies |
| **Separation of duties** | Private brokers, data collectors and lab networks |
| **Inference isolation** | Retrieved web text does not become a system instruction |
| **Conservative evidence** | Hash, record origin, review status and limitations preserved |
| **No silent escalation** | Role labels, directives and council outputs grant no execution rights |

### Before publishing to GitHub

**The uploaded backup contains local `.runtime/` secret-token files.** They are excluded by the present `.gitignore`, but that does not prove secrets were never committed or included in a previous Git revision. Rotate exposed tokens and audit the repository **and its history** before publishing. Do not push the backup archive itself.

```bash
# Review repository state without printing credential contents.
git status --short --ignored

# Check whether sensitive paths are tracked.
git ls-files | grep -E '(^|/)(\.runtime|\.env|\.slm-model|\.slm-venv|data)/|(^|/)(admin-token|broker-token|external-token)$' || true

# Review the commit history and run an appropriate local secret scanner
# before changing repository visibility or pushing to an external remote.
```

Exclude private credentials, real target details, personal data, unreviewed evidence, licensed datasets, large model weights and unneeded local Python environments. Git history must be examined separately if anything sensitive was previously tracked. For detailed boundaries read [SECURITY.md](SECURITY.md) and [API_KEYS.md](API_KEYS.md).

## CURRENT VERIFICATION LEDGER

**Archive snapshot:** October 21, 2026. These are documentation/source observations, not a live host inspection.

| Subsystem | Evidence in archive | Status |
|:--|:--|:--|
| Source and Compose configuration | Python/shell/YAML checks documented | **Locally tested** |
| Test suite | `102` tests run; `2` skipped in one documented local suite | **Historical local pass** |
| Role / model inventory | 57 profiles; 16 experimental checkpoints | **Source inventory** |
| Shared SLM | Local host inference previously documented | **Container state needs recheck** |
| Rootless Podman stack | Healthcheck/state/network issues reported across recovery | **Host recovery / verification pending** |
| GPU runtime | Host CUDA historically exercised on three GPUs | **Current service inference needs recheck** |
| Browser UI | Dashboard source and artwork present | **Interactive QA not fully verified** |
| Red/blue candidate training | Contract and fixture-driven tests exist | **No qualifying real-data training established** |
| General autonomous red teaming | No general executor supplied | **Not implemented** |

> [!NOTE]
> The archive includes status documents from different stages of the same recovery. An earlier successful verification does not override a later failure. Consult the most recent actual host outputs rather than treating this README as a live health monitor.

## DEVELOPMENT ROADMAP

The following is **planned work**, not a promise that the features already run. The highest priority is a verifiable, repeatable recovery before expanding capabilities.

- [x] Tactical AZRAEL identity and repository artwork integration in source
- [x] Authenticated console, role registry, shared-SLM orchestration and evidence APIs in source
- [x] Scoped tool broker, fixed internal recipes and approval structures in source
- [x] Source-level test suites and recovery/verification documentation
- [ ] **PHASE 01 — Host recovery:** Repair rootless container state, healthcheck ordering and frontend-to-dashboard connectivity without losing preserved data
- [ ] **PHASE 02 — Verified deployment:** Pass `/healthz`, authenticated API, project health, restart persistence and actual SLM inference
- [ ] **PHASE 03 — CUDA commissioning:** Verify CDI, each selected GPU, real container inference, reproducible GPU telemetry and CPU rollback
- [ ] **PHASE 04 — Research quality:** Expand validated primary sources, provenance/licensing review and adversarial evidence-quality tests
- [ ] **PHASE 05 — Model qualification:** Obtain real, authorized, labeled datasets; frozen leakage-resistant splits; honest held-out measurements
- [ ] **PHASE 06 — Mission console QA:** Confirm browser interactions, 3D accessibility, topology provenance and cancellation/replay behavior
- [ ] **PHASE 07 — Operational security:** Secret rotation/audit, supply-chain pinning, storage backup drills and improved deployment diagnostics
- [ ] **PHASE 08 — Controlled release:** Clean install reproducibility, contribution policy, artwork rights review and explicit licensing decision

**North star:** *More observable capability, fewer unverifiable claims.*

## REPOSITORY MAP

```text
azrael54/
├── azraelctl                 # Main operator CLI / lifecycle workflows
├── setup_lab.py              # Installer / preflight / host setup logic
├── compose.yaml              # Six service definitions
├── compose.podman.yaml       # Rootless Podman overlays
├── compose.gpu.yaml          # Optional selected GPU configuration
├── compose.docker-gpu.yaml   # Docker CUDA overlay
├── admin.py / ops_api.py     # Command API / operations surface
├── council.py / hierarchy.py # Sequential review contexts / reporting
├── model.py / slm.py         # Classifiers and shared local SLM
├── research.py / collection.py / live_data.py
│                            # Research, public sources and collection
├── evidence_store.py         # Persisted evidence / provenance
├── training_coordinator.py   # Authenticated mission coordination
├── tool_broker.py            # Fixed internal lab recipes
├── external_broker.py        # Bounded authorized observations
├── poc_training.py           # Optional isolated red/blue candidates
├── web/                      # Tactical UI, scripts and original artwork
│   └── art/
├── container/                # Container builds, Nginx and healthchecks
├── models-*/                 # Narrow-task experimental checkpoints
├── docs/                     # Requirements, research and GPU evidence
├── recovery/                 # Historical reconstruction and verification
├── SECURITY.md
├── ARCHITECTURE.md
└── BUILD-STATUS.md
```

<details>
<summary><b>Open the technical documentation index</b></summary>

| Document | Purpose |
|:--|:--|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Actual orchestration, research and authorization model |
| [BUILD-STATUS.md](BUILD-STATUS.md) | Host deployment issues and local checks |
| [KNOWN-ISSUES.md](KNOWN-ISSUES.md) | Current blockers and hypotheses |
| [PODMAN-SETUP.md](PODMAN-SETUP.md) | Runtime-specific configuration and deployment |
| [STORAGE-SETUP.md](STORAGE-SETUP.md) | Persistence, capacity and isolation |
| [SLM.md](SLM.md) | Qwen worker, token bounds and model limitations |
| [SECURITY.md](SECURITY.md) | Local security and authorization controls |
| [TEST-RESULTS.md](TEST-RESULTS.md) | Observed tests versus unverified runtime behaviors |
| [RESUME-ON-HOST.md](RESUME-ON-HOST.md) | Conservative host recovery sequence |
| [docs/LIVE_TRAINING.md](docs/LIVE_TRAINING.md) | Mission snapshots, review and evidence lifecycle |
| [docs/CTF-AND-IDLE-TRAINING.md](docs/CTF-AND-IDLE-TRAINING.md) | Offline training/practice constraints |
| [docs/GPU_DEPLOYMENT_STATUS.md](docs/GPU_DEPLOYMENT_STATUS.md) | Historical CUDA and current runtime recovery evidence |
| [docs/FEATURE_REQUIREMENTS.md](docs/FEATURE_REQUIREMENTS.md) | Source implementation versus acceptance gaps |
| [docs/GAPS.md](docs/GAPS.md) | Outstanding recovery conflicts and missing artifacts |

</details>

## VALIDATION FOR CONTRIBUTORS

From an environment where the project's local Python dependencies are installed:

```bash
python -m unittest discover -p 'test_*.py'
node --check web/app.js
bash -n run.sh install.sh deploy-host.sh
```

These commands check selected source behavior and syntax. They do not certify OCI images, the host GPU stack, lab containment, the quality of generated security analysis, or a production deployment. In a constrained sandbox, socket-dependent tests may skip.

## CONTRIBUTION & DISCLOSURE

AZRAEL-54 is an experimental security research repository. Responsible contributions prioritize reproducible tests, explicit scope, observable evidence, narrow permissions, and a clear distinction between simulation and real effects. **Do not submit live credentials, private target data, exploit runs against third parties or malicious samples into public pull requests.**

For sensitive security findings, contact the repository maintainer privately rather than opening a public issue with exploit details or tokens. A formal vulnerability-disclosure contact has not been specified in this backup.

### License and artwork

No root `LICENSE` file was identified in the supplied archive. **Do not assume this repository is open-source licensed or that its model checkpoints, data sources and artwork are freely redistributable.** Add a suitable license and verify third-party and original-art rights before public release.

---

<div align="center">

<img src="web/art/board-b-07-minimal-a-insignia.png" alt="AZRAEL-54 insignia" width="80">

### AZRAEL—54

**OBSERVE THE SIGNAL. VERIFY EVERYTHING.**

`LOCAL AUTHORITY` / `DEFENSIBLE EVIDENCE` / `HUMAN CONTROL`

*Built for research. Designed for restraint. Measured before claimed.*

</div>
