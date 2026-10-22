# Optional: Synthea as the EHR source

The PoC runs fully on the custom Indian T2D generator (`data_gen/ehr_generator.py`). This folder shows
how to swap in **Synthea** (an open-source synthetic patient generator) as the source of Stream A.

## 1. Generate patients with Synthea

Requires Java 17+. Get the `synthea-with-dependencies.jar` release from the official Synthea project
(synthetichealth on GitHub). Then:

```bash
java -jar synthea-with-dependencies.jar -p 300 -s 42 \
     -c data_gen/synthea/synthea.properties \
     -m "metabolic_syndrome*"
```

* Synthea models type 2 diabetes in its metabolic-syndrome modules (`metabolic_syndrome_disease`,
  `metabolic_syndrome_care` in recent versions). Check the module list of the release you download.
* `synthea.properties` turns on CSV export and turns off the other exporters.
* Synthea's demographics are US-based. Indian context (diet, staple, South-Asian BMI bands, SNPs) is
  **imputed** by the adapter from the same priors the custom generator uses, and flagged in the
  `source` column.

## 2. Convert to the twin's EHR schema

```bash
python -m data_gen.synthea.adapter --synthea-dir output/csv --out data/ehr/patients_synthea.csv
```

The adapter keeps only living adults with a T2D diagnosis (SNOMED 44054006). It takes the latest value
of each LOINC lab and maps medications by name. Remaining columns are imputed. You can then set
`DT_EHR_SOURCE=synthea` (see `adapter.py`) or point the world simulator at the converted file.
