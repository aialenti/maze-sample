# Photo Organizer

A web application that helps organize photos from Google Photos by showing them one at a time and allowing quick decisions about whether to add them to a specific album.

## Current Status & Goals

### What We Have
- Integration with Google Photos API
- Authentication flow working
- Photo filtering based on specific criteria:
  - Only shows photos taken with Samsung devices
  - Only shows photos with filenames matching pattern: YYYYMMDD_HHMMSS.jpg
- Basic mobile-first UI with approve/skip buttons
- Tracking of viewed photos to avoid showing duplicates
- Basic caching system to improve performance

### What We're Working On
1. Performance Improvements:
   - Currently implementing smarter caching for photo metadata
   - Optimizing API calls to reduce latency
   - Batch processing capabilities

2. Bug Fixes:
   - Fixed the "approve" functionality to correctly add photos to target album
   - Improved error handling and user feedback

3. Next Steps:
   - Add progress indicators
   - Implement undo functionality
   - Add statistics (total photos processed, approved vs skipped)
   - Improve photo loading speed

## Setup

1. Requirements:
   - Python 3.x
   - Google Cloud Project with Photos API enabled
   - OAuth 2.0 credentials

2. Configuration Files:
   - `client_secrets.json` - OAuth credentials from Google Cloud Console
   - `.env` - Contains TARGET_ALBUM_ID for the destination album

3. Running:
   ```bash
   pip install -r requirements.txt
   python app.py
   ```
   Access at http://localhost:54016

## Technical Notes

- Using Flask for the web server
- OAuth2 for Google Photos authentication
- Session-based auth storage
- File-based caching for viewed photos
- Mobile-first responsive design