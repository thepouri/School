"""All analyses register themselves when this package is imported.

Import order = display order in the report.
"""

from . import quality  # noqa: F401
from . import price  # noqa: F401
from . import members  # noqa: F401
from . import audience  # noqa: F401
from . import timeline  # noqa: F401
from . import owners  # noqa: F401
from . import content  # noqa: F401

__all__ = [
    "quality",
    "price",
    "members",
    "audience",
    "timeline",
    "owners",
    "content",
]
