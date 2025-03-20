#!/usr/bin/env python3

import sys
import yaml
import os
from typing import List
import argparse
from concurrent.futures import ProcessPoolExecutor

class Crd:
    def __init__(self, group: str, name: str, kind: str, api_version: str, description: str):
        self.group = group
        self.name = name
        self.kind = kind
        self.api_version = api_version
        self.description = description

class YamlDataStructure:
    def __init__(self):
        self.data = {}

    def add_entry(self, entry: Crd):
        if entry.group not in self.data:
            self.data[entry.group] = []
        self.data[entry.group].append({
            entry.name: {
                "kind": entry.kind,
                "apiVersion": entry.api_version,
                "description": entry.description
            }
        })

    def save_to_yaml(self, file_path: str):
        with open(file_path, "w") as file:
            yaml.dump(self.data, file, default_flow_style=False)

def list_dirs_in_src_dir(src: str) -> List[str]:
    entries = [os.path.join(src, name) for name in os.listdir(src)]
    return [dir for dir in entries if os.path.isdir(dir)]

def CreateCrds(dir: str) -> List[Crd]:
    print(f"Processing directory {dir}")
    groupName = os.path.basename(dir)
    listing = [os.path.join(dir, file) for file in os.listdir(dir)]
    crds = [CreateCrdEntry(groupName, file) for file in listing if os.path.isfile(file) and file.endswith(".json")]
    return [crd for crd in crds if crd != None]

def GetFileDescription(file: str) -> str:
    with open(file, "r") as f:
        data = yaml.safe_load(f)
        return data.get("description", "")

def SearchForKindInDescription(lowercaseKind: str, description: str) -> str:
    lowercase_description = description.lower()
    offset = lowercase_description.find(lowercaseKind)
    if offset == -1:
        return ""
    return description[offset:offset + len(lowercaseKind)]

def CreateCrdEntry(group: str, filepath: str):
    file_basename = os.path.basename(filepath)

    # file ends with .json. Strip this away
    filename = file_basename.split(".")[0]

    parts = filename.split('_')
    if len(parts) != 2:
      print(f"Error: Unexpected file name format: {filename}", file=sys.stderr)
      return None
    name, version = parts

    description = GetFileDescription(filepath)
    kind = SearchForKindInDescription(name, description)

    return Crd(
      group=group,
      name=f"{name}_{version}",
      kind=kind,
      api_version=f"{group}/{version}",
      description=description
    )

# Example usage
if __name__ == "__main__":
    yaml_structure = YamlDataStructure()

    parser = argparse.ArgumentParser(description="Generate an index.yaml file from CRDs in a source directory.")
    parser.add_argument("source_directory", type=str, help="Path to the source directory containing CRDs.")
    parser.add_argument("output_file", type=str, help="Path to the output YAML file.")
    args = parser.parse_args()

    source = args.source_directory
    output_file = args.output_file

    directories = list_dirs_in_src_dir(source)
    crd_entries: List[Crd] = []
    with ProcessPoolExecutor() as executor:
        future_dir_crds = {executor.submit(CreateCrds, dir): dir for dir in directories}
        for future in future_dir_crds:
            try:
                dir_crds = future.result()
                if dir_crds:
                    crd_entries.extend(dir_crds)
            except Exception as e:
                print(f"Error processing file {future_dir_crds[future]}: {e}", file=sys.stderr)

    for crd in crd_entries:
        yaml_structure.add_entry(crd)
    yaml_structure.save_to_yaml(output_file)
    print(f"YAML file saved as {output_file}.")
