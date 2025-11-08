from dataclasses import dataclass


@dataclass
class Message:
    """Represents a decoded UART message"""
    header: bytes
    data: bytes
    checksum: bytes
