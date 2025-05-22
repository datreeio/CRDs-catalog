#!/usr/bin/env python3

import argparse
import os
import time
import requests
import yaml
from typing import Dict, List

BASE_URL = "https://datreeio.github.io/CRDs-catalog/"
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "datree_crds_catalog")
INDEX_FILENAME="index.yaml"
INDEX_FILE_MAX_AGE_DAYS = 7
INDEX_FILEPATH = os.path.join(CACHE_DIR, INDEX_FILENAME)

def download_index_yaml():
    os.makedirs(CACHE_DIR, exist_ok=True)

    do_download = True
    if os.path.isfile(INDEX_FILEPATH):
      mtime = os.path.getmtime(INDEX_FILEPATH)
      if (time.time() - mtime) / (60 * 60 * 24) < INDEX_FILE_MAX_AGE_DAYS:
        do_download = False

    if do_download:
        url = BASE_URL + INDEX_FILENAME
        print(f"Downloading {url} to {INDEX_FILEPATH}...")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        with open(INDEX_FILEPATH, 'wb') as f:
            f.write(response.content)

def load_index() -> Dict[str, List[Dict[str, str]]]:
    with open(INDEX_FILEPATH, 'r') as f:
        return yaml.safe_load(f)

def find_schema_url(api_version: str, kind: str, index_data: Dict[str, List[Dict[str, str]]]) -> str | None:
    api_version = api_version.lower()
    kind = kind.lower()

    def run_search():
      for _, entries in index_data.items():
          for entry in entries:
              if entry.get("apiVersion", "").lower() == api_version and entry.get("kind", "").lower() == kind:
                  filename = entry.get("filename")
                  if filename:
                      return BASE_URL + filename
                  else:
                      return None
      return None

    print(f"Finding schema URL for apiVersion={api_version} kind={kind}...", end="")
    schema_url = run_search()
    if schema_url:
      print(f"found: {schema_url}")
    else:
      print("not found.")
    return schema_url

def annotate_file(file_path: str, index_data: Dict[str, List[Dict[str, str]]]):
    docs = []
    with open(file_path, 'r') as f:
        content = f.read()
    if content.startswith("---"):
        content = content[3:]
    if content.endswith("---"):
        content = content[:-3]
    for doc in content.split("\n---\n"):
        doc = doc.strip()
        if not doc:
            continue
        data = list(yaml.safe_load_all(doc))[0] if doc else {}
        api_version = data.get("apiVersion") if "apiVersion" in data else None
        kind = data.get("kind") if "kind" in data else None

        lines = doc.splitlines()
        # Remove any existing schema comment
        lines = [ln for ln in lines if not ln.strip().startswith("# yaml-language-server: $schema")]

        if api_version and kind:
            schema_url = find_schema_url(api_version, kind, index_data)
            if schema_url:
                lines.insert(0, f"# yaml-language-server: $schema={schema_url}")
        docs.append("\n".join(lines))

    with open(file_path, 'w') as f:
        f.write("---\n")
        f.write("\n---\n".join(docs) + "\n")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("yaml_files", nargs="+", help="YAML files to annotate")
    args = parser.parse_args()

    download_index_yaml()
    index_data = load_index()

    for yf in args.yaml_files:
        annotate_file(yf, index_data)

if __name__ == "__main__":
    main()
