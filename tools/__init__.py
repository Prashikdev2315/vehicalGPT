"""Tool implementations: typed, read-only tool functions (M2)."""
from tools.base import make_evidence_packet, validate_evidence_packet
from tools.registry import dispatch_tool, register_tool, validate_tool_call
from tools.time_parser import parse_iso_interval, parse_iso_to_epoch_ms, resolve_relative_time

# Register tools
import tools.get_events
import tools.lookup_dtc
import tools.search_logs
import tools.current_state
import tools.respond_direct
import tools.trend
import tools.compare
import tools.largest_change
import tools.timeline_before
import tools.explain_change
