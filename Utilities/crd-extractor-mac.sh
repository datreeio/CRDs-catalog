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
    if ! "${KUBECTL_ARGS[@]}" get crds "$filename" -o yaml >"$TMP/$filename.yaml" 2>/dev/null; then
        printf "Warning: Failed to extract CRD: %s\n" "$filename" >&2
    fi
}

# Check if python3 is installed
if ! command -v python3 &>/dev/null; then
    printf "python3 is required for this utility, and is not installed on your machine\n"
    printf "please visit https://www.python.org/downloads/ to install it\n"
    exit 1
fi
# Check if kubectl is installed
if ! command -v kubectl &>/dev/null; then
    printf "kubectl is required for this utility, and is not installed on your machine\n"
    printf "please visit https://kubernetes.io/docs/tasks/tools/#kubectl to install it\n"
    exit 1
fi

# Note: This version is compatible with bash versions lower than 4.
# Remove strict dependency on bash-4 features (associative arrays, wait -n, etc).

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

# Read CRD list into a temporary file, then iterate lines (avoids bash-4 read -a with process substitution)
CRD_TMP_LIST=$(mktemp)
"${KUBECTL_ARGS[@]}" get crds 2>&1 | sed -n '/NAME/,$p' | tail -n +2 >"$CRD_TMP_LIST" || true

# Count lines to handle "no CRDs"
CRD_COUNT=0
if [ -s "$CRD_TMP_LIST" ]; then
    # count non-empty lines
    CRD_COUNT=$(grep -cve '^[[:space:]]*$' "$CRD_TMP_LIST" || true)
fi

# If no CRDs exist in the cluster, exit
if [ "$CRD_COUNT" -eq 0 ]; then
    printf "No CRDs found in the cluster, exiting...\n"
    rm -f "$CRD_TMP_LIST"
    exit 0
fi

# Extract CRDs from cluster
FETCHED_CRDS=0
PARALLELISM=10

# Function to wait until number of running background jobs is less than PARALLELISM.
# Uses polling since 'wait -n' is not available in older bash.
wait_for_slot() {
    while :; do
        # jobs -r -p lists running job pids; wc -l counts them
        running=$(jobs -r -p 2>/dev/null | wc -l)
        if [ "$running" -lt "$PARALLELISM" ]; then
            break
        fi
        sleep 0.1
    done
}

# Start fetching CRDs in background, with simple parallelism control
while IFS= read -r crd_line || [ -n "$crd_line" ]; do
    # Skip empty lines
    case "$crd_line" in
        ''|[[:space:]]*) continue ;;
    esac

    FETCHED_CRDS=$((FETCHED_CRDS + 1))
    printf "Fetching CRD %s/%s...\n" "$FETCHED_CRDS" "$CRD_COUNT"

    # start fetch in background
    fetch_crd "$crd_line" &

    # enforce parallelism
    wait_for_slot
done <"$CRD_TMP_LIST"

# wait for all background jobs to finish
wait

rm -f "$CRD_TMP_LIST"

