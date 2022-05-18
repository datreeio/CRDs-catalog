# CRDs Catalog

## Overview

This repository aggregates popular k8s CRDs in JSON schema format. These schemas are used by various tools such as Datree and Kubeconform to perform resource validation on custom resources.

Would you like your public CRs to be automatically validated by these tools in the future? No problem! Add your schemas to this repository by creating a pull request, and help us support popular CRs in future validations :)

## CRD Extractor

This repository also contains a handy utility that extracts all CRDs from a cluster and converts them to JSON schema.

### Supported Platforms

This utility supports **MacOS** and **Linux**.

### Prerequisites
The following programs are required to be installed on the machine running this utility:
* [python3](https://www.python.org/downloads/)
* [kubectl](https://kubernetes.io/docs/tasks/tools/#kubectl)

### Usage
To use the crd-extractor:
1. Download the [latest release](https://github.com/datreeio/CRDs-catalog/releases/latest/download/crd-extractor.zip) from this repository.
2. Extract, and run the utility:
```
./crd-extractor
```
