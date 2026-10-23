"""Stable UUID-based selection for single-GPU training work in the lab process."""
import os
import shutil
import subprocess


def inventory():
    executable = shutil.which('nvidia-smi')
    if not executable:
        return []
    try:
        result = subprocess.run([executable, '--query-gpu=index,uuid,name', '--format=csv,noheader'],
                                capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode:
        return []
    devices = []
    for row in result.stdout.splitlines():
        values = [part.strip() for part in row.split(',', 2)]
        if len(values) == 3:
            devices.append({'index': values[0], 'uuid': values[1], 'name': values[2]})
    return devices


def resolve_torch_device(torch):
    enabled = os.environ.get('AZRAEL_GPU_ENABLED', 'false').strip().lower() in {'1', 'true', 'yes', 'on'}
    if not enabled:
        return torch.device('cpu'), {'status': 'cpu', 'reason': 'GPU acceleration disabled by configuration', 'uuid': None}
    if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
        return torch.device('cpu'), {'status': 'cpu_fallback', 'reason': 'CUDA is unavailable to PyTorch', 'uuid': None}
    preferred = os.environ.get('AZRAEL_GPU_UUID', '').strip()
    visible = [value.strip() for value in os.environ.get('CUDA_VISIBLE_DEVICES', '').split(',') if value.strip()]
    if visible and visible != ['all'] and all(item.startswith('GPU-') for item in visible):
        if preferred and preferred in visible:
            index = visible.index(preferred)
        elif len(visible) == 1:
            index = 0
            preferred = visible[0]
        else:
            return torch.device('cpu'), {'status': 'cpu_fallback',
                'reason': 'Configured GPU UUID is not in CUDA_VISIBLE_DEVICES', 'uuid': preferred or None}
    elif len(visible) == 1 and visible[0].isdigit():
        index = 0
        rows = inventory()
        preferred = next((row['uuid'] for row in rows if row['index'] == visible[0]), preferred)
    elif preferred and len(visible) == 0:
        rows = inventory()
        candidates = [row for row in rows if row['uuid'] == preferred]
        if not candidates:
            return torch.device('cpu'), {'status': 'cpu_fallback', 'reason': 'Configured GPU UUID is unavailable', 'uuid': preferred}
        index = int(candidates[0]['index'])
    else:
        index = 0
        rows = inventory()
        if rows and index < len(rows):
            preferred = rows[index]['uuid']
    if index >= torch.cuda.device_count():
        return torch.device('cpu'), {'status': 'cpu_fallback', 'reason': 'Selected CUDA ordinal is not visible', 'uuid': preferred or None}
    device = torch.device(f'cuda:{index}')
    torch.cuda.set_device(device)
    return device, {'status': 'cuda', 'uuid': preferred or None,
                    'name': torch.cuda.get_device_name(device), 'index': index}
