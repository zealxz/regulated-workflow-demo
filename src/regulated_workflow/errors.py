class WorkflowError(Exception):
    """Base class for expected, user-actionable workflow failures."""


class InputError(WorkflowError):
    """The supplied input cannot be safely or meaningfully processed."""


class OptionalDependencyError(WorkflowError):
    """An explicitly requested format needs an optional dependency."""


class LLMConfigurationError(WorkflowError):
    """The optional remote adapter is missing safe, explicit configuration."""


class LLMRequestError(WorkflowError):
    """The explicitly enabled remote adapter failed."""