# Convert crds to jsonSchema - output to temp directory to avoid mixing with existing schemas
CONVERTER_SCRIPT="$SCRIPT_DIR/openapi2jsonschema.py"
export FILENAME_FORMAT="{fullgroup}_{kind}_{version}"
cd "$CONVERSION_TMP"
python3 "$CONVERTER_SCRIPT" "$TMP"/*.yaml
conversionResult=$?

# Track which groups we're processing in this run using a plain list
PROCESSED_GROUPS_LIST=""

# Find newly generated schemas in the conversion temp directory
NEW_SCHEMAS=()
# nullglob may not be set; handle glob expansion safely
for schema in "$CONVERSION_TMP"/*.json; do
    if [ -f "$schema" ]; then
        NEW_SCHEMAS+=("$schema")
    fi
done

# Only proceed if we have new schemas
if [ "${#NEW_SCHEMAS[@]}" -gt 0 ]; then
    # Copy and rename files to support kubeval
    rm -rf "$SCHEMAS_DIR/master-standalone"
    mkdir -p "$SCHEMAS_DIR/master-standalone"
    # Use a loop to avoid failure when no files
    for f in "$CONVERSION_TMP"/*.json; do
        [ -f "$f" ] || continue
        cp "$f" "$SCHEMAS_DIR/master-standalone/"
    done
    # rename underscores to "-stable-"
    find "$SCHEMAS_DIR/master-standalone" -name '*json' -print0 | while IFS= read -r -d '' file; do
        # Replace first occurrence of '_' with '-stable-' after removing leading group part is not desired here;
        # original script used pattern replacement ${0/\_/-stable-} — replicate replacing first underscore with -stable-
        base=$(basename "$file")
        dir=$(dirname "$file")
        newbase=$(echo "$base" | sed 's/_/-stable-/')
        mv -f "$file" "$dir/$newbase"
    done

    # Organize schemas by group
    for schema in "${NEW_SCHEMAS[@]}"; do
        crdFileName=$(basename "$schema")
        crdGroup=$(echo "$crdFileName" | cut -d"_" -f1)
        outName=$(echo "$crdFileName" | cut -d"_" -f2-)
        mkdir -p "$SCHEMAS_DIR/$crdGroup"
        cp "$schema" "$SCHEMAS_DIR/$crdGroup/$outName"
        # record group if not already recorded
        case " $PROCESSED_GROUPS_LIST " in
            *" $crdGroup "*) ;;
            *) PROCESSED_GROUPS_LIST="$PROCESSED_GROUPS_LIST $crdGroup" ;;
        esac
    done

    # Copy organized schemas to git repository (when not using custom OUTPUT_DIR)
    if [ -z "${OUTPUT_DIR:-}" ]; then
        printf "\nCopying schemas to repository...\n"
        # iterate over unique groups in PROCESSED_GROUPS_LIST
        for crdGroup in $PROCESSED_GROUPS_LIST; do
            [ -z "$crdGroup" ] && continue
            groupDir="$SCHEMAS_DIR/$crdGroup"
            if [ -d "$groupDir" ]; then
                # Copy to parent directory of Utilities folder
                repoDir="$(dirname "$SCRIPT_DIR")/$crdGroup"
                mkdir -p "$repoDir"
                # copy json files
                for jf in "$groupDir"/*.json; do
                    [ -f "$jf" ] || continue
                    cp -r "$jf" "$repoDir/" 2>/dev/null || true
                done
                printf "  Copied %s schemas\n" "$crdGroup"
            fi
        done
    fi
fi

CYAN='\033[0;36m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

if [ "$conversionResult" -eq 0 ] && [ "${#NEW_SCHEMAS[@]}" -gt 0 ]; then
    printf "\n${GREEN}Successfully converted ${FETCHED_CRDS} CRDs to JSON schema${NC}\n"
    printf "Schemas saved to: ${CYAN}${SCHEMAS_DIR}${NC}\n"

    if [ -z "${OUTPUT_DIR:-}" ] && [ -n "$PROCESSED_GROUPS_LIST" ]; then
        printf "\n${GREEN}Schemas organized by API group and copied to:${NC}\n"
        # print unique repo dirs sorted
        tmp_sorted=$(mktemp)
        for crdGroup in $PROCESSED_GROUPS_LIST; do
            [ -z "$crdGroup" ] && continue
            repoDir="$(dirname "$SCRIPT_DIR")/$crdGroup"
            printf "  - %s/\n" "$repoDir"
        done | sort -u >"$tmp_sorted"
        cat "$tmp_sorted"
        rm -f "$tmp_sorted"
    fi

    printf "\nTo validate a CR using various tools, run the relevant command:\n"
    printf "\n- ${CYAN}datree:${NC}\n\$ datree test /path/to/file\n"
    printf "\n- ${CYAN}kubeconform:${NC}\n\$ kubeconform -summary -output json -schema-location default -schema-location '${SCHEMAS_DIR}/{{ .Group }}/{{ .ResourceKind }}_{{ .ResourceAPIVersion }}.json' /path/to/file\n"
    printf "\n- ${CYAN}kubeval:${NC}\n\$ kubeval --additional-schema-locations file:\"${SCHEMAS_DIR}\" /path/to/file\n\n"
fi