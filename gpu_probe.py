"""Short CUDA runtime probe: matrix operation and one synthetic optimizer step per visible GPU."""
import json
import os
import sys

import torch

from gpu_runtime import inventory


def main():
    expected = [value for value in os.environ.get('AZRAEL_GPU_EXPECTED_UUIDS', '').split(',') if value]
    host_visible = {item['uuid'] for item in inventory()}
    missing = sorted(set(expected) - host_visible)
    if missing:
        raise RuntimeError('NVIDIA driver query did not expose expected CDI UUID(s): ' + ', '.join(missing))
    if not torch.cuda.is_available():
        raise RuntimeError(f'PyTorch CUDA is unavailable (torch={torch.__version__}, cuda={torch.version.cuda})')
    rows = []
    for index in range(torch.cuda.device_count()):
        device = torch.device(f'cuda:{index}')
        name = torch.cuda.get_device_name(device)
        prop = torch.cuda.get_device_properties(device)
        uuid = str(getattr(prop,'uuid',''))
        if not uuid.startswith('GPU-'):raise RuntimeError('CUDA framework did not report a hardware GPU UUID')
        if expected and uuid and uuid not in expected:
            continue
        with torch.cuda.device(device):
            free_before,total=torch.cuda.mem_get_info(device)
            torch.cuda.reset_peak_memory_stats(device)
            torch.manual_seed(540 + index)
            a = torch.randn((512, 512), device=device, dtype=torch.float16)
            b = torch.randn((512, 512), device=device, dtype=torch.float16)
            product = a @ b
            torch.cuda.synchronize(device)
            if not torch.isfinite(product).all().item():
                raise RuntimeError(f'CUDA matrix result was invalid on {name}')
            model = torch.nn.Linear(16, 4).to(device)
            optimizer = torch.optim.SGD(model.parameters(), lr=0.01)
            inputs = torch.randn((8, 16), device=device)
            targets = torch.randint(0, 4, (8,), device=device)
            before = next(model.parameters()).detach().clone()
            optimizer.zero_grad(set_to_none=True)
            loss = torch.nn.functional.cross_entropy(model(inputs), targets)
            loss.backward()
            optimizer.step()
            torch.cuda.synchronize(device)
            updated = not torch.equal(before, next(model.parameters()).detach())
            if not updated:
                raise RuntimeError(f'Optimizer did not update model weights on {name}')
            measured={'cuda_index': index, 'uuid': uuid, 'name': name,
                         'compute_capability': f'{prop.major}.{prop.minor}',
                         'memory_total_bytes': int(prop.total_memory),
                         'free_before_bytes':free_before,'peak_allocated_bytes':torch.cuda.max_memory_allocated(device),
                         'parameter_device':str(next(model.parameters()).device),'input_device':str(inputs.device),
                         'loss_device':str(loss.device),'gradient_device':str(next(model.parameters()).grad.device),
                         'matrix_operation': 'passed', 'training_forward_backward_optimizer_step': 'passed',
                         'loss': float(loss.item()), 'optimizer_update': True}
            del optimizer,model,inputs,targets,loss,before,a,b,product
            torch.cuda.empty_cache();torch.cuda.synchronize(device)
            measured.update(allocated_after_cleanup_bytes=torch.cuda.memory_allocated(device),
                            reserved_after_cleanup_bytes=torch.cuda.memory_reserved(device))
            rows.append(measured)
    if expected and not set(expected).issubset(host_visible):
        raise RuntimeError('One or more expected UUIDs were not visible to the NVIDIA driver')
    if expected and len(rows) < len(expected):
        raise RuntimeError(f'Expected {len(expected)} CUDA device(s); framework exercised {len(rows)}')
    if not rows:
        raise RuntimeError('No CUDA device completed the runtime probe')
    print(json.dumps({'status': 'passed', 'torch': torch.__version__, 'cuda_build': torch.version.cuda,
                      'framework_device_count': torch.cuda.device_count(), 'devices': rows}, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'status': 'failed', 'error_type': type(error).__name__,
                          'error': str(error)[:1500], 'torch': torch.__version__,
                          'cuda_build': torch.version.cuda}), file=sys.stderr)
        raise SystemExit(1)
