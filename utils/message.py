"""
Module for common utility functions for messages.
"""
import uuid
import emoji


class MessageUtils:
    """
    Common utility functions for messages.
    """

    @staticmethod
    def sanitize_string(string, replacement="\uFFFD"):
        """
        Remove or replace unprintable characters from a string.
        Allows for newlines and tabs.

        Parameters:
        - text (str): The input string to sanitize.
        - replacement (str): The character to use for replacement.
            Default is the Unicode replacement character.

        Returns:
        - str: Sanitized text with unprintable characters replaced.
        """
        if not isinstance(string, str):
            return string

        string = string.replace(
            "\xa0", " "
        )  # Replace non-breaking space with regular spaces

        # Replace unprintable characters with the replacement character
        sanitized = []
        for char in string:
            if char.isprintable() or MessageUtils.is_emoji(char) or char in "\n\t":
                sanitized.append(char)
            else:
                sanitized.append(replacement)
        sanitized = "".join(sanitized)
        return sanitized

    @staticmethod
    def is_emoji(char):
        """Check if a character is an emoji."""
        # Emojis are generally in the Unicode ranges:
        # - U+1F600 to U+1F64F (emoticons)
        # - U+1F300 to U+1F5FF (symbols & pictographs)
        # - U+1F680 to U+1F6FF (transport & map symbols)
        # - U+2600 to U+26FF (miscellaneous symbols)
        # - U+2700 to U+27BF (dingbats)
        # - Additional ranges may exist
        return emoji.is_emoji(char)

    @staticmethod
    def gen_uuid():
        """Generate a UUID for a message."""
        return str(uuid.uuid4())
