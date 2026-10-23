# Reaffirmed artwork, research, coordination and visualization requirements

The user's current message reaffirmed the feature request originally recorded in
session A at 2026-10-20T13:28:54.879Z and related continuation prompts. This checklist
accounts for the complete request without turning historical intentions into
deployment permission. Source and tests establish implementation contracts, not
successful browser interaction or operational model quality.

| Requirement | Recovered implementation evidence | Remaining gap / verification |
|---|---|---|
| AZRAEL identity and supplied artwork | ARTWORK.json, branding.py, web/art, web/index.html and styles. | All 21 AZRAEL artwork files match both their original files and stored hashes; visual placement and final wording still need browser review. |
| The twenty specifically listed artwork paths | Board A items 02–11 and Board B items 01–10 exist in recovered web/art; the additional Board A hero also survives. | No source image was modified; no replacement artwork was generated. |
| Dark reference-inspired UI tailored to role capabilities | web/azrael.css, web/style.css, index/app/scene scripts, role cards and readiness presentation. | The current message's Image #2/#3 references do not establish an unambiguous visual-to-file mapping; retain this as a visual acceptance question rather than claiming a faithful match. |
| Updated product wording | AZRAEL branding, architecture/readiness limitations, role descriptions. | Review every final screen for wording that confuses registered roles, experimental classifiers, shared-SLM contexts and trained capability. |
| research.py access to web-collected and live data | research.py, live_data.py, source_transport.py, collection.py, role_research.py and evidence_store.py. | Existing collectors are bounded/exact-source integrations, not unrestricted crawling; fresh retrieval and source availability are not verified by this recovery. |
| Appropriate Python security/research libraries | requirements-research.txt and research-libraries.json list pinned integrations. | Listing/importing a library does not grant raw device, packet-capture or execution access; optional dependencies and native libraries require separate installation/verification. |
| Multiple communication contexts and peer project review | council.py, lab.Bus, slm.py and admin council/hive actions. | The recovered design uses one shared SLM with role contexts, not independent distributed model servers. |
| Peer suggestions and adjustments | Planner, critic and chair produce persisted proposals. | Automatic source-code modification is not implemented by the council; any approved patch workflow would need a separate design and authorization boundary. |
| Semi-autonomy with restrictions | Admin-started bounded jobs, role policies, shared work lock, mission and idle queues, cancellation. | Confirm the intended idle scheduling policy; current recovery starts no worker or training process. |
| Collective results returned to the administrator | Council decision records, job results, evidence references, authenticated dashboard actions. | Human acceptance does not establish an independently verified finding or execute a proposal. |
| Role hierarchy | hierarchy.py, roster.py and role presentation. | Hierarchy is reporting/coordination metadata and must not silently grant privileges. |
| 4D communications/brainstorming view | web/scene.js projects role nodes in 3D and uses recorded time as the fourth dimension. | It is not a direct view of neurons, weight updates or consciousness; live learning must not be fabricated. |
| 3D network topology of ongoing work | Supplied-inventory topology, operation/service views and mission timeline. | An actual discovered network graph requires authorized observations; a declared or supplied relationship must retain its provenance. |
| Offensive/defensive spread and containment analysis | simulation.py and topology/step-scrubbing controls compare bounded graph reachability. | This is a what-if graph model, not replication, endpoint control, botnet deployment, or proof that a path is exploitable. |
| Two red/blue PoC models | poc_training.py and the poc_red/poc_blue role contracts. | Candidate classifiers need admitted six-feature observations, two real outcome labels, and frozen disjoint splits; no qualifying dataset is recovered. |
| Preserve earlier work | PROJECT_HISTORY.md, OPEN_WORK.md, RECOVERY_MANIFEST.md and per-call ledger. | Conflicts, lost data and pending deployment tasks remain explicit rather than being discarded by the expanded feature request. |

## Artwork evidence

`recovery/artwork-validation.json` records read-only hash comparisons for all 21
AZRAEL originals. All 21 match the recovered files and ARTWORK.json. The full image
registry contains 25 assets including four earlier reference attachments. Hash
matching establishes byte preservation, not rendered UI correctness.

## Rebuild boundary

All rebuilt source, documentation, Git history and verification work live beneath
`AZRAEL_HOME=$HOME/azrael54`, not the former temporary working tree. Surviving
external data and deployments are not moved or modified. Necessary new
implementations remain subject to the per-file approval and preservation rules in
GAPS.md; this checklist is not a claim that those gaps have been implemented.
