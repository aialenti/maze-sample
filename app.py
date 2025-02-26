import os
import json
from flask import Flask, render_template, redirect, url_for, session, request, jsonify
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import random
from dotenv import load_dotenv

load_dotenv()

# Allow OAuth2 to work with HTTP for localhost development
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SESSION_TYPE'] = 'filesystem'

# OAuth 2.0 configuration
CLIENT_SECRETS_FILE = "client_secrets.json"
SCOPES = ['https://www.googleapis.com/auth/photoslibrary.readonly',
          'https://www.googleapis.com/auth/photoslibrary.appendonly']

# Store viewed photos
VIEWED_PHOTOS_FILE = 'viewed_photos.json'
TARGET_ALBUM_ID = os.getenv('TARGET_ALBUM_ID')

def load_viewed_photos():
    if os.path.exists(VIEWED_PHOTOS_FILE):
        with open(VIEWED_PHOTOS_FILE, 'r') as f:
            return json.load(f)
    return []

def save_viewed_photos(photos):
    with open(VIEWED_PHOTOS_FILE, 'w') as f:
        json.dump(photos, f)

def get_google_photos_service():
    if 'credentials' not in session:
        return None
    
    credentials = Credentials(**session['credentials'])
    
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            session['credentials'] = {
                'token': credentials.token,
                'refresh_token': credentials.refresh_token,
                'token_uri': credentials.token_uri,
                'client_id': credentials.client_id,
                'client_secret': credentials.client_secret,
                'scopes': credentials.scopes
            }
    
    # Use discoveryServiceUrl parameter to specify the API
    return build(
        'photoslibrary',
        'v1',
        credentials=credentials,
        discoveryServiceUrl='https://photoslibrary.googleapis.com/$discovery/rest?version=v1',
        static_discovery=False
    )

@app.route('/')
def index():
    if 'credentials' not in session:
        return redirect(url_for('authorize'))
    return render_template('index.html')

@app.route('/authorize')
def authorize():
    try:
        # Create flow instance
        flow = Flow.from_client_secrets_file(
            CLIENT_SECRETS_FILE,
            scopes=SCOPES,
            redirect_uri=url_for('oauth2callback', _external=True)
        )
        
        # Generate URL for request to Google's OAuth 2.0 server
        redirect_uri = url_for('oauth2callback', _external=True)
        app.logger.info(f"Redirect URI: {redirect_uri}")
        
        authorization_url, state = flow.authorization_url(
            access_type='offline',  # Enable refresh_token
            include_granted_scopes='true',
            prompt='consent'
        )
        app.logger.info(f"Authorization URL: {authorization_url}")
        
        # Store the state in the session
        session['state'] = state
        
        # Redirect to Google's OAuth 2.0 server
        return redirect(authorization_url)
    except Exception as e:
        return f'Authorization setup failed: {str(e)}', 500

@app.route('/oauth2callback')
def oauth2callback():
    try:
        # Debug output
        app.logger.info(f"Callback received. Args: {request.args}")
        
        # Check for error in callback
        if 'error' in request.args:
            return f'Authorization failed: {request.args["error"]}'
        
        # Verify state matches
        state = session.get('state')
        if not state:
            return 'State missing from session', 400
            
        if state != request.args.get('state', ''):
            return 'State mismatch', 400
            
        # Get authorization code
        code = request.args.get('code')
        if not code:
            return 'Authorization code missing from request', 400
            
        # Create flow instance
        flow = Flow.from_client_secrets_file(
            CLIENT_SECRETS_FILE,
            scopes=SCOPES,
            state=state,
            redirect_uri=url_for('oauth2callback', _external=True)
        )
        
        # Exchange authorization code for credentials
        flow.fetch_token(authorization_response=request.url)
        
        # Get credentials
        credentials = flow.credentials
        if not credentials or not credentials.valid:
            return 'Failed to obtain valid credentials', 400
            
        # Store credentials in session
        session['credentials'] = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes
        }
        
        # Redirect back to the main page
        return redirect(url_for('index'))
    except Exception as e:
        app.logger.error(f'OAuth callback error: {str(e)}')
        return f'OAuth callback failed: {str(e)}', 500

