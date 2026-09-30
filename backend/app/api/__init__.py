"""HTTP layer: routers and API dependencies.

S0.1 -- empty by design. Routers arrive in S1.1 and S3.2.
Routers stay thin: parse and validate, delegate to `services`, serialise.
No business logic and no direct database access from this layer.
"""
