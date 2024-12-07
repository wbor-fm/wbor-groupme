"""
Module for base classes for handlers.
"""


class MessageSourceHandler:
    """
    Base class for message source handlers.
    """

    def process_message(self, body):
        """
        Logic to process a message from the source.
        """
        raise NotImplementedError("This method should be implemented by subclasses.")
