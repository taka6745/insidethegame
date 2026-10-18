"""Install the engineering library into a local mcp-excalidraw-server package.

Usage: python3 install-local.py /path/to/node_modules/mcp-excalidraw-server
The adapter hook is checked explicitly; unsupported bundle versions are rejected.
"""
import pathlib
import re
import shutil
import sys

source = pathlib.Path(__file__).resolve().parent
frontend = pathlib.Path(sys.argv[1]).resolve() / 'dist/frontend'
bundles = [p for p in (frontend / 'assets').glob('index-*.js')
           if 'excalidraw-canvas-library' in p.read_text()]
if len(bundles) != 1:
    raise SystemExit('Expected one canvas bundle; nothing changed.')
bundle = bundles[0]
text = bundle.read_text()
import_line = 'import {libraryAdapter as engineeringLibraryAdapter} from "/library-adapter.mjs";\n'
if import_line not in text:
    pattern = r'hxe=\{load:.*?(?=,fxe=1200)'
    updated, count = re.subn(pattern, 'hxe=engineeringLibraryAdapter', text)
    if count != 1:
        raise SystemExit('Unsupported library adapter hook; nothing changed.')
    backup = bundle.with_suffix('.js.before-engineering-library')
    if not backup.exists():
        shutil.copy2(bundle, backup)
    text = import_line + updated
for name in ('engineering.excalidrawlib', 'library-adapter.mjs'):
    shutil.copy2(source / name, frontend / name)
bundle.write_text(text)
print('Engineering library installed. Reload the canvas and open Library.')
