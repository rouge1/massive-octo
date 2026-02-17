"""
Session Database Reader Module

Detects and reads radio session metadata from SQLite databases that accompany
intercepted audio files. When a watch folder contains a session.db + info.json,
this module extracts rich radio protocol metadata (frequency, talkgroup,
encryption status, etc.) to enrich AudioFile records.

Two modes (auto-detected):
- Session mode: watch folder has info.json + session.db -> extract radio metadata
- Normal mode: no session DB -> process WAVs as usual (this module returns None)

Main Functions:
- detect_session_context(): Check if watch folder has a session DB
- parse_radio_filename(): Extract metadata from radio-formatted filenames
- query_session_metadata(): Query SQLite for rich intercept metadata
- get_radio_metadata_for_file(): Combined entry point for all metadata extraction
"""

import json
import logging
import os
import re
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s', datefmt='%Y-%m-%d [%H:%M:%S]')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def detect_session_context(watch_folder):
    """
    Detect if watch_folder (or its parent) contains a radio session database.

    Checks for the presence of both session.db and info.json. If the watch
    folder itself doesn't have them, checks the parent directory (handles case
    where watcher points at intercept_files/ subdirectory).

    Args:
        watch_folder (str or Path): Path to the audio watch folder

    Returns:
        dict or None: Session context with keys:
            - session_dir (str): Path to directory containing session.db
            - session_db_path (str): Full path to session.db
            - info (dict): Parsed contents of info.json
        Returns None if no session DB found or on any error.
    """
    watch_folder = Path(watch_folder)

    # Check watch folder itself, then parent
    candidates = [watch_folder, watch_folder.parent]

    for candidate in candidates:
        session_db = candidate / 'session.db'
        info_json = candidate / 'info.json'

        if session_db.exists() and info_json.exists():
            try:
                with open(info_json, 'r') as f:
                    info = json.load(f)

                # Verify the SQLite DB is readable
                uri = f"file:{session_db}?mode=ro"
                conn = sqlite3.connect(uri, uri=True)
                conn.execute("SELECT 1")
                conn.close()

                logger.info(f"Session DB detected: {session_db}")
                return {
                    'session_dir': str(candidate),
                    'session_db_path': str(session_db),
                    'info': info
                }
            except (json.JSONDecodeError, sqlite3.Error, OSError) as e:
                logger.warning(f"Session DB found but unreadable: {e}")
                return None

    return None


def parse_radio_filename(filename):
    """
    Extract radio metadata encoded in intercepted audio filenames.

    Supports two formats:
    - With slot (DMR): {proto}_voice_{freq}hz_slot{n}_{timestamp}.wav
    - Without slot: {proto}_voice_{freq}hz_{timestamp}.wav

    Args:
        filename (str): The WAV filename (basename, not full path)

    Returns:
        dict: Extracted metadata with keys:
            - radio_protocol (str or None): e.g. 'dmr', 'ctcss', 'dcs', 'nxdn'
            - radio_frequency (float or None): Frequency in Hz
            - radio_slot (int or None): TDMA slot number (DMR only)
            - intercept_timestamp (float or None): Unix epoch seconds
    """
    result = {
        'radio_protocol': None,
        'radio_frequency': None,
        'radio_slot': None,
        'intercept_timestamp': None
    }

    # Pattern with slot: {proto}_voice_{freq}hz_slot{n}_{timestamp}.wav
    match = re.match(
        r'^([a-zA-Z]+)_voice_(\d+)hz_slot(\d+)_(\d+\.\d+)\.wav$',
        filename
    )
    if match:
        result['radio_protocol'] = match.group(1).lower()
        result['radio_frequency'] = float(match.group(2))
        result['radio_slot'] = int(match.group(3))
        result['intercept_timestamp'] = float(match.group(4))
        return result

    # Pattern without slot: {proto}_voice_{freq}hz_{timestamp}.wav
    match = re.match(
        r'^([a-zA-Z]+)_voice_(\d+)hz_(\d+\.\d+)\.wav$',
        filename
    )
    if match:
        result['radio_protocol'] = match.group(1).lower()
        result['radio_frequency'] = float(match.group(2))
        result['intercept_timestamp'] = float(match.group(3))
        return result

    return result


