# Pitcher-App - Techno Playlist Finder

## Overview
A FastAPI web application that helps music producers find techno playlists and their curator contact information using the Spotify API and web scraping techniques.

**Current State:** Imported from GitHub and configured for Replit environment (October 2, 2025)

## Recent Changes
- **2025-10-02**: Initial import and Replit setup
  - Installed Python 3.11 and FastAPI dependencies
  - Created .gitignore for Python project
  - Configured workflow for port 5000 deployment
  - Set up environment for development

## Features
- Search Spotify for techno playlists by genre
- Extract curator contact information (emails, social media)
- Filter by minimum follower count
- Export results to HTML format
- API key protection for production use
- Real-time progress updates via Server-Sent Events

## Tech Stack
- **Backend**: FastAPI 0.115.2
- **Server**: Uvicorn 0.30.6 (with standard extras)
- **Python**: 3.11

## Environment Variables Required
- `SPOTIFY_CLIENT_ID`: Spotify API client ID
- `SPOTIFY_CLIENT_SECRET`: Spotify API client secret
- `API_KEY` (optional): Protect API endpoints from unauthorized access
- `MAX_SPOTIFY_PAGES` (optional, default: 3): Maximum pages to search
- `MAX_LINKS_PER_QUERY` (optional, default: 6): Maximum links to scrape per query
- `PER_DOMAIN_COOLDOWN` (optional, default: 0.8): Cooldown between domain requests
- `GLOBAL_COOLDOWN` (optional, default: 0.15): Global request cooldown

## Project Structure
```
.
├── app.py              # Main FastAPI application
├── requirements.txt    # Python dependencies
├── Procfile           # Heroku deployment config (reference)
├── README.md          # Project readme
└── .gitignore         # Git ignore rules
```

## How It Works
1. User selects techno genres and minimum follower count
2. App searches Spotify for matching playlists
3. For each playlist, extracts curator information
4. Searches web for curator contact details
5. Validates and filters contact information
6. Exports results to HTML table

## Development Notes
- FastAPI runs on port 5000 (configured for Replit)
- Uses Server-Sent Events for real-time progress updates
- Implements rate limiting and domain cooldowns for scraping
- Email validation checks against free email providers
- Supports 14 techno genre variations
