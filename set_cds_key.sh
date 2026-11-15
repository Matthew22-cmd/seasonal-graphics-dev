#!/usr/bin/env bash
# Store the CDS / ECDS API key.
#
#   ./set_cds_key.sh <key>
#
# The key is written to .cdsapirc with mode 600 (gitignored), so it never
# appears in the git history, in a committed file, or in the process list.
#
# The SAME key works on both stores: the CDS (https://cds.climate.copernicus.eu)
# and the ECDS (https://ecds.ecmwf.int), which is where the ECMWF sub-seasonal
# ensemble (the EC46) comes from.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

KEY="${1:?usage: ./set_cds_key.sh <key>}"
FILE=".cdsapirc"

cat > "$FILE" <<EOF
url: https://cds.climate.copernicus.eu/api
key: $KEY
EOF
chmod 600 "$FILE"

# does it work?  the catalogue answers 200 for a key that is accepted
code=$(curl -s -o /dev/null -w '%{http_code}' -m 30 \
    -H "PRIVATE-TOKEN: $KEY" \
    "https://ecds.ecmwf.int/api/catalogue/v1/vocabularies/licences")
if [ "$code" != "200" ]; then
    echo "the key was not accepted by the store (HTTP $code) - it has been stored anyway" >&2
    exit 1
fi
echo "the key works on the store."

# and the licence list: this is what says whether the S2S licence is taken
curl -s -m 30 -H "PRIVATE-TOKEN: $KEY" \
    "https://ecds.ecmwf.int/api/profiles/v1/account/licences" | head -c 600
echo
