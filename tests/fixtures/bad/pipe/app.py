from pathlib import Path
Path('out').write_text(Path('in').read_text())
