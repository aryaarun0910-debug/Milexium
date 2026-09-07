# Research sources

Authoritative and primary sources reviewed for this blueprint on 23 July 2026.
Vendor sources establish public positioning, not independent proof of performance.

## Software-to-silicon dossier

- [Dossier index](../software_to_silicon_markdown_dossier/software_to_silicon_markdown/README.md)
- [Complete 80-technology portfolio](../software_to_silicon_markdown_dossier/software_to_silicon_markdown/03_portfolio_matrix_80_technologies.md)
- [Complete 72-project intelligence-layer radar](../software_to_silicon_markdown_dossier/software_to_silicon_markdown/15_open_source_intelligence_layer_research_radar.md)
- [Structured 72-project catalog](../software_to_silicon_markdown_dossier/software_to_silicon_markdown/intelligence_layer_projects.json)
- [Original reference library](../software_to_silicon_markdown_dossier/software_to_silicon_markdown/14_reference_library_original.md)
- [Intelligence-layer project source index](../software_to_silicon_markdown_dossier/software_to_silicon_markdown/17_intelligence_layer_source_index.md)

## Semantic retrieval and scientific methods

- [TurboVec repository, source, tests, issues, and MIT license](https://github.com/RyanCodrai/turbovec)
- [TurboVec atomic-save and load-validation hardening](https://github.com/RyanCodrai/turbovec/pull/173)
- [TurboVec encoding hardening](https://github.com/RyanCodrai/turbovec/pull/176)
- [TurboVec concurrent-mutation report](https://github.com/RyanCodrai/turbovec/issues/161)
- [TurboVec non-atomic integration persistence report](https://github.com/RyanCodrai/turbovec/issues/159)
- [TurboQuant: Online Vector Quantization with Near-optimal Distortion Rate](https://arxiv.org/abs/2504.19874)
- [pgvector: open-source vector similarity search for PostgreSQL](https://github.com/pgvector/pgvector)
- [TLA+ language and verification tools](https://lamport.org/tla/tla.html)
- [TLC model checker and TLA+ tools](https://lamport.org/tla/tools.html)
- [IEEE Task Force on Process Mining](https://www.tf-pm.org/)
- [A Gentle Introduction to Conformal Prediction and Distribution-Free Uncertainty Quantification](https://arxiv.org/abs/2107.07511)
- [Distributionally Robust Optimization: a review](https://arxiv.org/abs/1908.05659)
- [Bayesian hierarchical models for stochastic mobility flow and waiting times](https://arxiv.org/abs/2007.08962)
- [Digital-twin simulation for a public transportation network](https://doi.org/10.1016/j.ifacol.2025.09.409)

## Transport data standards

- [GTFS Schedule reference](https://gtfs.org/documentation/schedule/reference/)
- [GTFS Flex demand-responsive examples](https://gtfs.org/documentation/schedule/examples/flex/)
- [GTFS Flex project](https://gtfs.org/community/extensions/flex/)
- [TCRP Research Report 210: Transactional Data Specifications for Demand-Responsive Transportation](https://www.nationalacademies.org/publications/25800)
- [Transit Operational Data Standard (TODS)](https://tods-transit.org/)
- [Transit ITS Data Exchange Specification (TIDES)](https://tides-transit.org/gh-pages/)
- [EU Delegated Regulation 2017/1926: NeTEx and SIRI](https://eur-lex.europa.eu/legal-content/EN/ALL/?uri=CELEX%3A32017R1926)

## Regulation and public operational data

- [49 CFR Part 37 and DOT commentary](https://www.transit.dot.gov/regulations-and-guidance/civil-rights-ada/part-37-transportation-services-individuals-disabilities)
- [FTA ADA comprehensive review guide](https://www.transit.dot.gov/sites/fta.dot.gov/files/docs/regulations-and-guidance/safety/triennial-reviews/69491/fy18-comprehensive-review-guide-section-12-americans-disabilities-act-complementary-paratransit.pdf)
- [FTA National Transit Database](https://www.transit.dot.gov/ntd)
- [HHS HIPAA de-identification guidance](https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html)
- [HHS business-associate de-identification FAQ](https://www.hhs.gov/hipaa/for-professionals/faq/544/may-a-health-information-organization-de-identify-information/index.html)
- [City of Chicago TNP public datasets catalog](https://catalog.data.gov/dataset/?organization=city-of-chicago&publisher=data.cityofchicago.org&tags=tnp)

## Direct transport competitors

- [Ecolane](https://www.ecolane.com/)
- [TripSpark NovusDR](https://www.tripspark.com/paratransit-demand-response-software/scheduling-and-dispatching/)
- [Trapeze demand-response product documentation](https://collaborate2.trapezegroup.com/tag/dr/)
- [Spare](https://spare.com/)
- [RideCo scheduling](https://rideco.com/paratransit/scheduling)
- [Uber/Routematch acquisition announcement](https://www.uber.com/en-HN/newsroom/uber-routematch/)
- [Optibus platform](https://optibus.com/product/)
- [Optibus Operations API](https://apidocs.ops.optibus.co/)

## Adjacent optimization and model infrastructure

- [Timefold documentation](https://docs.timefold.ai/)
- [Nextmv documentation](https://www.nextmv.io/docs)
- [MLflow Model Registry](https://www.mlflow.org/docs/latest/ml/model-registry/workflow/)
- [Cordeau: A Branch-and-Cut Algorithm for the Dial-a-Ride Problem](https://pubsonline.informs.org/doi/10.1287/opre.1060.0283)
- [TU Wien optimization problem instances](https://www.ac.tuwien.ac.at/research/problem-instances/)

## Software and governance foundations

- [PostgreSQL row security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
- [CloudEvents specification](https://github.com/cloudevents/spec/blob/main/cloudevents/spec.md)
- [OpenTelemetry](https://opentelemetry.io/docs/)
- [OpenAPI specification](https://spec.openapis.org/oas/latest.html)
- [JSON Schema specification](https://json-schema.org/specification)
- [Semantic Versioning](https://semver.org/)
- [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework)
- [NIST AI RMF Core](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)
- [NIST Secure Software Development Framework 1.1](https://www.nist.gov/publications/secure-software-development-framework-ssdf-version-11-recommendations-mitigating-risk)
- [OSI-approved licenses](https://opensource.org/licenses)
- [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0.html)

## Source-use rules

- Prefer specifications, regulators, government datasets, vendor documentation,
  and original research over summaries.
- Record access date and version for material used in implementation.
- Do not infer absence of a competitor capability from absence on a public page.
- Do not rely on a regulation summary when the governing text or official guide is
  available.
- Re-check standards and product documentation before implementing an adapter,
  publishing a comparison, or making a compliance claim.
