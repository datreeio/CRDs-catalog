#!/usr/bin/env bash
# shellcheck disable=SC2059

set -euo pipefail

# Support kubectl context via KUBECTL_CONTEXT environment variable
KUBECTL_ARGS=(kubectl)
if [ -n "${KUBECTL_CONTEXT:-}" ]; then
    KUBECTL_ARGS=(kubectl --context="${KUBECTL_CONTEXT}")
fi

fetch_crd() {
    filename=${1%% *}
    "${KUBECTL_ARGS[@]}" get crds "$filename" -o yaml >"$TMP/$filename.yaml" 2>&1
}

# Check if python3 is installed
if ! command -v python3 &>/dev/null; then
    printf "python3 is required for this utility, and is not installed on your machine"
    printf "please visit https://www.python.org/downloads/ to install it"
    exit 1
fi
# Check if kubectl is installed
if ! command -v kubectl &>/dev/null; then
    printf "kubectl is required for this utility, and is not installed on your machine"
    printf "please visit https://kubernetes.io/docs/tasks/tools/#kubectl to install it"
    exit 1
fi
# Check if the major version is 4 or higher
if [[ ! ${BASH_VERSION%%.*} -ge 4 ]]; then
    printf "Bash version is lower than 4"
    printf "please visit https://www.gnu.org/software/bash/ to install it"
    exit 1
fi

# Check if the pyyaml module is installed
if ! echo 'import yaml' | python3 &>/dev/null; then
    printf "the python3 module 'yaml' is required, and is not installed on your machine.\n"

    while true; do
        read -r -p "Do you wish to install this program? (y/n) " yn
        case $yn in
        [Yy])
            pip3 install pyyaml
            break
            ;;
        "")
            pip3 install pyyaml
            break
            ;;
        [Nn])
            echo "Exiting..."
            exit
            ;;
        *) echo "Please answer 'y' (yes) or 'n' (no)." ;;
        esac
    done
fi

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Create temp folders for CRDs and conversion
TMP=$(mktemp -d)
CONVERSION_TMP=$(mktemp -d)
trap 'rm -rf "$TMP" "$CONVERSION_TMP"' EXIT

# Create final schemas directory
# Use current directory if OUTPUT_DIR is set, otherwise use default
SCHEMAS_DIR=${OUTPUT_DIR:-$HOME/.datree/crdSchemas}
mkdir -p "$SCHEMAS_DIR"

# Get a list of all CRDs
printf "Fetching list of CRDs..."
if [ -n "${KUBECTL_CONTEXT:-}" ]; then
    printf " (using context: %s)\n" "${KUBECTL_CONTEXT}"
else
    printf "\n"
fi
IFS=$'\n' read -r -d '' -a CRD_LIST < <("${KUBECTL_ARGS[@]}" get crds 2>&1 | sed -n '/NAME/,$p' | tail -n +2 && printf '\0')

