"""
SpotiTransfer - Spotify Service
Handles fetching and transferring liked tracks
"""
import time
from typing import Generator
import spotipy
from spotipy.exceptions import SpotifyException


def get_all_saved_tracks(sp_client: spotipy.Spotify) -> Generator[dict, None, None]:
    """
    Generator that yields all saved tracks with pagination.
    Yields progress info and track data.
    
    Yields:
        dict with 'type': 'progress' or 'track'
    """
    offset = 0
    limit = 50
    total = None
    
    while True:
        try:
            results = sp_client.current_user_saved_tracks(limit=limit, offset=offset)
        except SpotifyException as e:
            if e.http_status == 429:
                retry_after = int(e.headers.get('Retry-After', 30))
                yield {'type': 'rate_limit', 'retry_after': retry_after}
                time.sleep(retry_after)
                continue
            raise
        
        if total is None:
            total = results['total']
            yield {'type': 'total', 'total': total}
        
        items = results['items']
        if not items:
            break
        
        for item in items:
            track = item['track']
            if track is None:
                continue
            yield {
                'type': 'track',
                'id': track['id'],
                'name': track['name'],
                'artists': ', '.join(a['name'] for a in track['artists']),
                'album': track['album']['name'],
                'image': track['album']['images'][0]['url'] if track['album']['images'] else None,
                'added_at': item['added_at']
            }
        
        offset += limit
        yield {'type': 'progress', 'fetched': min(offset, total), 'total': total}
        
        # Small delay to respect rate limits
        time.sleep(0.3)


def transfer_tracks(sp_client: spotipy.Spotify, tracks: list, access_token: str, preserve_order: bool = True) -> Generator[dict, None, None]:
    """
    Transfer tracks to destination account.
    Adds tracks ONE BY ONE from oldest to newest to preserve chronological order.
    
    Args:
        sp_client: Authenticated Spotify client for destination
        tracks: List of track dicts with 'id' and 'added_at'
        access_token: Access token for API calls
        preserve_order: If True, add one by one (slower but preserves order)
    
    Yields:
        Progress updates
    """
    import requests
    
    total = len(tracks)
    transferred = 0
    
    if preserve_order:
        # Sort tracks by added_at (oldest first)
        # We add oldest first, so newest ends up on top
        tracks_sorted = sorted(tracks, key=lambda t: t['added_at'])
        
        # Add tracks ONE BY ONE to guarantee order
        for i, track in enumerate(tracks_sorted):
            try:
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                }
                
                # Add single track with its original timestamp
                response = requests.put(
                    "https://api.spotify.com/v1/me/tracks",
                    headers=headers,
                    json={"ids": [track['id']]}
                )
                
                if response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', 30))
                    yield {'type': 'rate_limit', 'retry_after': retry_after}
                    time.sleep(retry_after)
                    # Retry
                    response = requests.put(
                        "https://api.spotify.com/v1/me/tracks",
                        headers=headers,
                        json={"ids": [track['id']]}
                    )
                
                transferred += 1
                
                # Yield progress every 10 tracks to not spam the UI
                if transferred % 10 == 0 or transferred == total:
                    yield {
                        'type': 'progress',
                        'transferred': transferred,
                        'total': total,
                        'percent': int((transferred / total) * 100),
                        'current_track': track['name']
                    }
                
            except Exception as e:
                yield {'type': 'error', 'message': str(e), 'track': track['name']}
            
            # Small delay between each track to let Spotify process in order
            # This is key to preserving the chronological order!
            time.sleep(0.15)
    
    else:
        # Fast mode without order preservation - use batches
        batch_size = 50
        for i in range(0, total, batch_size):
            batch = tracks[i:i + batch_size]
            try:
                track_ids = [t['id'] for t in batch]
                sp_client.current_user_saved_tracks_add(tracks=track_ids)
                transferred += len(batch)
                yield {
                    'type': 'progress',
                    'transferred': transferred,
                    'total': total,
                    'percent': int((transferred / total) * 100)
                }
            except Exception as e:
                yield {'type': 'error', 'message': str(e), 'batch': i}
            time.sleep(0.5)
    
    yield {'type': 'complete', 'transferred': transferred, 'total': total}


