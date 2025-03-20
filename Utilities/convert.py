#!/usr/bin/env python3

import sys
import yaml
import os
import argparse

class ListDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
        return super(ListDumper, self).increase_indent(flow, False)

class NewCrd:
    def __init__(self, group: str, name: str, kind: str, api_version: str, filename: str):
        self.group = group
        self.name = name
        self.kind = kind
        self.api_version = api_version
        self.filename = filename

class NewYamlDataStructure:
    def __init__(self):
        self.data = {}

    def add_entry(self, entry: NewCrd):
        if entry.group not in self.data:
            self.data[entry.group] = []
        self.data[entry.group].append({
            "name": entry.name,
            "kind": entry.kind,
            "apiVersion": entry.api_version,
            "filename": entry.filename
        })

    def save_to_yaml(self, file_path: str):
        with open(file_path, "w") as file:
            yaml.dump(self.data, file, Dumper=ListDumper)

class OldYamlDataStructure:
    def __init__(self):
        self.data = {}

    def load_from_file(self, file_path: str):
        with open(file_path, "r") as file:
            self.data = yaml.safe_load(file)

def guess_filename(group: str, name: str) -> str:
    result = f"{group}/{name}.json"
    if not os.path.exists(result):
        print(f"Warning: The file '{result}' does not exist.")
        return ""
    return result

def convert_old_to_new(old_data: OldYamlDataStructure) -> NewYamlDataStructure:
    new_data = NewYamlDataStructure()
    for groupKey, group in old_data.data.items():
        kindsContainer = group["kinds"]
        for idx, kinds in enumerate(kindsContainer):
            for name, crds in kinds.items():
                filename = guess_filename(groupKey, name)
                new_data.add_entry(NewCrd(
                    group=groupKey,
                    name=name,
                    kind=crds["kind"],
                    api_version=crds["apiVersion"],
                    filename=filename
                ))

    return new_data

def parse_arguments():
    parser = argparse.ArgumentParser(description="Convert CRD YAML files to a new structure.")
    parser.add_argument("input_file", type=str, help="Path to the input YAML file.")
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_arguments()
    input_file = args.input_file

    if not os.path.exists(input_file):
        print(f"Error: The file '{input_file}' does not exist.")
        sys.exit(1)

    old_data = OldYamlDataStructure()
    old_data.load_from_file(input_file)
    new_data = convert_old_to_new(old_data)
    new_data.save_to_yaml(input_file)
