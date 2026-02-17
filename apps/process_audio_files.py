"""
Audio File Processing Module

This module handles the processing of WAV audio files for transcription and
speaker diarization. It integrates with the audio.py module and database.py
to provide a complete audio processing pipeline.

Main Functions:
- process_single_audio_file(): Main orchestrator for processing one file
- calculate_file_hash(): Generate SHA-256 hash for duplicate detection
- check_if_already_processed(): Query database for existing records
- save_audio_results(): Save processing results to database

Usage:
    from apps import process_audio_files as paf
    
    result = await paf.process_single_audio_file(
        '/path/to/file.wav',
        model_size='medium',
        db_manager=db_manager
    )
"""

# Standard library imports
import asyncio
import hashlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

# Local imports
import apps.audio as audio
import apps.database as db
import apps.gui_methods as gm
import apps.session_reader as session_reader

# Configure logger
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s', datefmt='%Y-%m-%d [%H:%M:%S]')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def calculate_file_hash(file_path):
    """
    Calculate SHA-256 hash of a file for duplicate detection.
    
    Args:
        file_path (str or Path): Path to the file
        
    Returns:
        str: Hexadecimal SHA-256 hash of the file
        
    Raises:
        FileNotFoundError: If file doesn't exist
        PermissionError: If file can't be read
    """
    hash_sha256 = hashlib.sha256()
    
    with open(file_path, 'rb') as f:
        # Read in 64KB chunks for memory efficiency
        for chunk in iter(lambda: f.read(65536), b''):
            hash_sha256.update(chunk)
    
    return hash_sha256.hexdigest()


def check_file_size(file_path, max_size_mb):
    """
    Check if file size is within acceptable limits.
    
    Args:
        file_path (str or Path): Path to the file
        max_size_mb (int): Maximum file size in megabytes
        
    Returns:
        tuple: (is_valid: bool, actual_size_mb: float)
    """
    file_size_bytes = os.path.getsize(file_path)
    file_size_mb = file_size_bytes / (1024 * 1024)
    
    is_valid = file_size_mb <= max_size_mb
    
    return is_valid, file_size_mb


def extract_wav_metadata(file_path):
    """
    Extract basic metadata from a WAV file.
    
    Args:
        file_path (str or Path): Path to the WAV file
        
    Returns:
        dict: Metadata including filename, file_path, file_size_mb
    """
    file_path = Path(file_path)
    file_size_bytes = os.path.getsize(file_path)
    file_size_mb = file_size_bytes / (1024 * 1024)
    
    return {
        'filename': file_path.name,
        'file_path': str(file_path.absolute()),
        'file_size_mb': file_size_mb
    }


def check_if_already_processed(file_hash, db_manager):
    """
    Check if a file has already been processed based on its hash.
    
    Args:
        file_hash (str): SHA-256 hash of the file
        db_manager: DatabaseManager instance
        
    Returns:
        dict or None: Audio file record if found, None otherwise
    """
    return db_manager.get_audio_by_hash(file_hash)


def save_audio_results(audio_data, segments, timeline, db_manager):
    """
    Save audio processing results to the database in a transaction.
    
    Args:
        audio_data (dict): Audio file metadata (filename, file_path, hash, etc.)
        segments (list): List of segment dicts from audio processing
        timeline (dict): Timeline visualization data
        db_manager: DatabaseManager instance
        
    Returns:
        tuple: (success: bool, audio_id: int or None, error_msg: str or None)
    """
    try:
        # Start by updating the audio file record with results
        success = db_manager.update_audio_status(
            audio_id=audio_data['audio_id'],
            processing_status='completed',
            duration_seconds=audio_data.get('duration_seconds'),
            sample_rate=audio_data.get('sample_rate'),
            language_detected=audio_data.get('language'),
            model_size_used=audio_data.get('model_size'),
            processed_at=datetime.now(timezone.utc)
        )
        
        if not success:
            return False, None, "Failed to update audio file status"
        
        # Insert segments
        if segments:
            success = db_manager.insert_audio_segments(
                audio_id=audio_data['audio_id'],
                segments_data=segments
            )
            if not success:
                return False, None, "Failed to insert audio segments"
        
        # Insert timeline
        if timeline:
            success = db_manager.insert_audio_timeline(
                audio_id=audio_data['audio_id'],
                timeline_visualization=timeline.get('timeline_str', ''),
                total_speaking_seconds=timeline.get('total_speaking_seconds'),
                silence_percentage=timeline.get('silence_percentage')
            )
            if not success:
                return False, None, "Failed to insert audio timeline"
        
        return True, audio_data['audio_id'], None
        
    except Exception as e:
        error_msg = f"Database save error: {str(e)}"
        logger.error(error_msg)
        return False, None, error_msg


