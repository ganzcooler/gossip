"""Service layer for the Gossip pipeline.

The legacy one-call article, caption, image and Instagram pipeline has been
removed. Protocol fetching and duplicate detection live here, together with
the stateless post-pipeline modules: planning, Summary writing, fact-check and
repair, deterministic slide composition, captions, and orchestration.
"""
