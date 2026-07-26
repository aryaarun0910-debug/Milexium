"""Program G: Verify and formal knowledge -- v0.1 slice.

Organizationally separate from app/canonical (the generator): this
package only reads canonical contracts and raw storage rows, it never
imports app.canonical.events.HashChainAppender or
app.canonical.storage.SqliteCanonicalStore's write path, per
blueprint 19's "candidate generators and independent verifiers must remain
separate."

v0.1 covers three of the roadmap's required checks: schema conformance,
state-machine legality, and hash-chain integrity. Numerical, statistical,
security, replay, compiler, and proof verifiers (TLA+/Lean/SMT) are
Specified, not Exists, until a packet actually needs them.
"""

from app.verify.hash_chain_verifier import ChainViolation, verify_chain
from app.verify.schema_verifier import export_schema, verify_against_schema
from app.verify.state_verifier import StateViolation, verify_state_sequence

__all__ = [
    "ChainViolation",
    "verify_chain",
    "export_schema",
    "verify_against_schema",
    "StateViolation",
    "verify_state_sequence",
]

CONTRACT_VERSION = "0.1.0"