import re
from datetime import datetime

def is_samsung_photo(metadata):
    """Check if photo was taken with a Samsung device"""
    if not metadata or 'photo' not in metadata:
        return False
    
    camera_make = metadata['photo'].get('cameraMake', '').lower()
    camera_model = metadata['photo'].get('cameraModel', '').lower()
    
    return 'samsung' in camera_make or 'samsung' in camera_model

def has_valid_filename_pattern(filename):
    """Check if filename matches pattern YYYYMMDD_HHMMSS.jpg"""
    pattern = r'^\d{8}_\d{6}\.jpg$'
    return bool(re.match(pattern, filename))

# Cache for filtered photos
PHOTOS_CACHE = {
    'timestamp': None,
    'photos': [],
    'next_page_token': None
}

# Cache duration in seconds (5 minutes)
CACHE_DURATION = 300

def should_refresh_cache():
    """Check if cache needs to be refreshed"""
    if not PHOTOS_CACHE['timestamp']:
        return True
    
    now = datetime.now().timestamp()
    return (now - PHOTOS_CACHE['timestamp']) > CACHE_DURATION

def get_filtered_photos(service, page_size=50):
    """Get filtered photos using cache and pagination"""
    app.logger.debug("Starting get_filtered_photos")
    
    # If cache is valid and we have photos, return from cache
    if not should_refresh_cache() and PHOTOS_CACHE['photos']:
        app.logger.debug("Returning photos from cache")
        return PHOTOS_CACHE['photos'], PHOTOS_CACHE['next_page_token']
    
    try:
        # Search for photos with basic filter
        request_body = {
            'pageSize': page_size,
            'filters': {
                'mediaTypeFilter': {
                    'mediaTypes': ['PHOTO']
                }
            }
        }
        
        if PHOTOS_CACHE['next_page_token']:
            request_body['pageToken'] = PHOTOS_CACHE['next_page_token']
        
        app.logger.debug(f"Fetching photos with request: {request_body}")
        response = service.mediaItems().search(body=request_body).execute()
        photos = response.get('mediaItems', [])
        app.logger.debug(f"Received {len(photos)} photos from API")
        
        # Filter photos based on criteria
        filtered_photos = []
        for photo in photos:
            try:
                # Get detailed metadata for each photo
                photo_details = service.mediaItems().get(mediaItemId=photo['id']).execute()
                metadata = photo_details.get('mediaMetadata', {})
                
                # Check filename pattern
                if not has_valid_filename_pattern(photo['filename']):
                    app.logger.debug(f"Photo {photo['filename']} doesn't match filename pattern")
                    continue
                
                # Check if it's a Samsung photo
                if not is_samsung_photo(metadata):
                    app.logger.debug(f"Photo {photo['filename']} is not from Samsung")
                    continue
                
                app.logger.debug(f"Adding photo {photo['filename']} to filtered list")
                filtered_photos.append(photo_details)
                
            except Exception as e:
                app.logger.error(f"Error processing photo {photo.get('filename')}: {str(e)}")
                continue
        
        app.logger.debug(f"Filtered down to {len(filtered_photos)} photos")
        
        # Update cache
        PHOTOS_CACHE['photos'] = filtered_photos
        PHOTOS_CACHE['next_page_token'] = response.get('nextPageToken')
        PHOTOS_CACHE['timestamp'] = datetime.now().timestamp()
        
        return filtered_photos, PHOTOS_CACHE['next_page_token']
        
    except Exception as e:
        app.logger.error(f"Error in get_filtered_photos: {str(e)}")
        raise

