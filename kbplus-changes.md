# KB+ changes needed for Oscar integration

This file describes the KB+ work required so Oscar can use KB+ as the **task source of truth** when KB+ integration is enabled.

## Goal

Allow Oscar to read, create, rename, and complete KB+ tasks through a dedicated external-integration API authenticated by per-user API tokens.

When KB+ is enabled in Oscar:

- Oscar task reads should come from KB+, not from Oscar's local task table
- `/task list` should show non-done KB+ columns grouped by column name
- Oscar should treat the configured done column as completed and all other columns as open/in-progress

## Why a separate integration API

Do **not** reuse the current session-authenticated browser routes under `/api/boards/...`.

Oscar needs:

- bearer-token authentication
- server-to-server usage
- revocation and auditing
- clear separation from browser/session auth

## Required data model additions

Add a personal access token model, for example:

```prisma
model PersonalAccessToken {
  id           String   @id @default(cuid())
  userId       String
  name         String
  tokenPrefix  String
  tokenHash    String
  scopes       String[]
  expiresAt    DateTime?
  lastUsedAt   DateTime?
  revokedAt    DateTime?
  createdAt    DateTime @default(now())
  updatedAt    DateTime @updatedAt

  user User @relation(fields: [userId], references: [id], onDelete: Cascade)

  @@index([userId])
  @@index([tokenPrefix])
}
```

Implementation rules:

- show the plaintext token **once** at creation time
- store only a hash
- allow revocation
- track last-used timestamp

## Required UI changes

KB+ currently has no settings page.

Recommended additions:

1. add a Settings entry from `app/src/components/boards/boards-index-client.tsx`
2. create a user settings page, e.g. `app/src/app/settings/page.tsx`
3. allow:
   - create token
   - view token metadata (name, scopes, created at, last used, revoked state)
   - revoke token

Suggested copy in the UI:

- "External integrations"
- "Generate API token"
- "This token is shown only once"

## Required auth/middleware changes

Add a token-auth middleware/helper separate from `requireSessionUser()`.

Recommended behavior:

- read `Authorization: Bearer <token>`
- resolve token by prefix/hash
- reject revoked or expired tokens
- attach the owning user to the request context

Authorization rules should still enforce that the token owner can access the target board.

## Required API namespace

Add dedicated integration routes, for example:

- `GET /api/integrations/v1/boards/:boardId/tasks`
- `POST /api/integrations/v1/boards/:boardId/tasks`
- `PATCH /api/integrations/v1/boards/:boardId/tasks/:taskId`
- `POST /api/integrations/v1/boards/:boardId/tasks/:taskId/complete`

These are the endpoints Oscar now expects.

## Endpoint contracts Oscar expects

### 1. List columns and tasks

`GET /api/integrations/v1/boards/:boardId/tasks`

Success response Oscar now expects:

```json
{
  "board": {
    "id": "board_1",
    "name": "Personal"
  },
  "columns": [
    {
      "id": "col_todo",
      "name": "Todo",
      "isDone": false,
      "tasks": [
        {
          "id": "task_123",
          "title": "Ship roadmap",
          "description": "",
          "position": 1000,
          "createdAt": "2026-04-02T10:00:00.000Z",
          "updatedAt": "2026-04-02T10:00:00.000Z"
        }
      ]
    },
    {
      "id": "col_doing",
      "name": "Doing",
      "isDone": false,
      "tasks": []
    },
    {
      "id": "col_done",
      "name": "Done",
      "isDone": true,
      "tasks": []
    }
  ]
}
```

Important behavior:

- return columns in board order
- return tasks nested under each column
- include `isDone` if possible; Oscar will also use the configured `KBPLUS_DONE_COLUMN_ID` as a fallback

### 2. Create task

`POST /api/integrations/v1/boards/:boardId/tasks`

Request body:

```json
{
  "columnId": "col_todo",
  "title": "Ship roadmap",
  "description": ""
}
```

Success response:

```json
{
  "task": {
    "id": "task_123",
    "boardId": "board_1",
    "columnId": "col_todo",
    "title": "Ship roadmap"
  }
}
```

Minimum Oscar dependency:

- response must include `task.id`

### 3. Rename/update task

`PATCH /api/integrations/v1/boards/:boardId/tasks/:taskId`

Request body Oscar currently sends:

```json
{
  "title": "Ship roadmap v2"
}
```

It is fine if the endpoint also supports other fields.

### 4. Complete task

`POST /api/integrations/v1/boards/:boardId/tasks/:taskId/complete`

Request body:

```json
{
  "columnId": "col_done"
}
```

Server behavior:

- move the task into the requested done column
- choose the next available position in that column

Suggested success response:

```json
{
  "task": {
    "id": "task_123",
    "columnId": "col_done"
  }
}
```

## Scope model

Recommended initial token scopes:

- `boards:read`
- `tasks:read`
- `tasks:write`

Oscar currently needs both `tasks:read` and `tasks:write`.

## Reuse from current code

The current `board-service.ts` already has good internal primitives for:

- `createTask(...)`
- `updateTask(...)`
- authorization checks

Recommended implementation path:

1. keep those domain functions as the core business logic
2. add token-auth integration routes that call the same service layer
3. add a new board read/list helper for the grouped column/task endpoint
4. add a new complete/move helper if needed for the done-column endpoint

## Additional recommended route

Optional but useful soon:

- `GET /api/integrations/v1/boards`

This would let Oscar later validate available boards/columns instead of relying entirely on env vars.

## Validation checklist in KB+

- creating a token shows plaintext only once
- revoked tokens stop working immediately
- expired tokens are rejected
- integration routes reject users without board access
- list route returns columns in board order with nested tasks
- create task returns `task.id`
- complete task moves the task into the provided done column
- integration routes do not require a browser session

## Notes about Oscar's current implementation

Oscar now uses these env vars when KB+ is enabled:

- `KBPLUS_BASE_URL`
- `KBPLUS_API_TOKEN`
- `KBPLUS_BOARD_ID`
- `KBPLUS_TODO_COLUMN_ID`
- `KBPLUS_DONE_COLUMN_ID`
- `KBPLUS_TIMEOUT_SECONDS`

Oscar currently:

- treats KB+ as the source of truth for tasks when all KB+ env vars are set
- reads task columns/tasks from `GET /api/integrations/v1/boards/:boardId/tasks`
- creates new tasks in `KBPLUS_TODO_COLUMN_ID`
- marks tasks done by moving them to `KBPLUS_DONE_COLUMN_ID`
- groups `/task list` output by KB+ column name

Oscar still keeps local storage for shopping items, reminders, notes, hours, and chat history. The source-of-truth change applies to tasks only.
