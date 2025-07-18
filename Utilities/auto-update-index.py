#!/usr/bin/env python3

import sys
import yaml
import os
from typing import List
import argparse
from concurrent.futures import ProcessPoolExecutor
from typing import Dict, Union

class ListDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
        return super(ListDumper, self).increase_indent(flow, False)

class Crd:
    def __init__(self, group: str, name: str, kind: str, api_version: str, filename: str):
        self.group = group
        self.name = name
        self.kind = kind
        self.api_version = api_version
        self.filename = filename

class YamlDataStructure:
    def __init__(self):
        self.data: Dict[str, List[Crd]] = {} 

    def add_entry(self, entry: Crd):
        if entry.group not in self.data:
            self.data[entry.group] = []
        self.data[entry.group].append(entry)

    def save_to_yaml(self, file_path: str):
        raw_data: Dict[str, List[Dict[str, str]]] = {}
        for groupKey, group in self.data.items():
            raw_data[groupKey] = []
            for crd in group:
                raw_data[groupKey].append({
                    "name": crd.name,
                    "kind": crd.kind,
                    "apiVersion": crd.api_version,
                    "filename": crd.filename
                })

        with open(file_path, "w") as file:
            yaml.dump(raw_data, file, Dumper=ListDumper)

    def load_index_file(self, file: str):
        yaml_data: Union[Dict[str, List[Dict[str, str]]], None]
        with open(file, "r") as f:
            yaml_data = yaml.safe_load(f)
        if yaml_data is None:
            return

        for groupKey, group in yaml_data.items():
            for crd in group:
                self.add_entry(Crd(
                    group=groupKey,
                    name=crd["name"],
                    kind=crd["kind"],
                    api_version=crd["apiVersion"],
                    filename=crd["filename"]
                    ))


    def prune_removed_files(self, source_dir: str):
        nRemoved = 0
        groupKeys = list(self.data.keys())
        for key in groupKeys:
            group = self.data[key]
            filePaths = [os.path.join(source_dir, entry.filename) for entry in group]
            doKeep = [os.path.isfile(filePath) for filePath in filePaths]
            self.data[key] = [entry for entry, keep in zip(group, doKeep) if keep]
            nRemoved += len([1 for keep in doKeep if not keep])

            if len(self.data[key]) == 0:
                del self.data[key]

        return nRemoved

class SubResult_CrdCollection:
    def __init__(self, list: List[Crd], nSkipped: int):
        self.list: List[Crd] = list
        self.nSkipped = nSkipped
        self.nUpdated = len(list)

def strip_dot_slash(str: str) -> str:
    return str.lstrip("./")

def list_dirs_in_src_dir(src: str) -> List[str]:
    entries = [strip_dot_slash(os.path.join(src, name)) for name in os.listdir(src)]
    return [dir for dir in entries if os.path.isdir(dir)]

def CreateCrds(dir: str, org_data: YamlDataStructure) -> SubResult_CrdCollection:
    print(f"Processing directory {dir}")
    groupName = os.path.basename(dir)
    listing = [os.path.join(dir, file) for file in os.listdir(dir)]
    org_data_group = org_data.data.get(groupName, [])
    skip = [any(crd.filename == file for crd in org_data_group) for file in listing]
    nSkipped = len([1 for s in skip if s])
    listing = [file for file, skip in zip(listing, skip) if not skip]
    crds = [CreateCrdEntry(groupName, file) for file in listing if os.path.isfile(file) and file.endswith(".json")]
    crds = [crd for crd in crds if crd != None]
    return SubResult_CrdCollection(crds, nSkipped)

def GetFileDescription(file: str) -> str:
    with open(file, "r") as f:
        data = yaml.safe_load(f)
        return data.get("description", "")

def SearchForKindInDescription(lowercaseKind: str, description: str) -> str:
    lowercase_description = description.lower()
    offset = lowercase_description.find(lowercaseKind)
    if offset == -1:
        return lowercaseKind
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
      filename=filepath
    )

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate an index.yaml file from CRDs in a source directory.")
    parser.add_argument("source_directory", type=str, help="Path to the source directory containing CRDs.")
    parser.add_argument("index_file", type=str, help="Path to index.yaml to edit.")
    args = parser.parse_args()

    source = args.source_directory
    index_file = args.index_file

    data = YamlDataStructure()
    if os.path.exists(index_file):
        data.load_index_file(index_file)
    nRemoved = data.prune_removed_files(source)

    directories = list_dirs_in_src_dir(source)
    crd_entries: List[Crd] = []
    nSkipped = 0
    with ProcessPoolExecutor() as executor:
        future_dir_crds = {executor.submit(CreateCrds, dir, data): dir for dir in directories}
        for future in future_dir_crds:
            try:
                partial_result = future.result()
                nSkipped += partial_result.nSkipped
                if partial_result.nUpdated > 0:
                    crd_entries.extend(partial_result.list)
            except Exception as e:
                print(f"Error processing file {future_dir_crds[future]}: {e}", file=sys.stderr)

    for crd in crd_entries:
        data.add_entry(crd)
    data.save_to_yaml(index_file)
    print(f"YAML file saved as {index_file}.")
    print(f"Skipped {nSkipped} files.")
    print(f"Added {len(crd_entries)} files.")
    print(f"Removed {nRemoved} files.")
