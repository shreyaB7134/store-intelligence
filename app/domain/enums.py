"""
Domain enumerations for the Store Intelligence Platform.
"""
from enum import Enum


class EventType(str, Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    ZONE_ENTER = "ZONE_ENTER"
    ZONE_EXIT = "ZONE_EXIT"
    ZONE_DWELL = "ZONE_DWELL"
    BILLING_QUEUE_JOIN = "BILLING_QUEUE_JOIN"
    BILLING_QUEUE_ABANDON = "BILLING_QUEUE_ABANDON"
    REENTRY = "REENTRY"


class Severity(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    CRITICAL = "CRITICAL"


class ZoneType(str, Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    SHELF = "SHELF"
    DISPLAY = "DISPLAY"
    BILLING = "BILLING"
    AISLE = "AISLE"
    OTHER = "OTHER"


class AnomalyType(str, Enum):
    QUEUE_SPIKE = "QUEUE_SPIKE"
    DEAD_ZONE = "DEAD_ZONE"
    CONVERSION_DROP = "CONVERSION_DROP"