@app.route('/get_random_photo')
def get_random_photo():
    try:
        service = get_google_photos_service()
        if not service:
            return jsonify({'error': 'Not authenticated. Please log in again.'}), 401
        
        viewed_photos = load_viewed_photos()
        app.logger.debug(f"Loaded {len(viewed_photos)} viewed photos")
        
        # Get filtered photos from cache or API
        filtered_photos, next_page_token = get_filtered_photos(service)
        app.logger.debug(f"Got {len(filtered_photos)} filtered photos")
        
        # Remove viewed photos
        available_photos = [p for p in filtered_photos if p['id'] not in viewed_photos]
        app.logger.debug(f"Have {len(available_photos)} photos after removing viewed ones")
        
        # If no photos available in current batch, try getting next batch
        attempts = 0
        while not available_photos and next_page_token and attempts < 3:
            app.logger.debug(f"Attempt {attempts + 1} to get more photos")
            PHOTOS_CACHE['next_page_token'] = next_page_token
            PHOTOS_CACHE['timestamp'] = None  # Force cache refresh
            filtered_photos, next_page_token = get_filtered_photos(service)
            available_photos = [p for p in filtered_photos if p['id'] not in viewed_photos]
            attempts += 1
        
        if not available_photos:
            total_photos = len(filtered_photos)
            viewed_count = len(viewed_photos)
            message = (f"No more unviewed photos available. "
                      f"Total Samsung photos found: {total_photos}, "
                      f"Already viewed: {viewed_count}")
            app.logger.info(message)
            return jsonify({'error': message}), 404
        
        # Select random photo
        photo = random.choice(available_photos)
        app.logger.debug(f"Selected photo: {photo['filename']}")
        
        # Get the full size image URL
        base_url = photo['baseUrl']
        width = photo['mediaMetadata'].get('width', '1600')
        height = photo['mediaMetadata'].get('height', '1200')
        full_url = f"{base_url}=w{width}-h{height}"
        
        # Get camera info
        metadata = photo.get('mediaMetadata', {})
        camera_make = metadata.get('photo', {}).get('cameraMake', 'Unknown')
        camera_model = metadata.get('photo', {}).get('cameraModel', 'Unknown')
        
        return jsonify({
            'id': photo['id'],
            'url': full_url,
            'filename': photo['filename'],
            'timestamp': metadata.get('creationTime'),
            'camera': {
                'make': camera_make,
                'model': camera_model
            }
        })
        
    except Exception as e:
        app.logger.error(f"Error in get_random_photo: {str(e)}", exc_info=True)
        error_message = f"Error fetching photos: {str(e)}"
        if "Invalid credentials" in str(e):
            error_message = "Your session has expired. Please refresh the page to log in again."
        return jsonify({'error': error_message}), 500

@app.route('/approve_photo/<photo_id>', methods=['POST'])
def approve_photo(photo_id):
    try:
        service = get_google_photos_service()
        if not service:
            return jsonify({'error': 'Not authenticated'}), 401
        
        # Add to viewed photos
        viewed_photos = load_viewed_photos()
        if photo_id not in viewed_photos:
            viewed_photos.append(photo_id)
            save_viewed_photos(viewed_photos)
        
        # Add to target album
        request_body = {
            'albumId': TARGET_ALBUM_ID,
            'mediaItems': [{'mediaItemId': photo_id}]
        }
        app.logger.debug(f"Sending batchCreate request: {request_body}")
        
        response = service.mediaItems().batchCreate(body=request_body).execute()
        app.logger.debug(f"batchCreate response: {response}")
        
        return jsonify({'success': True, 'response': response})
        
    except Exception as e:
        app.logger.error(f"Error in approve_photo: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/skip_photo/<photo_id>', methods=['POST'])
def skip_photo(photo_id):
    # Add to viewed photos
    viewed_photos = load_viewed_photos()
    if photo_id not in viewed_photos:
        viewed_photos.append(photo_id)
        save_viewed_photos(viewed_photos)
    return jsonify({'success': True})

@app.route('/clear')
def clear_session():
    session.clear()
    return 'Session cleared. <a href="/">Go back</a>'

if __name__ == '__main__':
    app.debug = True
    app.run(host='0.0.0.0', port=54016)