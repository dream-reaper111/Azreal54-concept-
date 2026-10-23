"""Named role contracts; registration does not imply trained weights or execution authority."""
PAIRS = (
 ('hydra', 'Hydra', 'Chains documented weaknesses into attack scenarios.', 'aegis', 'Aegis', 'Identifies critical control points that break attack chains.', 'attack-chain analysis'),
 ('crownfall', 'Crownfall', 'Reviews privilege escalation paths in authorized inputs.', 'citadel', 'Citadel', 'Finds dangerous permission relationships and recommends corrections.', 'identity and permissions'),
 ('cloudbreaker', 'Cloudbreaker', 'Reviews cloud trust boundaries in authorized configurations.', 'skyshield', 'Skyshield', 'Reviews evidence of cloud abuse and recommends containment.', 'cloud trust'),
 ('phantom_forge', 'Phantom Forge', 'Analyzes compromised-dependency scenarios from supplied evidence.', 'provenance', 'Provenance', 'Checks build-integrity evidence and traces suspicious components.', 'software supply chain'),
 ('blackout', 'Blackout', 'Plans bounded availability assessments for owned lab services.', 'lifeline', 'Lifeline', 'Assesses failover, service continuity and recovery evidence.', 'availability and continuity'),
 ('chimera', 'Chimera', 'Connects documented weaknesses across web, identity and networks.', 'nexus', 'Nexus', 'Connects supplied alerts into an evidence-backed incident narrative.', 'cross-domain correlation'),
 ('ghost_protocol', 'Ghost Protocol', 'Reviews intrusion-emulation plans for designated lab targets.', 'watchtower', 'Watchtower', 'Reviews supplied telemetry for behavioral anomalies.', 'behavioral analysis'),
 ('zero_day_forge', 'Zero-Day Forge', 'Reviews designated test software for candidate flaws.', 'bastion', 'Bastion', 'Assesses findings, proposes fixes and plans patch verification.', 'software flaw review'),
 ('doomsday', 'Doomsday', 'Plans worst-case assessments for an owned isolated digital twin.', 'phoenix', 'Phoenix', 'Reviews restoration evidence and verifies integrity checks.', 'recovery and integrity'),
 ('nomad', 'Nomad', 'Reviews authorized server security evidence across network and connectivity changes.', 'anchor', 'Anchor', 'Checks encryption, device identity and secure reconnection evidence.', 'portable servers'),
 ('worldline', 'Worldline', 'Reviews session and permission consistency during authorized host migration.', 'continuum', 'Continuum', 'Verifies policy continuity across migration and failover evidence.', 'application migration'),
 ('threshold', 'Threshold', 'Reviews approved unattended-equipment and exposed-port assessment plans.', 'gatekeeper', 'Gatekeeper', 'Correlates supplied physical-access records, device events and tamper alerts.', 'physical access'),
 ('iron_ghost', 'Iron Ghost', 'Reviews designated lab-device evidence for debug-interface and boot weaknesses.', 'root_of_trust', 'Root of Trust', 'Checks supplied firmware integrity, boot verification and hardware configuration evidence.', 'hardware interfaces'),
 ('trojan_dock', 'Trojan Dock', 'Plans authorized peripheral assessments using harmless designated test devices.', 'portwarden', 'Portwarden', 'Reviews peripheral restrictions and unexpected-device detection evidence.', 'peripheral devices'),
 ('drift', 'Drift', 'Reviews connection behavior during authorized wireless roaming assessments.', 'spectrum', 'Spectrum', 'Reviews supplied telemetry for suspicious wireless changes and policy violations.', 'wireless mobility'),
 ('cold_orbit', 'Cold Orbit', 'Reviews dummy-data accessibility on designated recovered lab devices.', 'vault', 'Vault', 'Reviews disk protection, credential revocation and recovery evidence.', 'lost or stolen equipment'),
)
ROLES = []
CONTRACTS = {}
for red_id, red_name, red_description, blue_id, blue_name, blue_description, domain in PAIRS:
    for role, name, description, group, counterpart in (
        (red_id, red_name, red_description, 'research', blue_id),
        (blue_id, blue_name, blue_description, 'defense', red_id),
    ):
        ROLES.append((role, name, description, group))
        CONTRACTS[role] = {
            'name': name, 'counterpart': counterpart, 'domain': domain,
            'status': 'pending_data_and_validation',
            'independent_weights': False,
            'live_web_collection_verified': False,
            'execution_authority': 'none granted by role registration',
            'shared_modes': None,
            'required_evidence': ['source URL or local source identity', 'retrieved_at UTC',
                                  'content SHA-256', 'coverage and uncertainty'],
        }

# Independent specialist contracts, not an offensive/defensive pair.
for role,name,description,group,domain in (
 ('hephaestus','HEPHAESTUS','Reviews designated lab reproductions and fuzzing evidence; pairs findings with detection and remediation.','research','authorized adversary research'),
 ('obsidian','OBSIDIAN','Minimizes unnecessary exposure and measures what remains; reviews privacy evidence and preserves accountable audit records.','defense','privacy and exposure assessment'),
 ('crucible','CRUCIBLE','Independently audits lab scope, evidence provenance and privacy claims; reports gaps for administrator review without executing tests.','analysis','independent scope and evidence audit'),
):
    ROLES.append((role,name,description,group))
    CONTRACTS[role]={'name':name,'counterpart':None,'domain':domain,'status':'pending_data_and_validation',
        'independent_weights':False,'live_web_collection_verified':False,'execution_authority':'none granted by role registration',
        'shared_modes':None,'required_evidence':['source identity','retrieved_at UTC','content SHA-256','coverage and uncertainty']}

