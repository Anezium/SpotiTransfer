"""
SpotiTransfer - Flask Application
Web dashboard for transferring Spotify liked songs between accounts
"""
import os
import json
import secrets
from flask import Flask, render_template, redirect, request, session, url_for, Response, stream_with_context
from dotenv import load_dotenv

load_dotenv()

from auth import (
    get_auth_url, 
    get_token_from_code, 
    get_spotify_client, 
    get_user_info,
    is_configured
)
from spotify_service import get_all_saved_tracks, transfer_tracks

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(32))


@app.route('/')
def index():
    """Home page - show setup guide if not configured, otherwise show connect button."""
    configured = is_configured()
    source_user = session.get('source_user')
    dest_user = session.get('dest_user')
    tracks = session.get('tracks', [])
    
    return render_template('index.html', 
                         configured=configured,
                         source_user=source_user,
                         dest_user=dest_user,
                         tracks_count=len(tracks))


@app.route('/setup')
def setup():
    """Show Spotify app setup guide."""
    return render_template('setup.html')


@app.route('/save-credentials', methods=['POST'])
def save_credentials():
    """Save Spotify credentials to .env file."""
    client_id = request.form.get('client_id', '').strip()
    client_secret = request.form.get('client_secret', '').strip()
    
    if not client_id or not client_secret:
        return redirect(url_for('setup'))
    
    # Write to .env file
    env_content = f"""SPOTIPY_CLIENT_ID={client_id}
SPOTIPY_CLIENT_SECRET={client_secret}
SPOTIPY_REDIRECT_URI=http://127.0.0.1:5000/callback
FLASK_SECRET_KEY={secrets.token_hex(32)}
"""
    with open('.env', 'w') as f:
        f.write(env_content)
    
    # Reload environment
    load_dotenv(override=True)
    
    return redirect(url_for('index'))


@app.route('/login/<account_type>')
def login(account_type):
    """Initiate OAuth flow for source or destination account."""
    if account_type not in ['source', 'dest']:
        return redirect(url_for('index'))
    
    # Generate state for security
    state = f"{account_type}:{secrets.token_hex(16)}"
    session['oauth_state'] = state
    
    auth_url = get_auth_url(account_type, state)
    return redirect(auth_url)


@app.route('/callback')
def callback():
    """Handle OAuth callback from Spotify."""
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')
    
    if error:
        return render_template('error.html', error=error)
    
    # Validate state
    expected_state = session.get('oauth_state', '')
    if not state or not state.startswith(expected_state.split(':')[0]):
        return render_template('error.html', error='Invalid state parameter')
    
    account_type = state.split(':')[0]
    
    try:
        token_info = get_token_from_code(account_type, code)
        sp_client = get_spotify_client(token_info)
        user_info = get_user_info(sp_client)
        
        # Store in session
        session[f'{account_type}_token'] = token_info
        session[f'{account_type}_user'] = user_info
        
        if account_type == 'source':
            # Clear any previous tracks when connecting new source
            session.pop('tracks', None)
            return redirect(url_for('fetch_tracks'))
        else:
            return redirect(url_for('transfer'))
            
    except Exception as e:
        return render_template('error.html', error=str(e))


@app.route('/fetch')
def fetch_tracks():
    """Page to fetch tracks from source account."""
    source_user = session.get('source_user')
    if not source_user:
        return redirect(url_for('index'))
    
    return render_template('fetch.html', source_user=source_user)


@app.route('/fetch/stream')
def fetch_stream():
    """SSE endpoint for streaming track fetch progress."""
    source_token = session.get('source_token')
    if not source_token:
        return Response('No source token', status=401)
    
    def generate():
        sp_client = get_spotify_client(source_token)
        tracks = []
        
        for update in get_all_saved_tracks(sp_client):
            if update['type'] == 'track':
                tracks.append(update)
            yield f"data: {json.dumps(update)}\n\n"
        
        # Store tracks in a file (session has size limits)
        with open('.tracks_cache.json', 'w', encoding='utf-8') as f:
            json.dump(tracks, f)
        
        yield f"data: {json.dumps({'type': 'complete', 'count': len(tracks)})}\n\n"
    
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )


@app.route('/tracks')
def show_tracks():
    """Show fetched tracks and connect destination button."""
    source_user = session.get('source_user')
    if not source_user:
        return redirect(url_for('index'))
    
    # Load tracks from cache
    try:
        with open('.tracks_cache.json', 'r', encoding='utf-8') as f:
            tracks = json.load(f)
    except FileNotFoundError:
        return redirect(url_for('fetch_tracks'))
    
    return render_template('tracks.html', 
                         source_user=source_user,
                         tracks=tracks,
                         tracks_count=len(tracks))


@app.route('/transfer')
def transfer():
    """Transfer page."""
    source_user = session.get('source_user')
    dest_user = session.get('dest_user')
    
    if not source_user:
        return redirect(url_for('index'))
    if not dest_user:
        return redirect(url_for('show_tracks'))
    
    # Load tracks
    try:
        with open('.tracks_cache.json', 'r', encoding='utf-8') as f:
            tracks = json.load(f)
    except FileNotFoundError:
        return redirect(url_for('fetch_tracks'))
    
    return render_template('transfer.html',
                         source_user=source_user,
                         dest_user=dest_user,
                         tracks_count=len(tracks))


@app.route('/transfer/stream')
def transfer_stream():
    """SSE endpoint for streaming transfer progress."""
    dest_token = session.get('dest_token')
    if not dest_token:
        return Response('No destination token', status=401)
    
    # Load tracks
    try:
        with open('.tracks_cache.json', 'r', encoding='utf-8') as f:
            tracks = json.load(f)
    except FileNotFoundError:
        return Response('No tracks cached', status=400)
    
    def generate():
        sp_client = get_spotify_client(dest_token)
        access_token = dest_token['access_token']
        
        for update in transfer_tracks(sp_client, tracks, access_token, preserve_order=True):
            yield f"data: {json.dumps(update)}\n\n"
    
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )


@app.route('/reset')
def reset():
    """Reset session and start over."""
    session.clear()
    # Clean up cache files
    for f in ['.cache-source', '.cache-dest', '.tracks_cache.json']:
        try:
            os.remove(f)
        except FileNotFoundError:
            pass
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True, port=5000, host='127.0.0.1')