# If no CRDs exist in the cluster, exit
if [ ${#CRD_LIST[@]} == 0 ]; then
    printf "No CRDs found in the cluster, exiting...\n"
    exit 0
fi

# Extract CRDs from cluster
FETCHED_CRDS=0
PARALLELISM=10
for crd in "${CRD_LIST[@]}"; do
    printf "Fetching CRD %s/%s...\n" $((FETCHED_CRDS + 1)) ${#CRD_LIST[@]}

    # Fetch CRD
    fetch_crd "$crd" &

    # allow to execute up to $PARALLELISM jobs in parallel
    if [[ $(jobs -r -p | wc -l) -ge $PARALLELISM ]]; then
        # now there are $PARALLELISM jobs already running, so wait here for any job
        # to be finished so there is a place to start next one.
        wait -n
    fi
    ((++FETCHED_CRDS))
done
# shellcheck disable=SC2046
wait $(jobs -p)


# Convert crds to jsonSchema - output to temp directory to avoid mixing with existing schemas
CONVERTER_SCRIPT="$SCRIPT_DIR/openapi2jsonschema.py"
export FILENAME_FORMAT="{fullgroup}_{kind}_{version}"
cd "$CONVERSION_TMP"
python3 "$CONVERTER_SCRIPT" "$TMP"/*.yaml
conversionResult=$?

# Track which groups we're processing in this run
declare -A PROCESSED_GROUPS

# Find newly generated schemas in the conversion temp directory
NEW_SCHEMAS=()
shopt -s nullglob
for schema in "$CONVERSION_TMP"/*.json; do
    [ -f "$schema" ] && NEW_SCHEMAS+=("$schema")
done
shopt -u nullglob

# Only proceed if we have new schemas
if [ ${#NEW_SCHEMAS[@]} -gt 0 ]; then
    # Copy and rename files to support kubeval
    rm -rf "$SCHEMAS_DIR/master-standalone"
    mkdir -p "$SCHEMAS_DIR/master-standalone"
    cp "$CONVERSION_TMP"/*.json "$SCHEMAS_DIR/master-standalone/" 2>/dev/null
    find "$SCHEMAS_DIR/master-standalone" -name '*json' -exec bash -c ' mv -f $0 ${0/\_/-stable-}' {} \;

    # Organize schemas by group
    for schema in "${NEW_SCHEMAS[@]}"; do
        crdFileName=$(basename "$schema")
        crdGroup=$(echo "$crdFileName" | cut -d"_" -f1)
        outName=$(echo "$crdFileName" | cut -d"_" -f2-)
        mkdir -p "$SCHEMAS_DIR/$crdGroup"
        cp "$schema" "$SCHEMAS_DIR/$crdGroup/$outName"
        PROCESSED_GROUPS[$crdGroup]=1
    done

    # Copy organized schemas to git repository (when not using custom OUTPUT_DIR)
    if [ -z "${OUTPUT_DIR:-}" ]; then
        printf "\nCopying schemas to repository...\n"
        for crdGroup in "${!PROCESSED_GROUPS[@]}"; do
            groupDir="$SCHEMAS_DIR/$crdGroup"
            if [ -d "$groupDir" ]; then
                # Copy to parent directory of Utilities folder
                repoDir="$(dirname "$SCRIPT_DIR")/$crdGroup"
                mkdir -p "$repoDir"
                cp -r "$groupDir"/*.json "$repoDir/" 2>/dev/null || true
                printf "  Copied %s schemas\n" "$crdGroup"
            fi
        done
    fi
fi

CYAN='\033[0;36m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

if [ $conversionResult == 0 ] && [ ${#NEW_SCHEMAS[@]} -gt 0 ]; then
    printf "\n${GREEN}Successfully converted ${FETCHED_CRDS} CRDs to JSON schema${NC}\n"
    printf "Schemas saved to: ${CYAN}${SCHEMAS_DIR}${NC}\n"

    if [ -z "${OUTPUT_DIR:-}" ] && [ ${#PROCESSED_GROUPS[@]} -gt 0 ]; then
        printf "\n${GREEN}Schemas organized by API group and copied to:${NC}\n"
        for crdGroup in "${!PROCESSED_GROUPS[@]}"; do
            repoDir="$(dirname "$SCRIPT_DIR")/$crdGroup"
            printf "  - %s/\n" "$repoDir"
        done | sort -u
    fi

    printf "\nTo validate a CR using various tools, run the relevant command:\n"
    printf "\n- ${CYAN}datree:${NC}\n\$ datree test /path/to/file\n"
    printf "\n- ${CYAN}kubeconform:${NC}\n\$ kubeconform -summary -output json -schema-location default -schema-location '${SCHEMAS_DIR}/{{ .Group }}/{{ .ResourceKind }}_{{ .ResourceAPIVersion }}.json' /path/to/file\n"
    printf "\n- ${CYAN}kubeval:${NC}\n\$ kubeval --additional-schema-locations file:\"${SCHEMAS_DIR}\" /path/to/file\n\n"
fi
