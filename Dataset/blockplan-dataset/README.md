# Block-Planning Dataset — SIH 2026, PS 26027

A reproducible synthetic benchmark built on **real Indian Railways
infrastructure and publicly available railway data**, with the maintenance and
block variables that are not public synthesised from documented railway rules,
distributions and explicit assumptions.

**What this is not.** This is not Indian Railways maintenance data. We have no
access to BDMS, TMS, SMMS, TDMS or COA and do not claim any. Every maintenance
job, block request, freight path and execution realisation in here is generated.

**What is real.** Station codes, names, coordinates, zones and states; train
numbers, names and their published stop sequences with arrival and departure
times; the corridor topology, which is *derived from* those real stop sequences
rather than asserted; and the protection regimes, corridor block lengths and
mandatory cross-department associations, each traced to an Indian Railways
manual with a citation and a confidence.

## Quick start

    pip install numpy pyyaml matplotlib
    cd src
    python generate_dataset.py --seed 42 --size medium
    python validate_dataset.py

`--source scaffold` builds a placeholder network so the pipeline can be
developed without network access. Scaffold station identifiers are of the form
`SCAFFOLD-nn` and the validator refuses to certify a scaffold build without an
explicit `--allow-scaffold`. Nothing produced in scaffold mode may be presented.

## Feeding it to the optimiser

    python blockplan_adapter.py --core /path/to/blockplan

This is the integration the Phase-16 audit found was missing: the optimiser
previously read no files at all. The adapter loads `config/*.yaml` over the
optimiser's module constants, loads `pairing_rules.csv` into its rule table, and
constructs its Job/Section/Train objects from the dataset CSVs.

## Reproducibility

    same --seed  ->  byte-identical dataset
    new  --seed  ->  a different maintenance week on the SAME real railway

Infrastructure is seed-invariant by construction: it comes from the downloaded
source files, whose SHA-256 prefixes are recorded in
`dataset/metadata/manifest.json`. Only demand, freight and execution vary.

## Layout

    config/     corridor.yaml  activities.yaml  rules.yaml  assumptions.yaml
    src/        generate_dataset.py  validate_dataset.py  blockplan_adapter.py
                dsgen/{sources,network,demand,scenarios,validate,report,provenance}.py
    dataset/
      raw/        downloaded source files (not committed; fetched on first run)
      processed/  the 11 dataset tables
      scenarios/  scenario definitions
      metadata/   manifest, DATA_PROVENANCE.csv, DATA_DICTIONARY.csv, validation, report
      maps/       figures
      scenarios/jobs/    per-scenario generated demand + scenario_jobs_manifest.csv
    docs/       data_sources.md  methodology.md  validation.md  evaluation.md

## Pipeline

    python generate_dataset.py --seed 42 --size medium     # base dataset
    python generate_scenario_jobs.py                       # per-scenario demand
    python validate_dataset.py --dataset ../dataset        # 28 checks
    python method_comparison.py --dataset .. --core ../../blockplan
    python score_execution.py  --dataset .. --core ../../blockplan
    python blockplan_adapter.py --dataset ../dataset --config ../config \
                                --core ../../blockplan      # all 8 scenarios

## Provenance classes

    A  real public data, used as published
    B  derived from real public data by a documented computation
    C  derived from an official Indian Railways rule or manual
    D  synthetic, generated from a documented distribution
    E  explicit modelling assumption

Every one of the 113 columns across 12 tables carries a class in
`DATA_DICTIONARY.csv`, and the generator fails the build if a column appears
with no provenance row.

## The one sentence to use

"A reproducible synthetic benchmark built on real Indian Railway infrastructure
and publicly available railway data, with unavailable maintenance and block
variables synthesised using documented railway rules, distributions and
explicit assumptions."
