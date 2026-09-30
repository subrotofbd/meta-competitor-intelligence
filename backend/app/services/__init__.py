"""Business logic and orchestration.

S0.1 -- empty by design. Arrives in S1.2 (collection orchestration) and
S2.3 (status state machine).

This is the only layer that orchestrates providers, persistence, and the job
queue. It depends on the `AdDataProvider` and `AIProvider` Protocols, never on
a concrete provider module. Concrete providers are wired in the composition
root only, so swapping a provider touches exactly one file.
"""
