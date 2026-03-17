#!/bin/bash
# Exponer python3 de Nix al PATH en runtime
export PATH="/root/.nix-profile/bin:/nix/var/nix/profiles/default/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

echo "Python3 path: $(which python3 2>/dev/null || echo 'NO ENCONTRADO')"
echo "Python3 version: $(python3 --version 2>/dev/null || echo 'N/A')"

node index.js
