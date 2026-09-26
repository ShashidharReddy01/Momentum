"""Citations in Mo's answers (S3.3.1): resolved as the reader by ``domain/references.py``
(the same resolution status updates use), so a made-up or private key never becomes a link."""

from momentum.domain.references import CITE, MAX_CITATIONS, Citation, find_refs, resolve

__all__ = ["CITE", "MAX_CITATIONS", "Citation", "find_refs", "resolve"]
