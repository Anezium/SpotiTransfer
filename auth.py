"""
SpotiTransfer - OAuth Authentication Manager
Handles dual-account authentication for source and destination
"""
import os
from spotipy.oauth2 import SpotifyOAuth
import spotipy


# Scopes needed for each account type
SOURCE_SCOPES = 'user-library-read'
DEST_SCOPES = 'user-library-read user-library-modify'


def get_oauth_manager(account_type: str) -> SpotifyOAuth:
    """
    Create OAuth manager for specific account type.
    Uses different cache paths to maintain separate sessions.
    
    Args:
        account_type: 'source' or 'dest'
    
    Returns:
        SpotifyOAuth instance
    """
    scopes = SOURCE_SCOPES if account_type == 'source' else DEST_SCOPES
    cache_path = f'.cache-{account_type}'
    
    return SpotifyOAuth(
        client_id=os.getenv('SPOTIPY_CLIENT_ID'),
        client_secret=os.getenv('SPOTIPY_CLIENT_SECRET'),
        redirect_uri=os.getenv('SPOTIPY_REDIRECT_URI'),
        scope=scopes,
        cache_path=cache_path,
        show_dialog=True  # Force showing login dialog for account switching
    )


def get_auth_url(account_type: str, state: str) -> str:
    """
    Get authorization URL for OAuth flow.
    
    Args:
        account_type: 'source' or 'dest'
        state: State parameter for security
    
    Returns:
        Authorization URL
    """
    oauth = get_oauth_manager(account_type)
    return oauth.get_authorize_url(state=state)


def get_token_from_code(account_type: str, code: str) -> dict:
    """
    Exchange authorization code for access token.
    
    Args:
        account_type: 'source' or 'dest'
        code: Authorization code from callback
    
    Returns:
        Token info dict
    """
    oauth = get_oauth_manager(account_type)
    return oauth.get_access_token(code, as_dict=True)


def get_spotify_client(token_info: dict) -> spotipy.Spotify:
    """
    Create Spotify client from token info.
    
    Args:
        token_info: Token dict with access_token
    
    Returns:
        Authenticated Spotify client
    """
    return spotipy.Spotify(auth=token_info['access_token'])


def get_user_info(sp_client: spotipy.Spotify) -> dict:
    """
    Get current user's profile info.
    
    Returns:
        Dict with display_name, id, and image
    """
    user = sp_client.current_user()
    return {
        'display_name': user.get('display_name', user['id']),
        'id': user['id'],
        'image': user['images'][0]['url'] if user.get('images') else None
    }


def is_configured() -> bool:
    """Check if Spotify credentials are configured."""
    client_id = os.getenv('SPOTIPY_CLIENT_ID', '')
    client_secret = os.getenv('SPOTIPY_CLIENT_SECRET', '')
    return bool(client_id and client_secret and len(client_id) > 10 and len(client_secret) > 10)
