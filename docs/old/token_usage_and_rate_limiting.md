# Token Usage Tracking and Rate Limiting Implementation

## Overview

This document describes the comprehensive token usage tracking and rate limiting solution implemented for the Chat webapp interface to resolve OpenAI API rate limiting issues and provide detailed analytics.

## Features Implemented

### 1. Rate Limiting Infrastructure

**Files:**
- [`src/infrastructure_atlas/infrastructure/rate_limiting.py`](../src/infrastructure_atlas/infrastructure/rate_limiting.py)

**Key Components:**
- `RateLimitConfig`: Configurable rate limits and retry settings
- `RateLimiter`: Tracks usage and enforces limits
- `TokenUsageTracker`: Comprehensive token usage analytics
- `with_rate_limiting()`: Decorator for applying rate limiting to functions

**Configuration (via environment variables):**
```bash
OPENAI_REQUESTS_PER_MINUTE=60        # Request rate limit
OPENAI_REQUESTS_PER_HOUR=3000        # Hourly request limit
OPENAI_TOKENS_PER_MINUTE=150000      # Token rate limit
OPENAI_TOKENS_PER_HOUR=1000000       # Hourly token limit
OPENAI_MAX_RETRIES=5                 # Maximum retry attempts
OPENAI_BASE_DELAY=1.0                # Base delay for exponential backoff
OPENAI_MAX_DELAY=300.0               # Maximum delay (5 minutes)
OPENAI_STABILIZATION_MINUTES=15      # Stabilization period after rate limits
```

### 2. Enhanced OpenAI Client

**Files:**
- [`src/infrastructure_atlas/infrastructure/openai_client.py`](../src/infrastructure_atlas/infrastructure/openai_client.py)

**Features:**
- Exponential backoff retry with jitter
- Automatic cost calculation for different models
- Comprehensive token usage tracking
- Support for both SDK and HTTP fallback
- Streaming with rate limit handling
- User-friendly error messages

### 3. Queue Management System

**Files:**
- [`src/infrastructure_atlas/infrastructure/queues/chat_queue.py`](../src/infrastructure_atlas/infrastructure/queues/chat_queue.py)

**Features:**
- Priority-based request queuing
- Configurable concurrency limits
- Request lifecycle tracking
- Session-based request cancellation
- Performance metrics

### 4. Enhanced Agent Runtime

**Files:**
- [`src/infrastructure_atlas/application/chat_agents/enhanced_runtime.py`](../src/infrastructure_atlas/application/chat_agents/enhanced_runtime.py)

**Features:**
- Integration with rate limiting infrastructure
- Enhanced error handling and retry logic
- Comprehensive performance metrics
- Cost tracking per request
- Queue integration for OpenAI providers

### 5. Monitoring API Endpoints

**Files:**
- [`src/infrastructure_atlas/interfaces/api/routes/monitoring.py`](../src/infrastructure_atlas/interfaces/api/routes/monitoring.py)

**Endpoints:**
- `GET /monitoring/token-usage` - Token usage statistics
- `GET /monitoring/session-usage/{session_id}` - Per-session usage
- `GET /monitoring/queue-status` - Current queue status
- `GET /monitoring/rate-limits` - Rate limiting status
- `GET /monitoring/performance` - Comprehensive performance metrics
- `GET /monitoring/cost-breakdown` - Detailed cost analysis
- `POST /monitoring/reset-rate-limits` - Admin function to reset limits

### 6. Frontend Enhancements

**Files:**
- [`src/infrastructure_atlas/api/static/app.js`](../src/infrastructure_atlas/api/static/app.js)
- [`src/infrastructure_atlas/api/static/styles.css`](../src/infrastructure_atlas/api/static/styles.css)
- [`src/infrastructure_atlas/api/static/index.html`](../src/infrastructure_atlas/api/static/index.html)

**Features:**
- Real-time token usage display in chat messages
- Performance metrics (efficiency, retries, queue time)
- Monitoring dashboard with toggle
- Enhanced error messages for rate limiting
- Queue status indicators
- Cost tracking display

## How It Works

### Rate Limiting Flow

1. **Request Initiation**: When a chat request is made, the system checks current usage against configured limits
2. **Queue Management**: Requests are queued based on priority and current capacity
3. **Rate Limit Checking**: Before execution, the system verifies rate limits haven't been exceeded
4. **Exponential Backoff**: If rate limits are hit, requests are retried with exponential backoff
5. **Stabilization Period**: After rate limit errors, the system enters a 15-minute stabilization period
6. **Token Tracking**: All successful requests have their token usage and cost recorded

### Error Handling

The system handles several types of errors:

- **429 Rate Limit Exceeded**: Triggers exponential backoff and stabilization period
- **503 Service Unavailable**: Retries with backoff
- **500/502/504 Server Errors**: Retries with backoff
- **Network Errors**: Retries with backoff

### User Experience

- **Queue Status**: Users see their position in queue when requests are delayed
- **Rate Limit Feedback**: Clear messages when rate limits are active
- **Processing Status**: Real-time updates during request processing
- **Token Metrics**: Detailed usage and cost information per message
- **Performance Metrics**: Efficiency, retry count, and timing information