async def process_single_audio_file(file_path, model_size, max_file_size_mb, db_manager, session_context=None):
    """
    Main orchestrator function to process a single audio file.

    This function handles the complete workflow:
    1. Validate file size
    2. Calculate hash and check for duplicates
    3. Extract radio metadata (if session context available)
    4. Insert pending record
    5. Run audio processing
    6. Save results to database
    7. Handle errors appropriately

    Args:
        file_path (str or Path): Path to the WAV file
        model_size (str): Whisper model size to use
        max_file_size_mb (int): Maximum file size in MB
        db_manager: DatabaseManager instance
        session_context (dict, optional): From session_reader.detect_session_context()

    Returns:
        dict: Processing result with keys:
            - success (bool): Whether processing succeeded
            - audio_id (int or None): Database record ID
            - status (str): 'completed', 'error', or 'skipped'
            - message (str): Human-readable status message
    """
    file_path = Path(file_path)
    filename = file_path.name
    
    try:
        # Step 1: Check file size
        is_valid_size, actual_size_mb = check_file_size(file_path, max_file_size_mb)
        if not is_valid_size:
            logger.error(f"File too large: {filename} ({actual_size_mb:.1f} MB > {max_file_size_mb} MB limit)")
            return {
                'success': False,
                'audio_id': None,
                'status': 'error',
                'message': f"File exceeds size limit ({actual_size_mb:.1f} MB > {max_file_size_mb} MB)"
            }
        
        # Step 2: Calculate hash
        logger.debug(f"Calculating hash for {filename}...")
        file_hash = calculate_file_hash(file_path)
        
        # Step 3: Check if already processed
        existing_record = check_if_already_processed(file_hash, db_manager)
        if existing_record:
            status = existing_record['processing_status']
            if status == 'completed':
                logger.debug(f"Already processed: {filename} (skipped)")
                return {
                    'success': True,
                    'audio_id': existing_record['audio_id'],
                    'status': 'skipped',
                    'message': 'Already processed'
                }
            elif status == 'processing':
                logger.debug(f"Currently processing: {filename} (skipped)")
                return {
                    'success': False,
                    'audio_id': existing_record['audio_id'],
                    'status': 'skipped',
                    'message': 'Already being processed'
                }
            # If status is 'error' or 'pending', continue to reprocess
        
        # Step 4: Extract metadata
        metadata = extract_wav_metadata(file_path)

        # Step 4b: Extract radio metadata (if session context available)
        radio_meta = session_reader.get_radio_metadata_for_file(file_path, session_context)
        if radio_meta.get('radio_protocol'):
            logger.info(f"Radio metadata: {radio_meta['radio_protocol'].upper()} "
                        f"{radio_meta.get('radio_frequency', 0) / 1e6:.3f} MHz")

        # Step 5: Insert or update database record with 'processing' status
        if existing_record:
            audio_id = existing_record['audio_id']
            db_manager.update_audio_status(audio_id, 'processing')
            logger.info(f"Reprocessing {filename} (audio_id: {audio_id})")
        else:
            audio_id = db_manager.insert_audio_file(
                filename=metadata['filename'],
                file_path=metadata['file_path'],
                file_hash=file_hash,
                processing_status='processing',
                model_size_used=model_size,
                radio_protocol=radio_meta.get('radio_protocol'),
                radio_frequency=radio_meta.get('radio_frequency'),
                radio_slot=radio_meta.get('radio_slot'),
                intercept_timestamp=radio_meta.get('intercept_timestamp'),
                radio_metadata=radio_meta.get('radio_metadata'),
                intercept_id=radio_meta.get('intercept_id'),
                radio_bandwidth=radio_meta.get('radio_bandwidth'),
                radio_rssi=radio_meta.get('radio_rssi'),
            )
            if not audio_id:
                logger.error(f"Failed to create database record for {filename}")
                return {
                    'success': False,
                    'audio_id': None,
                    'status': 'error',
                    'message': 'Failed to create database record'
                }
        
        # Log processing start
        duration_str = f"{actual_size_mb:.1f} MB"
        logger.info(f"Processing: {filename} ({duration_str})")
        
        # Step 6: Run audio processing - ALWAYS transcribe in original language first
        loop = asyncio.get_event_loop()
        try:
            results_original = await loop.run_in_executor(
                None,
                audio.process_audio_file,
                str(file_path),
                model_size,
                False,  # translate=False - get original language
                True    # offline_mode=True
            )
        except FileNotFoundError as e:
            error_msg = f"File not found: {str(e)}"
            logger.error(f"Processing failed for {filename}: {error_msg}")
            db_manager.update_audio_status(audio_id, 'error', error_message=error_msg)
            return {
                'success': False,
                'audio_id': audio_id,
                'status': 'error',
                'message': error_msg
            }
        except RuntimeError as e:
            error_msg = f"Processing error: {str(e)}"
            logger.error(f"Processing failed for {filename}: {error_msg}")
            db_manager.update_audio_status(audio_id, 'error', error_message=error_msg)
            return {
                'success': False,
                'audio_id': audio_id,
                'status': 'error',
                'message': error_msg
            }
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            logger.error(f"Processing failed for {filename}: {error_msg}")
            db_manager.update_audio_status(audio_id, 'error', error_message=error_msg)
            return {
                'success': False,
                'audio_id': audio_id,
                'status': 'error',
                'message': error_msg
            }
        
        # Log processing completion
        num_segments = len(results_original.get('segments', []))
        language = results_original.get('language', 'unknown')
        duration_formatted = format_duration(results_original.get('duration_seconds', 0))
        
        logger.info(f"Original transcription complete - {num_segments} segments, language: {language}, duration: {duration_formatted}")
        
        # Step 7: Check if we need English translation
        results_english = None
        if language.lower() != 'en':
            logger.info(f"Detected non-English audio ({language}) - processing English translation...")
            try:
                results_english = await loop.run_in_executor(
                    None,
                    audio.process_audio_file,
                    str(file_path),
                    model_size,
                    True,   # translate=True - translate to English
                    True    # offline_mode=True
                )
                logger.info(f"English translation complete - {len(results_english.get('segments', []))} segments")
            except Exception as e:
                logger.warning(f"English translation failed: {str(e)} - continuing with original only")
                results_english = None
        else:
            logger.info("Audio is already in English - skipping translation")
        
        # Step 8: Save results to database
        audio_data = {
            'audio_id': audio_id,
            'duration_seconds': results_original.get('duration_seconds'),
            'sample_rate': results_original.get('sample_rate'),
            'language': results_original.get('language'),
            'model_size': model_size
        }
        
        timeline_data = {
            'timeline_str': results_original.get('timeline_str', ''),
            'total_speaking_seconds': results_original.get('total_speaking_seconds'),
            'silence_percentage': results_original.get('silence_percentage')
        }
        
        # Transform segments from audio.py format to database format
        # Always save original language segments
        segments_for_db = []
        for seg in results_original.get('segments', []):
            segment_dict = {
                'speaker_label': seg.get('speaker', 'UNKNOWN'),
                'start_time': seg.get('start', 0.0),
                'end_time': seg.get('end', 0.0),
                'transcript_original': seg.get('text', ''),  # Original language
                'transcript_english': None,  # Will be filled if translation exists
                'segment_order': seg.get('segment_order', 0)
            }
            
            # If we have English translation, add it to the same segment
            if results_english and len(results_english.get('segments', [])) > seg.get('segment_order', 0):
                english_seg = results_english.get('segments', [])[seg.get('segment_order', 0)]
                segment_dict['transcript_english'] = english_seg.get('text', '')
            
            segments_for_db.append(segment_dict)
        
        success, saved_audio_id, error_msg = save_audio_results(
            audio_data,
            segments_for_db,
            timeline_data,
            db_manager
        )
        
        if not success:
            logger.error(f"Failed to save results for {filename}: {error_msg}")
            db_manager.update_audio_status(audio_id, 'error', error_message=error_msg)
            return {
                'success': False,
                'audio_id': audio_id,
                'status': 'error',
                'message': error_msg
            }
        
        logger.info(f"Saved to database - audio_id: {audio_id}")
        logger.info(f"Processing complete: {filename}")
        
        return {
            'success': True,
            'audio_id': audio_id,
            'status': 'completed',
            'message': f'Processed successfully ({num_segments} segments, {language})'
        }
        
    except PermissionError as e:
        error_msg = f"Permission denied: {str(e)}"
        logger.error(f"Cannot access {filename}: {error_msg}")
        return {
            'success': False,
            'audio_id': None,
            'status': 'error',
            'message': error_msg
        }
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.error(f"Failed to process {filename}: {error_msg}")
        return {
            'success': False,
            'audio_id': None,
            'status': 'error',
            'message': error_msg
        }


def format_duration(seconds):
    """
    Format duration in seconds to human-readable string.

    Args:
        seconds (float): Duration in seconds

    Returns:
        str: Formatted duration (e.g., "5:32", "1:23:45")
    """
    if seconds > 0 and seconds < 1:
        return "0:01"
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes}:{secs:02d}"
