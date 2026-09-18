"""One transport per WAY OF REACHING a model.

`cli`         -- an executable, argv from a template, the prompt on stdin
                 (claude, codex, and any CLI-shaped agent)
`openai`      -- an OpenAI-compatible HTTP server: LM Studio and Ollama on
                 this machine, OpenAI, OpenRouter and the rest over the wire;
                 local versus remote is the endpoint and whether a credential
                 is named
`prompt-file` -- not a model: writes the request where a person can carry it,
                 and answers "deferred"

Transports are stateless. Everything comes from the `Spec` they are handed,
so one transport object serves every backend built over it and two backends
cannot leak into each other. The protocol they implement is
`backend.Transport`; they are registered in `backend._TRANSPORTS` by name.
"""
