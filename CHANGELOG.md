# Changelog

## [Unreleased]

### Added
- **Conversation Persistence**: All chat conversations now saved to PostgreSQL database
  - New `conversations` table to track conversation metadata
  - New `messages` table to store individual messages
  - Automatic tracking of message count, locale, and model used
  - Database indexes for optimal query performance

- **Conversation History Support**: All chat endpoints now support conversation history
  - `/api/chat` - Simple chat with history
  - `/api/chat/web` - Web-enabled chat with history
  - `/api/rag/chat` - RAG chat with history
  - Redis cache (1 hour TTL) for fast access
  - PostgreSQL for permanent storage

- **Multi-language Support**: All chat endpoints now support Portuguese and English
  - `locale` parameter accepts `"pt"` or `"en"`
  - Language-specific system prompts
  - Automatic language detection for responses

- **Enhanced MessageRequest Type**: Standardized request structure
  ```typescript
  type MessageRequest = {
    message: string;
    conversation_id: string;
    locale: 'pt' | 'en';
    model?: string;
  }
  ```

- **ConversationDB Service**: New database service for conversation management
  - `upsertConversation()` - Create/update conversations
  - `addMessage()` - Add messages with transaction support
  - `getMessages()` - Retrieve conversation messages
  - `getConversation()` - Get conversation metadata
  - `deleteConversation()` - Delete conversations
  - `deleteOldConversations()` - Cleanup utility

- **New API Endpoints**:
  - `GET /api/chat/history/:conversation_id` - Get conversation history from database
  - `DELETE /api/chat/history/:conversation_id` - Clear conversation (Redis + DB)

- **Documentation**:
  - `docs/CONVERSATIONS_DATABASE.md` - Complete database documentation
  - `examples/test-rag-chat.ts` - RAG chat test examples
  - `examples/chat-api-curl-examples.md` - Updated with RAG examples
  - `scripts/migrate-conversations.sql` - Migration script for existing databases

### Changed
- **Chat Endpoints**: Updated to use new MessageRequest type with required fields
  - `conversation_id` is now required (was optional)
  - `locale` is now required (was not present)
  - `model` remains optional but accepts any string value

- **RAG Chat Endpoint**: Complete overhaul with new features
  - Added conversation history support
  - Added locale-specific system prompts for RAG
  - Integrated Redis caching and database persistence
  - Improved response formatting

- **TTL Configuration**: Redis conversation TTL reduced from 7 days to 1 hour
  - Encourages database as primary storage
  - Reduces Redis memory usage
  - Active conversations still cached for performance

- **History Retrieval**: Now returns database records instead of Redis cache
  - More reliable and complete history
  - Includes conversation metadata
  - Survives Redis TTL expiration

### Removed
- **Task Scheduling Agent**: Removed Google Calendar/Meet scheduling functionality
  - Removed `createTaskAgent()` factory function
  - Removed Google Calendar tools
  - Removed task automation example
  - Updated documentation to remove all references

### Fixed
- TypeScript type errors in chat routes
- Response content extraction from agent messages
- Test file missing embeddings parameter
- Import errors from removed modules

### Database Schema
```sql
-- New tables
CREATE TABLE conversations (
    id SERIAL PRIMARY KEY,
    conversation_id VARCHAR(255) NOT NULL UNIQUE,
    user_id VARCHAR(255),
    locale VARCHAR(10) NOT NULL,
    model VARCHAR(100),
    message_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE messages (
    id SERIAL PRIMARY KEY,
    conversation_id VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
);
```

### Migration Guide

**For new installations:**
```bash
docker-compose up -d
```

**For existing databases:**
```bash
psql $DATABASE_URL -f scripts/migrate-conversations.sql
```

**Updating API calls:**
```diff
  // Old format
  {
    "message": "Hello!",
-   "model": "free"
  }

  // New format
  {
    "message": "Hello!",
+   "conversation_id": "user-123-session-1",
+   "locale": "en",
    "model": "free"
  }
```

### Breaking Changes
⚠️ **All chat endpoints now require `conversation_id` and `locale` parameters**

**Before:**
```bash
curl -X POST http://localhost:3000/api/chat \
  -d '{"message": "Hello!"}'
```

**After:**
```bash
curl -X POST http://localhost:3000/api/chat \
  -d '{
    "message": "Hello!",
    "conversation_id": "user-123",
    "locale": "en"
  }'
```

### Benefits
✅ **Permanent Storage** - Conversations never lost  
✅ **Multi-language** - Portuguese and English support  
✅ **Analytics Ready** - Query conversations by user, date, locale  
✅ **Performance** - Redis cache + Database persistence  
✅ **Scalability** - Indexed queries, efficient storage  
✅ **Type Safety** - Improved TypeScript types  

---

## Previous Versions
See git history for changes before this version.
