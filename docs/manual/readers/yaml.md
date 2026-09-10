---
title: "YAML Reader"
anchors:
  - readers.yaml
---

# YAML Reader

`uadas_core.readers.yaml_reader.YamlReader` -- `.yaml`, `.yml`.

Single-table, and the same shape as [the JSON reader](json.md) for the same underlying reason:
both formats can encode either a list of flat records (the common, directly tabular case) or a
single nested document, which pandas' `json_normalize` flattens rather than this reader
inventing its own flattening rules.

Parsed with `yaml.safe_load` specifically, never `yaml.load` -- the unsafe loader can construct
arbitrary Python objects from tags in the file, a real code-execution risk for a file format
this reader accepts from whatever the user opens. `safe_load` accepts every YAML construct a
legitimate tabular export would ever use.
