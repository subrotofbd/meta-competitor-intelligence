"""Copy analysis: the `AIProvider` seam, its schema, and the mock.

`base` is the protocol, `models` is the analysis contract, and `mock` is a
working provider that returns fixture-driven results without a network call.

No AI SDK is installed. A real adapter (`openai`, `gemini`) is added in S3,
behind the same protocol, and the model name comes from settings rather than
from code.
"""
