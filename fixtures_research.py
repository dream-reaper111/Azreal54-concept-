# ARCHIVED TEST FIXTURES ONLY: never operational evidence or training evaluation.
"""Four educational research classifiers trained on explicitly synthetic fixtures."""
import argparse
import hashlib
import json
from pathlib import Path
import random

import numpy as np
import torch
from sklearn.model_selection import train_test_split
from lab import fit, checkpoint, probabilities
from model import ROOT, FEATURES, network
import storage_paths

OUT = storage_paths.training_root(ROOT,'models-research')
TASKS = {
 'malware_static': {
  'memory_imports_candidate': 'Static feature report: imports VirtualAlloc WriteProcessMemory CreateRemoteThread; unsigned; section entropy high.',
  'persistence_imports_candidate': 'Static feature report: imports RegSetValueEx CreateService; strings include startup and Run key.',
  'ordinary_fixture': 'Static feature report: imports printf fopen fclose; signed utility; ordinary text resources.'},
 'malware_behavior': {
  'file_encryption_like': 'Synthetic events: repeated file reads and encrypted writes, renamed extensions and ransom-note-like filenames.',
  'persistence_like': 'Synthetic events: startup registry entry added, service created and scheduled task registered.',
  'network_beacon_like': 'Synthetic events: repeated periodic outbound connections with uniform timing and small payloads.',
  'ordinary_fixture': 'Synthetic events: user opens a document, application renders content and exits.'},
 'bounty_review': {
  'sql_injection_candidate': 'Fixture code: query = "SELECT * FROM users WHERE id=" + request.args["id"]; cursor.execute(query)',
  'xss_candidate': 'Fixture code: return "<div>" + request.args["message"] + "</div>" without output escaping.',
  'path_traversal_candidate': 'Fixture code: filename = request.args["file"]; return open(base + filename).read() without path containment check.',
  'safer_example': 'Fixture code: cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,)); HTML output escaped; resolved paths checked against base.'},
 'cve_triage': {
  'insufficient_evidence': 'Report: suspected vulnerability, no reproducer, no crash log, affected version unknown.',
  'reproducible_crash_candidate': 'Report: deterministic parser crash on minimized local fixture; affected version recorded; no memory safety evidence.',
  'known_issue_candidate': 'Report: behavior matches an existing vendor advisory and known CVE; affected version agrees; existing patch identified.',
  'memory_safety_candidate': 'Report: local sanitizer reports heap-buffer-overflow with a minimized fixture and stack trace; exact version and digest recorded.'}}
LIMIT = 'Synthetic educational classifier only. No real malware benchmark, code-flow proof, runtime reproduction, exploitability confirmation, or CVE assignment.'


def train_research(out=OUT):
    torch.set_num_threads(2)
    out = Path(out)
    if out.exists():
        raise ValueError('Choose a fresh output directory to preserve previous weights')
    out.mkdir(parents=True)
    report = {'training_data': 'Generated synthetic text fixtures, no real malware or executable payloads', 'limitations': LIMIT, 'models': {}}
    for name, classes in TASKS.items():
        labels = sorted(classes)
        texts, targets = [], []
        for index, label in enumerate(labels):
            for i in range(320):
                marker = hashlib.sha256(f'{name}:{label}:{i}'.encode()).hexdigest()[:12]
                text = classes[label]
                # Metadata augmentation changes fixtures; it does not create new independent real-world observations.
                prefix = ['Analyst fixture', 'Local test case', 'Educational sample', 'Synthetic report'][i % 4]
                texts.append(f'{prefix} {marker}; version {i % 11}.{i % 7}; {text}')
                targets.append(index)
        pool, test = train_test_split(np.arange(len(texts)), test_size=.2, stratify=targets, random_state=103)
        train, validation = train_test_split(pool, test_size=.2, stratify=np.array(targets)[pool], random_state=103)
        model, metrics = fit(texts, targets, train, validation, test, labels, seed=103)
        checkpoint(model, labels, out / f'{name}.pt')
        metrics['coverage'] = 'Random split of metadata-augmented templates; templates occur across splits. Measures fixture fitting only.'
        report['models'][name] = metrics
        print(f'{name}: fixture accuracy={metrics["metrics"]["accuracy"]:.3f}', flush=True)
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


class Research:
    def __init__(self, bus, directory=OUT):
        self.bus, self.models, self.labels = bus, {}, {}
        self.fingerprints = {}
        for name in TASKS:
            path = Path(directory) / f'{name}.pt'
            saved = torch.load(path, map_location='cpu', weights_only=True)
            if saved['version'] != 1 or saved['features'] != FEATURES:
                raise ValueError('Incompatible research checkpoint')
            model = network(len(saved['labels'])); model.load_state_dict(saved['state_dict']); model.eval()
            self.models[name], self.labels[name] = model, saved['labels']
            self.fingerprints[name] = hashlib.sha256(path.read_bytes()).hexdigest()

    def analyze(self, role, text):
        if role not in TASKS or not isinstance(text, str) or not 1 <= len(text) <= 4096:
            raise ValueError('Select a research role and provide 1 through 4096 characters of text')
        sha = hashlib.sha256(text.encode()).hexdigest()
        self.bus.send('controller', role, 'research_request', {'input_sha256': sha, 'mode': 'text_analysis_only'})
        p = probabilities(self.models[role], [text])[0]
        scores = {label: round(float(score), 6) for label, score in zip(self.labels[role], p)}
        result = {'input_sha256': sha, 'category': self.labels[role][int(p.argmax())], 'scores': scores, 'reason': LIMIT}
        self.bus.send(role, 'defender', 'research_assessment', result)
        self.bus.send('defender', 'controller', 'defense_review', {'decision': 'unverified_candidate', 'reason': LIMIT})
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default=str(OUT))
    args = parser.parse_args()
    train_research(args.out)
