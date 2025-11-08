from dataclasses import dataclass


@dataclass
class Message:
    """Represents a decoded message"""
    len:  int
    checksum: bytes
    quiet_mode: int = 0