def query_session_metadata(session_db_path, wav_filename):
    """
    Query the session SQLite database for rich metadata about a WAV file.

    Join path: intercept_files -> intercepts -> intercept_attachments -> intercept_rssis

    Args:
        session_db_path (str): Path to session.db
        wav_filename (str): WAV filename to look up (basename)

    Returns:
        dict or None: Metadata with keys:
            - intercept_id (int): Session DB intercept ID
            - radio_frequency (float): Center frequency in Hz
            - radio_bandwidth (float): Channel bandwidth in Hz
            - radio_protocol (str): Protocol from attachment standard/technology
            - radio_rssi (float): Average signal strength in dBm
            - radio_metadata (str): Full JSON from intercept_attachments
            - intercept_timestamp (float): Start time in Unix epoch seconds
        Returns None if file not found in session DB.
    """
    try:
        uri = f"file:{session_db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Find the file in intercept_files - match by filename in path column
        # Path format in DB: "intercept_files/dmr_voice_461487000hz_slot0_1621057773.576242.wav"
        cursor.execute("""
            SELECT if2.intercept_id, if2.path
            FROM intercept_files if2
            WHERE if2.path LIKE ?
        """, (f'%{wav_filename}',))

        file_row = cursor.fetchone()
        if not file_row:
            conn.close()
            return None

        intercept_id = file_row['intercept_id']

        # Get intercept details (frequency, bandwidth, timestamps)
        cursor.execute("""
            SELECT center_frequency, bandwidth, start_time, end_time
            FROM intercepts
            WHERE intercept_id = ?
        """, (intercept_id,))

        intercept_row = cursor.fetchone()
        if not intercept_row:
            conn.close()
            return None

        # Get attachment metadata (rich JSON)
        cursor.execute("""
            SELECT body
            FROM intercept_attachments
            WHERE intercept_id = ?
            ORDER BY id DESC LIMIT 1
        """, (intercept_id,))

        attachment_row = cursor.fetchone()
        attachment_json = None
        radio_protocol = None

        if attachment_row and attachment_row['body']:
            try:
                attachment_data = json.loads(attachment_row['body'])
                attachment_json = json.dumps(attachment_data)

                # Extract protocol from standard/technology fields
                standard = attachment_data.get('standard', '').lower()
                technology = attachment_data.get('technology', '').lower()

                if standard == 'dmr' or technology == 'dmr':
                    radio_protocol = 'dmr'
                elif technology == 'ctcss':
                    radio_protocol = 'ctcss'
                elif technology == 'dcs':
                    radio_protocol = 'dcs'
                elif standard == 'nxdn' or 'nxdn' in technology:
                    radio_protocol = 'nxdn'
                elif standard:
                    radio_protocol = standard
                elif technology:
                    radio_protocol = technology
            except (json.JSONDecodeError, TypeError):
                pass

        # Get average RSSI
        cursor.execute("""
            SELECT AVG(rssi) as avg_rssi
            FROM intercept_rssis
            WHERE intercept_id = ?
        """, (intercept_id,))

        rssi_row = cursor.fetchone()
        avg_rssi = rssi_row['avg_rssi'] if rssi_row else None

        conn.close()

        # Convert nanosecond timestamps to seconds
        start_time_ns = intercept_row['start_time']
        intercept_timestamp = start_time_ns / 1e9 if start_time_ns else None

        return {
            'intercept_id': intercept_id,
            'radio_frequency': intercept_row['center_frequency'],
            'radio_bandwidth': intercept_row['bandwidth'],
            'radio_protocol': radio_protocol,
            'radio_rssi': round(avg_rssi, 2) if avg_rssi is not None else None,
            'radio_metadata': attachment_json,
            'intercept_timestamp': intercept_timestamp
        }

    except sqlite3.Error as e:
        logger.warning(f"Session DB query error for {wav_filename}: {e}")
        return None
    except Exception as e:
        logger.warning(f"Unexpected error querying session DB for {wav_filename}: {e}")
        return None


def get_radio_metadata_for_file(wav_path, session_context):
    """
    Main entry point: get all available radio metadata for a WAV file.

    Always parses the filename for baseline metadata. If a session context
    exists, queries the session DB and overrides filename-parsed values
    with richer data from the database.

    Args:
        wav_path (str or Path): Full path to the WAV file
        session_context (dict or None): From detect_session_context()

    Returns:
        dict: Radio metadata ready for DB insertion with keys:
            - radio_protocol (str or None)
            - radio_frequency (float or None)
            - radio_slot (int or None)
            - intercept_timestamp (float or None)
            - radio_metadata (str or None): JSON string
            - intercept_id (int or None)
            - radio_bandwidth (float or None)
            - radio_rssi (float or None)
    """
    wav_path = Path(wav_path)
    filename = wav_path.name

    # Start with filename-parsed metadata (always available)
    metadata = parse_radio_filename(filename)

    # Add fields that only come from session DB
    metadata['radio_metadata'] = None
    metadata['intercept_id'] = None
    metadata['radio_bandwidth'] = None
    metadata['radio_rssi'] = None

    # If session context exists, query DB for richer metadata
    if session_context:
        session_data = query_session_metadata(
            session_context['session_db_path'],
            filename
        )

        if session_data:
            # Session DB values override filename-parsed values where available
            if session_data.get('radio_protocol'):
                metadata['radio_protocol'] = session_data['radio_protocol']
            if session_data.get('radio_frequency') is not None:
                metadata['radio_frequency'] = session_data['radio_frequency']
            # Keep filename-parsed timestamp (per-file) over session DB
            # start_time (per-intercept session) — it's more granular
            if not metadata.get('intercept_timestamp') and session_data.get('intercept_timestamp') is not None:
                metadata['intercept_timestamp'] = session_data['intercept_timestamp']

            # Fields only available from session DB
            metadata['radio_metadata'] = session_data.get('radio_metadata')
            metadata['intercept_id'] = session_data.get('intercept_id')
            metadata['radio_bandwidth'] = session_data.get('radio_bandwidth')
            metadata['radio_rssi'] = session_data.get('radio_rssi')

    return metadata
