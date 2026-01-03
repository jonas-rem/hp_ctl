# Code Review - Protocol Compliance

## Critical Findings

### 1. Concurrency/Collision Risk

**Issue:** The current implementation violates the "sequential locking" requirement from `Protocol_Communication_Summary.md`.

**Current State:**
- `QueryManager` (src/hp_ctl/query_manager.py:132-161) runs a background thread sending periodic status queries (`0x71`)
- `main.py` (src/hp_ctl/main.py:82-134) sends user setting commands (`0xf1`) immediately upon receiving an MQTT message via `uart_transceiver.send()`
- These two independent processes can attempt to write to the UART bus simultaneously or interrupt a pending response

**Protocol Requirement:**
> "Sequential Locking: HeishaMon uses a `sending` flag. Once a command is sent, the system is 'locked' until:
> 1. A valid response is received from the heat pump.
> 2. A serial timeout occurs (hardcoded at 2000ms)."

**Result:** Protocol violation - multiple independent senders can collide.

### 2. Missing Locking for Settings Commands

**Issue:** User setting commands do not implement the required wait-for-response pattern.

**Current State:**
- `QueryManager` implements waiting logic (`waiting_for_response` flag, timeout handling) for queries only
- User commands in `main.py:126` are "fire-and-forget" - they call `uart_transceiver.send()` directly without waiting for confirmation
- No mechanism prevents sending another command before the heat pump responds to the previous one

**Protocol Requirement:**
> "HeishaMon uses a sending flag. Once a command is sent, the system is 'locked' until a valid response is received or timeout occurs."

**Result:** Settings commands can be sent while waiting for a previous response, violating the locking requirement.

### 3. Inter-packet Delay

**Current State:**
- No enforced delay between commands
- Protocol summary states: "There is no enforced delay between the end of a response and the start of the next queued command"

**Assessment:** This is compliant - no change needed, but commands must still be sequential (one at a time).

## Recommendations

### Refactor to Centralized Command Manager

**Goal:** Ensure all UART transmissions (queries and settings) go through a single synchronized manager.

**Proposed Changes:**

1. **Rename/Refactor `QueryManager` → `CommandManager`:**
   - Add thread-safe queue for outgoing commands
   - Centralize both periodic queries and user setting commands
   - Maintain single `waiting_for_response` flag for all command types
   - Process commands FIFO from queue, respecting timeout/response lock

2. **Update `main.py`:**
   - Replace `uart_transceiver.send(encoded)` (line 126) with `command_manager.queue_command(encoded)`
   - Replace `send_command()` (line 152) with queue-based approach
   - Remove direct UART access from application layer

3. **Command Manager Responsibilities:**
   - Queue management (FIFO or priority-based)
   - Periodic query injection (every 30s)
   - Sequential transmission enforcement
   - Response locking (wait for response or 2s timeout)
   - No startup delay enforcement (per user requirement)

**Benefits:**
- Single point of synchronization
- No concurrent UART writes
- Full protocol compliance with timing requirements
- Prevents command collisions between queries and settings

## Summary

The current implementation has two independent command sources (QueryManager for queries, main.py for settings) that can collide on the UART bus. This violates the protocol's sequential locking requirement. A centralized CommandManager that queues all commands and enforces the wait-for-response pattern is needed for protocol compliance.
