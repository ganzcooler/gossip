"""Service layer for the Gossip pipeline.

The legacy one-call article, caption, image and Instagram pipeline has been
removed. Protocol fetching and duplicate detection live here; the stateless
post pipeline (tickets 02+) will add its modules and orchestration to this
package.
"""
