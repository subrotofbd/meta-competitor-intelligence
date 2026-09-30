"""Provider families and the protocols they must satisfy.

Two independent seams live here:

* `providers.data` -- ad collection. `AdDataProvider` is the only way the
  business layer may obtain ad data, from any source.
* `providers.ai`   -- copy analysis. `AIProvider` is the only way the business
  layer may reach a model.

A concrete provider imports its protocol, satisfies it, and returns data. It
imports nothing else from the application -- no database, no filesystem, no
orchestration. Business code receives an `AdDataProvider` *instance* and never
names a concrete class, so swapping providers is a one-file change in
`app.composition`.

The mocks shipped here are first-class providers, not test scaffolding: they
are registered and built exactly like any real provider would be.
"""
