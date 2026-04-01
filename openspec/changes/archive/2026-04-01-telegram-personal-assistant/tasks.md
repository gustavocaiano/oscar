## 1. Foundation and project setup

- [x] 1.1 Create the Python project skeleton, dependency manifest, container files, and environment configuration for the Telegram assistant.
- [x] 1.2 Define modular application boundaries for Telegram handlers, domain services, AI tool layer, scheduling, and integrations.
- [x] 1.3 Define the SQLite schema for tasks, shopping items, reminders, notes, approvals, chat history, and hour-tracking entries.

## 2. Deterministic command-based features

- [x] 2.1 Implement grouped Telegram command namespaces for tasks and shopping operations.
- [x] 2.2 Implement grouped Telegram command namespaces for notes/inbox capture and reminder management.
- [x] 2.3 Implement grouped Telegram command namespaces for calendar and hour-tracking features.

## 3. Core personal-data services

- [x] 3.1 Implement persistent task and shopping services with create/list/update/complete flows.
- [x] 3.2 Implement persistent note/inbox services plus reminder creation and scheduled trigger storage.
- [x] 3.3 Implement briefing data assembly that can combine tasks, shopping items, reminders, notes, and hour-tracking status.

## 4. External integrations

- [x] 4.1 Port or adapt the required `hcounter` parsing, formatting, and monthly aggregation logic into this repository.
- [x] 4.2 Implement iCloud/CalDAV calendar configuration, agenda reads, and basic event creation.
- [x] 4.3 Add integration error handling and user-visible fallback messages for unavailable calendar or hour-tracking operations.

## 5. AI chat and approval workflow

- [x] 5.1 Implement the OpenAI-compatible chat backend adapter and default non-command chat flow.
- [x] 5.2 Implement a read-capable tool layer that exposes assistant data to AI chat mode.
- [x] 5.3 Implement pending-action approval flow so AI-proposed writes require explicit confirmation before execution.

## 6. Proactive assistant behavior

- [x] 6.1 Implement scheduled reminder alerts, hour reminders, morning briefings, and evening wrap-ups.
- [x] 6.2 Add user or config preferences for enabling and disabling proactive message types and schedules.
- [x] 6.3 Ensure proactive briefings can include relevant data from lists, notes, reminders, hours, and calendar agenda.

## 7. Validation and documentation

- [x] 7.1 Add tests for list management, reminders, approval workflow, and briefing assembly.
- [x] 7.2 Add tests that preserve expected `hcounter` behavior and validate calendar integration edge cases.
- [x] 7.3 Document local setup, iCloud/CalDAV configuration, AI backend setup, command reference, and manual end-to-end validation steps.
