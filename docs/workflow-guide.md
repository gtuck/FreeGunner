# Daily Article Researcher Workflow

This workflow automatically fetches, processes, and researches articles from RSS feeds, generating markdown files with extracted content and related research.

## Features

- **Automated RSS Processing**: Fetches latest articles from configured RSS feeds
- **Content Extraction**: Intelligently extracts article content from web pages
- **Research Integration**: Uses Google Custom Search to find related articles
- **Markdown Generation**: Creates well-formatted markdown files with metadata
- **History Tracking**: Prevents duplicate processing of articles
- **Error Handling**: Robust error handling with retry mechanisms
- **Logging**: Comprehensive logging for debugging and monitoring

## Configuration

### Environment Variables

The workflow can be configured using environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `FEEDS_FILE` | `feeds.json` | Path to RSS feeds configuration file |
| `HISTORY_FILE` | `history.json` | Path to processed articles history |
| `OUTPUT_DIR` | `articles` | Directory for generated articles |
| `RESULTS_PER_QUERY` | `10` | Number of research results per article |
| `USER_AGENT` | Chrome UA | HTTP User Agent string |
| `DEFAULT_RSS` | Firearms News RSS | Default RSS feed URL |

### Required Secrets

For Google Custom Search functionality, add these secrets to your repository:

- `GCS_API_KEY`: Google Custom Search API key
- `GCS_CX`: Google Custom Search engine ID

## File Structure

```
├── .github/workflows/
│   └── get-articles-daily.yml    # Main workflow file
├── scripts/
│   └── fetch_articles.py         # Python script for article processing
├── articles/                     # Generated article files
├── feeds.json                    # RSS feeds configuration
├── history.json                  # Processed articles history
├── requirements.txt              # Python dependencies
└── README.md                     # This documentation
```

## Workflow Improvements

The following improvements have been made to the original workflow:

### 1. **Security & Maintainability**
- ✅ Extracted Python script to separate file (`scripts/fetch_articles.py`)
- ✅ Added proper dependency management with `requirements.txt`
- ✅ Improved error handling and logging
- ✅ Added type hints and documentation

### 2. **Performance & Reliability**
- ✅ Added Python package caching with `actions/setup-python@v5`
- ✅ Implemented retry mechanisms for network requests
- ✅ Added timeout configurations to prevent hanging
- ✅ Better resource management with proper session handling

### 3. **Monitoring & Debugging**
- ✅ Enhanced logging with structured log messages
- ✅ Added log file artifacts for debugging
- ✅ Improved error messages and notifications
- ✅ Added configuration validation step

### 4. **User Experience**
- ✅ Added workflow inputs for manual runs:
  - `force_refresh`: Ignore history and process all articles
  - `debug_mode`: Enable verbose logging
- ✅ Better commit messages with timestamps
- ✅ Automatic issue creation on scheduled run failures

### 5. **Configuration Flexibility**
- ✅ Increased `RESULTS_PER_QUERY` from 8 to 10 for more research results
- ✅ Added proper timeout handling (30 minutes max)
- ✅ Better permission management
- ✅ Support for both JSON and CSV configuration files

## Usage

### Manual Trigger

You can manually trigger the workflow from the GitHub Actions tab with optional parameters:

1. Go to Actions → Daily Article Researcher
2. Click "Run workflow"
3. Optionally enable:
   - **Force refresh**: Process all feeds regardless of history
   - **Debug mode**: Enable detailed logging

### Scheduled Runs

The workflow runs automatically every day at 5:00 AM UTC.

### Adding RSS Feeds

Edit the `feeds.json` file to add or modify RSS feeds:

```json
[
  {
    "FeedURL": "https://example.com/rss.xml",
    "Active": true
  },
  {
    "FeedURL": "https://another-site.com/feed.xml",
    "Active": false
  }
]
```

## Troubleshooting

### Common Issues

1. **Rate Limiting**: If you encounter rate limiting issues:
   - Reduce `RESULTS_PER_QUERY` value
   - Check API quotas for Google Custom Search
   - Review workflow run frequency

2. **Missing Articles**: If articles aren't being processed:
   - Check RSS feed validity
   - Verify network connectivity
   - Review logs for parsing errors

3. **Search Results**: If research results are missing:
   - Verify `GCS_API_KEY` and `GCS_CX` secrets
   - Check Google Custom Search quota
   - Ensure API key has proper permissions

### Debugging

1. Enable debug mode when running manually
2. Check workflow logs and artifacts
3. Review the generated log files
4. Validate RSS feeds manually

### Monitoring

The workflow includes:
- Automatic issue creation on failures
- Log artifacts for debugging
- Comprehensive error reporting
- Step-by-step progress tracking

## Development

To test the script locally:

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export GCS_API_KEY="your-api-key"
export GCS_CX="your-search-engine-id"

# Run the script
python scripts/fetch_articles.py
```

## Contributing

When modifying the workflow:

1. Test changes locally first
2. Update documentation if needed
3. Consider backward compatibility
4. Add appropriate error handling
5. Update version comments in files