"""Service-layer exceptions.

Kept in a separate module so low-level helpers can raise them without
importing the package initializer (and its service imports) in a circle.
"""


class APIError(Exception):
    """Base class for API-related errors."""


class AuthenticationError(APIError):
    """Raised when API authentication or account-level billing fails.

    These errors must stop the whole job: retrying cannot fix an invalid key
    or an empty account balance.
    """


class ArticleGenerationError(Exception):
    """Raised when article generation fails after all retries."""


class PostGenerationError(Exception):
    """Raised when a post-generation step fails after all retries."""


class SlidePlanError(PostGenerationError):
    """Raised when a slide plan is structurally invalid."""


class TextOverflowError(PostGenerationError):
    """Raised when text does not fit its fixed-size box.

    The renderer never shrinks fonts or truncates text. Callers repair the
    slide plan or fall back to the deterministic paginator.
    """

    def __init__(
        self,
        *,
        role: str,
        text: str,
        max_width: int,
        max_height: int,
    ) -> None:
        self.role = role
        self.text = text
        self.max_width = max_width
        self.max_height = max_height
        super().__init__(
            f"{role} does not fit at the fixed font size "
            f"(text={text!r}, max_width={max_width}px, max_height={max_height}px)"
        )
