# Standard library imports
import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

# Local application imports
import apps.database as db
import apps.gui_methods as gm
import apps.process_audio_files as paf
import apps.session_reader as session_reader

# Configure logger properly
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    #formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s', datefmt='%Y-%m-%d [%H:%M:%S]')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)  # Changed from INFO to DEBUG

class simple_timer:
    def __init__(self, browser_service=None, db_manager=None):
        self.browser_service = browser_service
        self.db_manager = db_manager if db_manager is not None else db._db_manager
        self.duration = 60  # Default duration in seconds
        self.check_interval = 30  # Check database connection every 30 seconds when disconnected
        self._db_not_connected_logged = False  # Track if we've logged the DB not connected message
        self._no_folder_logged = False  # Track if we've logged the no folder message
        logger.info(f"SimpleTimer initialized (db_manager: {id(self.db_manager)})")
        
    def set_browser_service(self, browser_service):
        """Set the browser service for this GUI instance"""
        self.browser_service = browser_service
        
    async def run(self):
        """Main menu loop"""
        loop_iteration = 0
        while True:
            try:
                loop_iteration += 1
                
                # Check if database is connected before proceeding
                if not self.db_manager.is_connected():
                    # Only log once to avoid spam
                    if not self._db_not_connected_logged:
                        logger.info(f"Database not connected - waiting for connection (db_manager: {id(self.db_manager)})")
                        self._db_not_connected_logged = True
                    # Reset folder flag since we're not checking
                    self._no_folder_logged = False
                    # Check more frequently when waiting for database connection
                    logger.debug(f"Timer loop #{loop_iteration}: DB not connected, sleeping {self.check_interval}s")
                    await asyncio.sleep(self.check_interval)
                    continue
                
                # Reset the flag since we're now connected
                if self._db_not_connected_logged:
                    logger.info("Database connection detected - resuming audio file checks")
                    self._db_not_connected_logged = False
                
                # Check if audio folder is configured
                settings = gm.get_settings()
                watch_folder = settings.get('audio', {}).get('watch_folder', '')
                
                if not watch_folder or not os.path.exists(watch_folder):
                    # Only log once to avoid spam
                    if not self._no_folder_logged:
                        logger.info("No audio folder configured - waiting for folder selection")
                        self._no_folder_logged = True
                    logger.debug(f"Timer loop #{loop_iteration}: No folder configured, sleeping {self.check_interval}s")
                    await asyncio.sleep(self.check_interval)
                    continue
                
                # Reset the flag since we now have a folder
                if self._no_folder_logged:
                    logger.info(f"Audio folder detected: {watch_folder}")
                    self._no_folder_logged = False
                
                # Log that we're running a check
                logger.debug(f"Timer loop #{loop_iteration}: Running audio file check cycle")
                
                """ Check for WAV files in the watch folder (recursive) """
                # Detect session context once per cycle (radio metadata)
                session_context = session_reader.detect_session_context(watch_folder)

                # Find all WAV files recursively
                all_wav_files = list(Path(watch_folder).rglob('*.wav'))
                total_count = len(all_wav_files)
                
                # Get settings for processing
                model_size = settings.get('audio', {}).get('model_size', 'medium')
                max_file_size_mb = settings.get('audio', {}).get('max_file_size_mb', 100)
                
                # Filter to only NEW files (not in database or with status='error')
                new_files = []
                for wav_file in all_wav_files:
                    try:
                        file_hash = paf.calculate_file_hash(wav_file)
                        db_record = paf.check_if_already_processed(file_hash, self.db_manager)
                        
                        if not db_record:
                            new_files.append(wav_file)  # Completely new
                        elif db_record['processing_status'] == 'error':
                            new_files.append(wav_file)  # Retry errors each cycle
                        # else: status='completed' or 'processing' → skip
                    except Exception as e:
                        logger.error(f"Error checking file {wav_file.name}: {str(e)}")
                        continue
                
                already_processed = total_count - len(new_files)
                
                if len(new_files) > 0:
                    logger.info(f"Found {len(new_files)} new wav files ({total_count} total, {already_processed} already processed)")
                    
                    # Process each new file
                    for idx, wav_file in enumerate(new_files, 1):
                        logger.info(f"Processing {idx}/{len(new_files)}: {wav_file.name}")
                        
                        result = await paf.process_single_audio_file(
                            file_path=wav_file,
                            model_size=model_size,
                            max_file_size_mb=max_file_size_mb,
                            db_manager=self.db_manager,
                            session_context=session_context
                        )
                        
                        if not result['success'] and result['status'] != 'skipped':
                            logger.error(f"Failed to process {wav_file.name}: {result['message']}")
                else:
                    logger.debug(f"Found 0 new wav files ({total_count} total, {already_processed} already processed)")
                
                # Log completion of this cycle
                logger.debug(f"Timer loop #{loop_iteration}: Completed check cycle, sleeping {self.duration}s")
  
            except Exception as e:
                logger.error(f"Error in simple_timer loop: {e}")
            
            await asyncio.sleep(self.duration)
    
    def set_timer_duration(self, duration):
        """Set the timer duration in seconds"""
        if duration <= 0:
            logger.error("Invalid timer duration. Must be greater than 0.")
            return
        self.duration = duration
        """Log the new timer duration in a human-readable format"""
        logger.info(f"Timer duration set to {gm.convert_seconds_to_human_readable(self.duration)}")