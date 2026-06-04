# LOINC

> ⚠️ **Alpha / experimental.** This ingest is an early-stage prototype. Sources, modeling
> decisions (predicates, node categories), and coverage are provisional and expected to
> change — see **Modeling** and **Versioning** below. Not yet a stable production ingest.

[LOINC](https://loinc.org/) (Logical Observation Identifiers Names and Codes) is the universal
standard for identifying laboratory tests, clinical measurements, and observations.

This ingest provides the **clinical measurement layer for the BioData Catalyst (BDC) knowledge
graph** (built on the Monarch KG). The BDC KG has a coverage gap for measurement-type concepts —
it carries no clinical lab / measurement nodes — and this ingest fills that gap: each LOINC code
becomes a `biolink:ClinicalMeasurement` node, decomposed into **what it measures** (OBO ontologies),
**what an abnormal result indicates** (HPO phenotypes, by outcome), and **where it sits** (an is_a
hierarchy). The pipeline is automated from freely-redistributable sources — no account-gated downloads.

- [LOINC](https://loinc.org/) · [OMOP2OBO](https://github.com/callahantiff/OMOP2OBO) · [CompLOINC](https://github.com/loinc/comp-loinc)

## Source material

Three upstreams, each contributing a different layer. All three are freely pullable; their versions
are recorded in `output/release-metadata.yaml` (see **Versioning**).

| source | license | layer it provides |
|---|---|---|
| **LOINC release table** — via the [Tuva Project](https://thetuvaproject.com/terminology/loinc) public-S3 repackage | LOINC (free, redistributable; attribution required) | the ~104k leaf measurement **nodes** |
| **[OMOP2OBO Measurement Mappings](https://zenodo.org/records/6949858)** (Tiffany Callahan) | MIT | the OBO **edges** — analyte/specimen/etc. (ChEBI, UBERON, CL, PR, NCBITaxon) and phenotype (HPO) |
| **[CompLOINC](https://github.com/loinc/comp-loinc)** — ontologized LOINC in OWL | MIT | the **is_a hierarchy** + the LP-Part / CC-grouper backbone nodes |

These are chosen over the official files for automation and licensing. The canonical LOINC table is
account-gated, so the node table comes from Tuva's license-clean repackage. The HPO mappings
originate in **loinc2hpo** (Zhang et al.) but are consumed here already integrated and extended via
OMOP2OBO. And rather than build an is_a tree from LOINC's gated multiaxial-hierarchy file, the
hierarchy comes from CompLOINC, which already expresses LOINC as an OWL ontology with the hierarchy
built in.

## Shape of the output

One LOINC measurement, fully decomposed. Worked example — `LOINC:2356-4`, *"Glucose-6-Phosphate
dehydrogenase [Presence] in Red Blood Cells"* (a G6PD enzyme test on red blood cells):

```
                      LOINC:2356-4  ── biolink:ClinicalMeasurement
              "G6PD [Presence] in Red Blood Cells"
                            │
   what it measures  (biolink:related_to — compositional, outcome-independent)
     ├─ CHEBI:36080      protein                                  (analyte, broad)
     ├─ PR:P11413        glucose-6-phosphate 1-dehydrogenase      (analyte, precise)
     ├─ UBERON:0000178   blood                                    (specimen / system)
     ├─ CL:0000232       erythrocyte                              (specimen cell type)
     └─ NCBITaxon:9606   Homo sapiens                             (organism)

   what an abnormal result means  (biolink:correlated_with — outcome-qualified)
     ├─ HP:0410189  Increased G6PD level in red blood cells   [result=Positive, negated=false]
     └─ HP:0410184  Abnormal G6PD level in red blood cells    [result=Negative, negated=true]

   where it sits  (biolink:subclass_of — is_a)
     └─ LOINC:CC-LP31392-1  "Enzymes Component Class"  ──is_a──▶  LOINC:lc0000001 (root)
```

That single node touches five OBO ontologies (the measurement decomposed by axis), two outcome-typed
phenotype edges, and the enzyme branch of the hierarchy. **991 leaf codes carry this full set**;
most carry a subset (see coverage notes below).

### Totals

**107,791 nodes** (104,672 leaf + 3,119 backbone) · **50,700 edges** (15,444 compositional + 10,946 phenotype + 24,310 is_a).

### Leaf measurement nodes — 104,672

Every LOINC code from the release table. Deprecated codes are **kept and flagged** (not dropped) so
that hierarchy/edges referencing codes deprecated since an upstream's vintage don't dangle.

**Biolink Captured:**

- `biolink:ClinicalMeasurement`
    - id (`LOINC:<code>`)
    - name (long common name, falling back to short name)
    - has_attribute_type (the LOINC code itself — required slot; see Modeling)
    - deprecated (`true` for the 4,945 deprecated codes, else absent)
    - provided_by (`["infores:loinc"]`)

### Part / grouper backbone nodes — 3,119

The LOINC **Parts** (`LP…`) and CompLOINC **groupers** (`CC-…`) that the leaf codes hang from. These
don't exist in the flat LOINC table, so they're emitted from CompLOINC with their OWL labels.

**Biolink Captured:**

- `biolink:ClinicalMeasurement`
    - id (`LOINC:LP…` or `LOINC:CC-…`)
    - name (CompLOINC `rdfs:label`)
    - has_attribute_type (the id itself)
    - provided_by (`["infores:comploinc"]`)

### Compositional edges — 15,444 (CHEBI 4,294 · UBERON 5,025 · NCBITaxon 3,743 · PR 1,938 · CL 444)

What characteristic the assay measures, split across OBO ontologies by axis. Outcome-independent.

**Biolink Captured:**

- `biolink:Association`
    - id (random uuid)
    - subject (`LOINC:<code>`)
    - predicate (`biolink:related_to` — provisional; see Modeling)
    - object (`CHEBI:` / `UBERON:` / `CL:` / `PR:` / `NCBITaxon:`)
    - primary_knowledge_source (`infores:omop2obo`)
    - aggregator_knowledge_source (`["infores:monarchinitiative"]`)
    - knowledge_level / agent_type (from OMOP2OBO `MAPPING_CATEGORY`; see Modeling)

### Phenotype edges — 10,946

What an abnormal result indicates, as an HPO phenotype. The result interpretation
(High / Low / Normal / Positive / Negative) selects the HP term and the negation: a Normal/Negative
result means the phenotype is *absent* (`negated=true`).

**Biolink Captured:**

- `biolink:Association`
    - id (random uuid)
    - subject (`LOINC:<code>`)
    - predicate (`biolink:correlated_with` — provisional; see Modeling)
    - object (`HP:<id>`)
    - negated (`true` for Normal/Negative results)
    - primary_knowledge_source (`infores:loinc2hpo`)
    - aggregator_knowledge_source (`["infores:omop2obo"]`)
    - knowledge_level / agent_type (from OMOP2OBO `MAPPING_CATEGORY`)

### Hierarchy (is_a) edges — 24,310

The CompLOINC subsumption tree: leaf code → LOINC Part → … → root grouper.

**Biolink Captured:**

- `biolink:Association`
    - id (random uuid)
    - subject (`LOINC:<code>` / `LOINC:LP…` / `LOINC:CC-…`)
    - predicate (`biolink:subclass_of` — the is_a predicate; *not* provisional)
    - object (parent `LOINC:LP…` / `LOINC:CC-…`)
    - primary_knowledge_source (`infores:comploinc`)
    - aggregator_knowledge_source (`["infores:monarchinitiative"]`)
    - knowledge_level (`knowledge_assertion`) / agent_type (`automated_agent` — CompLOINC computes it)

## Concepts: leaf codes vs LP Parts vs CC groupers

Three kinds of concept appear as nodes, and the distinction drives the modeling:

- **Leaf codes** (`2345-7`) — fully-specified observations, the complete "sentence": a unique
  combination of LOINC's six axes (component · property · time · system · scale · method). These are
  what a lab result is coded with. The ~104k data layer.
- **LP Parts** (`LP14536-4` = "Glucose") — the reusable atomic axis values, the "words" sentences are
  built from (the component *Glucose*, the system *Serum or Plasma*…). In the hierarchy they also
  serve as the grouping levels leaves roll up through.
- **CC groupers** (`CC-LP31392-1` = "Enzymes Component Class") — grouping classes **CompLOINC computes**
  that don't exist in stock LOINC; they impose clean ontological categories ("all enzyme assays").

So leaves are the data; LP Parts and CC groupers are the **scaffolding above them** that makes the data
aggregatable ("show me every enzyme test"). Leaves come from the LOINC table; the scaffolding exists
only in CompLOINC, so the ingest emits those 3,119 backbone nodes.

## Modeling — settled vs. provisional

Node and edge **shapes** are settled; several **semantic** choices are deliberately left provisional
for a later modeling pass:

- **Node category `ClinicalMeasurement`** — biolink anchors this class to LOINC, but it is an
  `attribute`, so its `has_attribute_type` slot is required; for a terminology *concept* node the
  LOINC code is self-referenced. Open questions: is `ClinicalMeasurement` right for terminology-as-nodes
  (vs. a specific patient measurement)? And is it right for the LP/CC **grouping** nodes, which are
  categories rather than measurements?
- **Compositional predicate `biolink:related_to`** — *provisional placeholder.* The intended grounding
  is `RO:0009006` *assay measures characteristic* (outcome-independent); biolink has no exact predicate
  yet. The object's category already distinguishes analyte (ChEBI/PR) vs. specimen (UBERON/CL) vs.
  organism (NCBITaxon).
- **Phenotype predicate `biolink:correlated_with` + `negated`** — *provisional.* There is no biolink
  predicate for "abnormal-measurement-result indicates phenotype"; a purpose-built one (grounded near
  the `RO:0020329`–`RO:0020334` "indicates …" family) should be proposed. The result interpretation is
  preserved in the prep TSV for a future qualifier model.
- **`biolink:subclass_of` (is_a)** — *settled.* This genuinely is the is_a predicate.
- **Provenance** — `knowledge_level` / `agent_type` are derived per edge: OMOP2OBO's manually-curated
  mappings → `knowledge_assertion` / `manual_agent`; its automatic/similarity tiers and the computed
  CompLOINC hierarchy → `prediction` / `automated_agent`.

## Versioning — three LOINC vintages, surfaced in metadata

The three sources were built against different LOINC releases, so the graph carries **three vintages**,
each recorded as a source in `output/release-metadata.yaml` (the CompLOINC entry carries a free-text
`notes` field spelling out the skew):

| source | version | built on LOINC |
|---|---|---|
| LOINC node table | `2.80` (via Tuva terminology `0.16.0`) | 2.80 |
| OMOP2OBO | `V1.1` | 2.64 / Sept-2020 ontologies |
| CompLOINC | `v2022-12-05` | ~2.73 |

The node table is pinned by the Tuva terminology release (`TUVA_TERMINOLOGY_VERSION`, default `0.16.0`);
the actual LOINC version is derived from the table itself (`max(version_last_changed)`).

**The visible consequence — partial coverage:**

- OBO + phenotype edges attach to the ~3,900 LOINC codes OMOP2OBO covers.
- The is_a hierarchy covers only **~10% of leaf codes** (10,547): CompLOINC's 2022 release placed the
  full LP-Part backbone but wired up only a fraction of leaves.

Both gaps close by refreshing the upstreams against current LOINC (for the hierarchy, by building
CompLOINC HEAD from a current LOINC release).

## Not yet in scope (later passes)

- Attaching the remaining ~90% of leaf codes to the hierarchy (current CompLOINC build).
- LOINC's own structure beyond CompLOINC: LOINC→Gene, COMPONENT/SYSTEM-derived edges for codes OMOP2OBO doesn't cover.
- LOINC→SNOMED / RadLex Part mappings (license-encumbered).
- Refreshing OMOP2OBO past its LOINC 2.64 / 2020 ontology snapshot.

## Citation

- **LOINC:** Regenstrief Institute, Inc. LOINC (Logical Observation Identifiers Names and Codes). https://loinc.org/
- **OMOP2OBO:** Callahan TJ, et al. *Ontologizing health systems data at scale: making translational discovery a reality.* npj Digital Medicine, 2023. [PMC10196319](https://pmc.ncbi.nlm.nih.gov/articles/PMC10196319/)
- **loinc2hpo (phenotype lineage):** Zhang S, et al. *Semantic integration of clinical laboratory tests from electronic health records for deep phenotyping and biomarker discovery.* npj Digital Medicine, 2019. [PMC6499863](https://pmc.ncbi.nlm.nih.gov/articles/PMC6499863/)
- **CompLOINC:** Computational LOINC in OWL. https://github.com/loinc/comp-loinc

## License

MIT