SHARED_MODES = {
    'observe': {'label':'Observe','actions':['live_intel','tools','literature','wireless','radio','incident_review','tool_status','collect_sources','published_exploits','hak5_repos']},
    'analyze': {'label':'Analyze','actions':['analyze','admin_chat','team_brief']},
    'plan': {'label':'Plan','actions':['council_review','role_hive_review','topology','spread_model','train_poc','tool_plan','code_draft','online_brief']},
    'verify': {'label':'Verify','actions':[], 'workflow':'Inspect retained evidence and explicitly approve/execute a fixed internal lab recipe.'},
}
for contract in CONTRACTS.values():
    contract['shared_modes']=list(SHARED_MODES)

for role,name,description,group,domain,counterpart in (
 ('scada_red','SCADA · Red','Reviews supplied industrial configurations and documented weaknesses for authorized assessment planning.','research','industrial configuration and protocol review','scada_blue'),
 ('scada_blue','SCADA · Blue','Reviews supplied asset, segmentation, alarm and control-integrity evidence.','defense','industrial defensive evidence review','scada_red'),
 ('satellite_red','Satellite · Red','Reviews supplied satellite software, protocol and ground-segment configurations.','research','space-system software and configuration review','satellite_blue'),
 ('satellite_blue','Satellite · Blue','Reviews supplied telemetry integrity, ground-segment hardening and communications-policy evidence.','defense','space-system defensive evidence review','satellite_red'),
):
    ROLES.append((role,name,description,group))
    CONTRACTS[role]={'name':name,'counterpart':counterpart,'domain':domain,'status':'pending_data_and_validation',
        'independent_weights':False,'live_web_collection_verified':False,'execution_authority':'none granted by role registration',
        'shared_modes':list(SHARED_MODES),'required_evidence':['source identity','collection/publication/event dates','content SHA-256','coverage and uncertainty']}

for role,name,description,group,domain,counterpart in (
 ('poc_red','PoC · Red','Reviews designated-software reproducer proposals and supplied failure evidence.','research','authorized reproducibility review','poc_blue'),
 ('poc_blue','PoC · Blue','Reviews proposed reproducers, detection, patches and regression evidence.','defense','remediation and regression review','poc_red'),
 ('osint_junior','Geo Sentinel · Junior','Collects public reference metadata and reviews authorized asset information under analyst supervision.','analysis','public reference and authorized asset research',None),
 ('dark_signal','Dark Signal · Threat Research','Reviews lawfully obtained, redacted public threat reports and darknet-related references; no illicit-service access, purchases, credential handling or account access.','analysis','public threat reporting and source provenance','nightwatch'),
 ('nightwatch','Nightwatch · Exposure Defense','Triages public threat indicators, checks source provenance and recommends defensive exposure reduction from supplied evidence.','defense','threat indicator review and exposure defense','dark_signal'),
 ('fission','Fission · Critical-System Scenarios','Reviews synthetic, offline failure scenarios against nonoperational critical-infrastructure diagrams; no live control-system interaction or operational instructions.','research','synthetic critical-infrastructure resilience scenarios','containment'),
 ('containment','Containment · Critical-System Resilience','Reviews supplied defensive configurations and synthetic recovery scenarios for critical infrastructure; no connection to live control systems.','defense','critical-infrastructure detection and recovery evidence','fission'),
 ('event_horizon','Event Horizon · Graph Simulation','Examines bounded propagation hypotheses on synthetic graphs only; it does not discover hosts, execute payloads or control endpoints.','research','synthetic graph-risk simulation','sinkhole'),
 ('sinkhole','Sinkhole · Threat Containment','Reviews offline sinkhole and segmentation designs and supplied telemetry; it does not alter live routes or intercept unrelated traffic.','defense','offline containment design and telemetry review','event_horizon'),
 ('malware_lab_red','Malware Lab · Red','Reviews supplied malware-behavior reports and proposes harmless, non-propagating defensive-control tests; no malware creation, kernel modification, persistence, evasion or sample execution.','research','offline review and harmless defensive-control test planning','malware_lab_blue'),
 ('malware_lab_blue','Malware Lab · Blue','Reviews supplied process, memory, file-integrity and network evidence for possible rootkit, virus or worm activity; recommends detection, containment and recovery without changing live hosts.','defense','malware triage, detection and recovery review','malware_lab_red'),
):
    ROLES.append((role,name,description,group))
    CONTRACTS[role]={'name':name,'counterpart':counterpart,'domain':domain,'status':'pending_data_and_validation','independent_weights':False,
        'live_web_collection_verified':False,'execution_authority':'none granted by role registration','shared_modes':list(SHARED_MODES),
        'required_evidence':['source identity','collection/publication/event dates','content SHA-256','coverage and uncertainty']}