## Testing the Solution

### 1. Infrastructure Test

```bash
# Test the core infrastructure components
uv run python -c "
import asyncio
from src.infrastructure_atlas.infrastructure.rate_limiting import get_rate_limiter, get_token_tracker
from src.infrastructure_atlas.infrastructure.queues.chat_queue import get_chat_queue

async def test():
    rate_limiter = get_rate_limiter()
    token_tracker = get_token_tracker()
    queue = await get_chat_queue()
    
    print('✅ All components initialized successfully')
    await queue.stop()

asyncio.run(test())
"
```

### 2. API Server Test

```bash
# Start the API server
uv run atlas api serve --host 0.0.0.0 --port 8443
```

### 3. Monitoring Endpoints Test

```bash
# Test monitoring endpoints (requires authentication)
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:8443/monitoring/token-usage
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:8443/monitoring/queue-status
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:8443/monitoring/rate-limits
```

### 4. Frontend Test

1. Open `http://localhost:8443/app/` in your browser
2. Navigate to the Chat page
3. Enable "Show monitoring" checkbox
4. Send a chat message to test rate limiting and token tracking
5. Observe the token usage metrics and performance data

## Configuration Recommendations

### Production Settings

```bash
# Conservative rate limits for production
OPENAI_REQUESTS_PER_MINUTE=30
OPENAI_REQUESTS_PER_HOUR=1500
OPENAI_TOKENS_PER_MINUTE=75000
OPENAI_TOKENS_PER_HOUR=500000

# Aggressive retry settings
OPENAI_MAX_RETRIES=8
OPENAI_BASE_DELAY=2.0
OPENAI_MAX_DELAY=600.0
OPENAI_STABILIZATION_MINUTES=20
```

### Development Settings

```bash
# More permissive for development
OPENAI_REQUESTS_PER_MINUTE=100
OPENAI_REQUESTS_PER_HOUR=5000
OPENAI_TOKENS_PER_MINUTE=200000
OPENAI_TOKENS_PER_HOUR=1500000

# Faster retries for development
OPENAI_MAX_RETRIES=3
OPENAI_BASE_DELAY=0.5
OPENAI_MAX_DELAY=60.0
OPENAI_STABILIZATION_MINUTES=5
```

## Monitoring and Analytics

### Token Usage Metrics

- **Total tokens consumed** (prompt + completion)
- **Cost tracking** with model-specific pricing
- **Request efficiency** (characters per token)
- **Session-based usage** tracking
- **Time-based analytics** (hourly, daily trends)

### Performance Metrics

- **Queue wait times** and processing duration
- **Retry counts** and success rates
- **Rate limit utilization** percentages
- **Error rates** and types
- **Stabilization period** tracking

### Cost Analysis

- **Per-request cost** calculation
- **Model-specific pricing** (GPT-4, GPT-4o, etc.)
- **Session cost** tracking
- **Daily/weekly cost** trends
- **Cost efficiency** metrics

## Troubleshooting

### Common Issues

1. **High Rate Limit Utilization**
   - Reduce `OPENAI_REQUESTS_PER_MINUTE`
   - Increase `OPENAI_STABILIZATION_MINUTES`
   - Monitor queue size and processing times

2. **Frequent 503 Errors**
   - Increase `OPENAI_MAX_DELAY`
   - Reduce concurrent request limits
   - Check OpenAI service status

3. **High Costs**
   - Monitor token efficiency metrics
   - Use smaller models for simple queries
   - Implement request filtering

### Monitoring Dashboard

The monitoring dashboard provides real-time visibility into:

- **Current rate limit status** (healthy/warning/error)
- **Token usage trends** and cost tracking
- **Queue performance** and wait times
- **Error rates** and retry statistics
- **Performance scores** and optimization suggestions

## Integration Points

### Backend Integration

The enhanced runtime is automatically used for OpenAI providers in:
- [`/chat/complete`](../src/infrastructure_atlas/api/app.py) endpoint
- [`/chat/stream`](../src/infrastructure_atlas/api/app.py) endpoint
- Tool sample execution

### Frontend Integration

The monitoring features are integrated into:
- Chat message display (token usage per message)
- Chat interface (queue status, rate limit warnings)
- Optional monitoring dashboard (toggle-able)
- Enhanced error messages and user feedback

## Benefits

1. **Prevents Rate Limit Errors**: Proactive rate limiting prevents 429 errors
2. **Improves Reliability**: Exponential backoff and stabilization periods ensure stable operation
3. **Cost Visibility**: Real-time cost tracking helps manage expenses
4. **Performance Insights**: Detailed metrics enable optimization
5. **Better UX**: Clear feedback and status updates improve user experience
6. **Scalability**: Queue management handles multiple concurrent users

## Future Enhancements

- **Predictive rate limiting** based on usage patterns
- **Model selection optimization** based on cost/performance
- **Advanced analytics** with trend analysis
- **Alert system** for cost thresholds
- **Load balancing** across multiple API keys