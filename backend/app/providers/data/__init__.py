"""Ad collection: the `AdDataProvider` seam, its errors, and the mock.

`base` is the protocol, `models` is its data vocabulary, `errors` is how a
provider says it failed, `provenance` is the shared trust vocabulary, and
`mock` is a working provider that needs no network.

A real provider module (`official_api`, `public_ui`, `apify`, `manual_import`)
belongs beside `mock` and is added in a later checkpoint. Adding one must
require no change outside this package and `app.composition`.
"""
