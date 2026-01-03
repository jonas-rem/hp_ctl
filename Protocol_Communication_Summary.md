# Panasonic Heat Pump Protocol & Timing Findings

## 1. Command Structure (Queries vs. Settings)
The investigation confirms that status queries and settings updates are handled as **standalone transmissions**. They are never merged into a single datagram.

*   **Status Queries (`0x71` header):** These are sent periodically (governed by the `waitTime` setting). All parameter-related bytes in these packets are set to `0x00`. Their sole purpose is to request the current state (203-byte response) from the heat pump.
*   **Settings Commands (`0xf1` header):** When a user changes a setting, HeishaMon constructs a separate 110-byte command. 
    *   It uses the `0xf1` header to signal a write operation.
    *   The heat pump interprets `0x00` values in these commands as "no change," allowing HeishaMon to update single parameters without affecting others.
*   **Flow:** Commands are queued in a buffer and sent sequentially. The heat pump responds to an `0xf1` command with the same 203-byte status update used for `0x71` queries, which HeishaMon uses to confirm the update.

## 2. Command Timing and Latency
The timing between commands is managed by a software semaphore rather than a fixed "sleep" interval.

*   **Sequential Locking:** HeishaMon uses a `sending` flag. Once a command is sent, the system is "locked" until:
    1.  A valid response is received from the heat pump.
    2.  A serial timeout occurs (hardcoded at **2000ms**).
*   **Inter-packet Delay:** There is no enforced delay between the *end* of a response and the *start* of the next queued command. In high-traffic scenarios (e.g., several MQTT commands arriving at once), the next packet can be sent almost immediately after the previous response is processed.
*   **Periodic Minimums:**
    *   **Main Query:** Configurable via `waitTime`, but the interface enforces a minimum of **5 seconds**.
    *   **Optional PCB Query:** If enabled, this is hard-coded to attempt a transmission every **1 second**.
*   **Startup Delay:** There is a mandatory **1.5 second delay** after boot-up before HeishaMon is allowed to send its first datagram.

## 3. Hardware Safety & Recommendations (EEPROM Warning)
While the protocol technically allows for rapid commanding, the following constraints are critical for hardware longevity:

*   **EEPROM Wear:** The heat pump likely stores settings (like DHW targets or operation modes) in non-volatile EEPROM. Excessive writing (e.g., every few seconds) can permanently damage the heat pump's control board. 
*   **Recommended Frequency:** The developers recommend limiting settings changes to **a few per hour** per parameter.
*   **Control Strategy:** For optimization tasks (like chasing a target temperature to prevent cycling), it is safer to adjust setpoints gradually rather than spamming high-frequency updates.
