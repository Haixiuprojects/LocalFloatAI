from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.main import HardwareProfile, detect_hardware, load_config, STRICT_SYSTEM

profile = detect_hardware(None)
assert profile.selected_threads >= 1
assert profile.context_size in (1536, 2048, 3072, 4096)
assert profile.batch_size in (64, 96, 128, 192)
config = load_config()
assert config['host'] == '127.0.0.1'
assert config['port'] == 8765
assert 'Return only the requested result' in STRICT_SYSTEM
print('core tests passed')
print(profile)
