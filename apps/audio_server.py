"""
Audio Frontend Server - FastAPI web server for displaying transcription data

Run with: python -m audio_frontend.audio_server
"""

# Standard library imports
import getpass
import logging
import os
from datetime import datetime, timezone
from urllib.parse import quote_plus

# Third-party imports
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from uvicorn import run as uvicorn_run

# Local imports
import apps.database as db

# Configure logger
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s', datefmt='%Y-%m-%d [%H:%M:%S]')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class AudioServer:
    """FastAPI-based web server for displaying audio transcription data"""

    def __init__(self, db_manager, host='0.0.0.0', port=8081):
        self.db_manager = db_manager
        self.host = host
        self.port = port

        # Get the directory where this file is located (apps/)
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        # web_gui is a sibling directory to apps/
        self.web_gui_dir = os.path.join(os.path.dirname(self.base_dir), 'web_gui')
        self.template_dir = os.path.join(self.web_gui_dir, 'templates', 'audio')
        self.static_dir = os.path.join(self.web_gui_dir, 'static')
        
        # Favicon is in the web_gui static directory
        self.web_gui_static = self.static_dir

        # Create FastAPI app
        self.app = FastAPI(
            title="Audio Transcription Viewer",
            description="View transcribed audio files with speaker diarization"
        )

        # Setup templates
        self.templates = Jinja2Templates(directory=self.template_dir)

        # Add custom Jinja2 filters
        self.templates.env.filters['format_duration'] = self._format_duration
        self.templates.env.filters['format_timestamp'] = self._format_timestamp
        self.templates.env.filters['format_intercept_time'] = self._format_intercept_time
        self.templates.env.filters['format_intercept_time_full'] = self._format_intercept_time_full
        self.templates.env.filters['from_json'] = self._from_json

        # Mount static files
        if os.path.exists(self.static_dir):
            self.app.mount("/static", StaticFiles(directory=self.static_dir), name="static")

        # Setup routes
        self._setup_routes()

        logger.debug(f"AudioServer initialized (templates: {self.template_dir})")
        logger.info(f"AudioServer initialized")
        
    @staticmethod
    def _format_duration(seconds):
        """Format seconds as MM:SS.t or HH:MM:SS.t (with tenths of a second)"""
        if seconds is None:
            return "0:00.0"
        
        total_seconds = seconds
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        secs = total_seconds % 60
        
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:04.1f}"
        else:
            return f"{minutes}:{secs:04.1f}"

    @staticmethod
    def _format_timestamp(seconds):
        """Format seconds as timestamp for segments"""
        if seconds is None:
            return "0:00.0"
        minutes = int(seconds) // 60
        secs = seconds % 60
        return f"{minutes}:{secs:05.2f}"

    @staticmethod
    def _format_intercept_time(epoch):
        """Format Unix epoch timestamp as HH:MM:SS"""
        if epoch is None:
            return "—"
        from datetime import datetime
        dt = datetime.fromtimestamp(epoch)
        return dt.strftime("%H:%M:%S")

    @staticmethod
    def _format_intercept_time_full(epoch):
        """Format Unix epoch timestamp as full date/time with timezone"""
        if epoch is None:
            return ""
        from datetime import datetime
        import time
        dt = datetime.fromtimestamp(epoch)
        # Format: May 15, 2021\n01:49:33 EDT
        date_str = dt.strftime("%B %d, %Y")
        # Get timezone name (EST/EDT)
        tz_name = time.tzname[time.daylight and time.localtime(epoch).tm_isdst]
        time_str = dt.strftime(f"%H:%M:%S {tz_name}")
        return f"{date_str}\n{time_str}"

    @staticmethod
    def _from_json(json_str):
        """Parse JSON string to Python dict/list for Jinja2 templates"""
        if not json_str:
            return {}
        import json
        try:
            return json.loads(json_str)
        except (json.JSONDecodeError, TypeError):
            return {}

    def _setup_routes(self):
        """Setup FastAPI routes"""

        @self.app.get("/", response_class=RedirectResponse)
        async def root():
            """Redirect root to audio list"""
            return RedirectResponse(url="/audio", status_code=302)
        
        @self.app.get("/favicon.ico")
        async def favicon():
            """Serve favicon from web_gui static directory"""
            from fastapi.responses import FileResponse
            favicon_path = os.path.join(self.web_gui_static, 'favico.ico')
            if os.path.exists(favicon_path):
                return FileResponse(favicon_path, media_type='image/x-icon')
            raise HTTPException(status_code=404, detail="Favicon not found")

        @self.app.get("/audio", response_class=HTMLResponse)
        async def audio_list(request: Request):
            """Render the audio file list page"""
            if not self.db_manager or not self.db_manager.is_connected():
                raise HTTPException(status_code=503, detail="Database not connected")

            try:
                audio_files = self.db_manager.get_all_audio_files()

                # Determine which metadata columns have data
                has_time = any(f.get('intercept_timestamp') for f in audio_files)
                has_rssi = any(f.get('radio_rssi') is not None for f in audio_files)
                has_frequency = any(f.get('radio_frequency') for f in audio_files)

                return self.templates.TemplateResponse(
                    "audio_list.html",
                    {
                        "request": request,
                        "audio_files": audio_files,
                        "has_time": has_time,
                        "has_rssi": has_rssi,
                        "has_frequency": has_frequency
                    }
                )
            except Exception as e:
                logger.error(f"Error loading audio list: {str(e)}")
                raise HTTPException(status_code=500, detail=f"Error loading audio files: {str(e)}")

        @self.app.get("/audio/{audio_id}", response_class=HTMLResponse)
        async def audio_detail(request: Request, audio_id: int):
            """Render the audio detail page with transcript"""
            if not self.db_manager or not self.db_manager.is_connected():
                raise HTTPException(status_code=503, detail="Database not connected")

            try:
                data = self.db_manager.get_audio_file_with_details(audio_id)
                if not data:
                    raise HTTPException(status_code=404, detail="Audio file not found")

                return self.templates.TemplateResponse(
                    "audio_detail.html",
                    {
                        "request": request,
                        "file": data['file'],
                        "timeline": data['timeline'],
                        "segments": data['segments'],
                        "speakers": data['speakers']
                    }
                )
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error loading audio detail: {str(e)}")
                raise HTTPException(status_code=500, detail=f"Error loading audio file: {str(e)}")

        # ============================================================
        # JSON API Endpoints
        # ============================================================

        @self.app.get("/api/audio/files")
        async def api_audio_files():
            """JSON API: Get all completed audio files"""
            if not self.db_manager or not self.db_manager.is_connected():
                raise HTTPException(status_code=503, detail="Database not connected")

            try:
                audio_files = self.db_manager.get_all_audio_files()
                # Convert datetime objects to ISO format strings
                for af in audio_files:
                    if af.get('created_at'):
                        af['created_at'] = af['created_at'].isoformat()
                    if af.get('processed_at'):
                        af['processed_at'] = af['processed_at'].isoformat()

                return JSONResponse(content={"files": audio_files})
            except Exception as e:
                logger.error(f"API error (files): {str(e)}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get("/api/audio/files/{audio_id}")
        async def api_audio_detail(audio_id: int):
            """JSON API: Get audio file with details"""
            if not self.db_manager or not self.db_manager.is_connected():
                raise HTTPException(status_code=503, detail="Database not connected")

            try:
                data = self.db_manager.get_audio_file_with_details(audio_id)
                if not data:
                    raise HTTPException(status_code=404, detail="Audio file not found")

                # Convert datetime objects to ISO format strings
                if data['file'].get('created_at'):
                    data['file']['created_at'] = data['file']['created_at'].isoformat()
                if data['file'].get('processed_at'):
                    data['file']['processed_at'] = data['file']['processed_at'].isoformat()

                return JSONResponse(content=data)
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"API error (detail): {str(e)}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get("/api/audio/stats")
        async def api_audio_stats():
            """JSON API: Get dashboard statistics"""
            if not self.db_manager or not self.db_manager.is_connected():
                raise HTTPException(status_code=503, detail="Database not connected")

            try:
                session = self.db_manager.get_session()
                try:
                    from sqlalchemy import func

                    # Count files by status
                    total = session.query(func.count(db.AudioFile.id)).scalar() or 0
                    completed = session.query(func.count(db.AudioFile.id)).filter(
                        db.AudioFile.processing_status == 'completed'
                    ).scalar() or 0
                    pending = session.query(func.count(db.AudioFile.id)).filter(
                        db.AudioFile.processing_status == 'pending'
                    ).scalar() or 0
                    errors = session.query(func.count(db.AudioFile.id)).filter(
                        db.AudioFile.processing_status == 'error'
                    ).scalar() or 0

                    # Total duration
                    total_duration = session.query(func.sum(db.AudioFile.duration_seconds)).filter(
                        db.AudioFile.processing_status == 'completed'
                    ).scalar() or 0

                    # Total segments
                    total_segments = session.query(func.count(db.AudioSegment.id)).scalar() or 0

                    return JSONResponse(content={
                        "total_files": total,
                        "completed": completed,
                        "pending": pending,
                        "errors": errors,
                        "total_duration_seconds": total_duration,
                        "total_segments": total_segments
                    })
                finally:
                    session.close()
            except Exception as e:
                logger.error(f"API error (stats): {str(e)}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get("/audio/{audio_id}/stream")
        async def stream_audio(audio_id: int):
            """Stream WAV file for browser playback"""
            from fastapi.responses import FileResponse
            import os

            try:
                # Get file path from database
                audio_file = self.db_manager.get_audio_file_with_details(audio_id)
                if not audio_file:
                    raise HTTPException(status_code=404, detail="Audio file not found in database")

                file_path = audio_file['file']['file_path']

                # Verify file exists on filesystem
                if not os.path.exists(file_path):
                    logger.warning(f"Audio file not found on disk: {file_path}")
                    raise HTTPException(status_code=404, detail="Audio file not found on server")

                # Return file with range request support (enables seeking)
                return FileResponse(
                    path=file_path,
                    media_type='audio/wav',
                    headers={
                        'Accept-Ranges': 'bytes',
                        'Content-Disposition': 'inline'
                    }
                )
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error streaming audio {audio_id}: {str(e)}")
                raise HTTPException(status_code=500, detail="Internal server error")

        @self.app.get("/stream-audio-files")
        async def stream_audio_files():
            """Server-Sent Events endpoint for real-time audio file updates"""
            from fastapi.responses import StreamingResponse
            import asyncio
            import json
            import time
            
            async def audio_files_event_stream():
                """Generator for SSE events"""
                last_data_hash = None
                
                while True:
                    try:
                        # Check if database is connected
                        if not self.db_manager or not self.db_manager.is_connected():
                            yield f"data: {json.dumps({'error': 'Database not connected'})}\n\n"
                            await asyncio.sleep(5)
                            continue
                        
                        # Get current audio files data (only completed files)
                        session = self.db_manager.get_session()
                        try:
                            files = session.query(db.AudioFile).filter(
                                db.AudioFile.processing_status == 'completed'
                            ).order_by(db.AudioFile.processed_at.desc()).all()
                            
                            # Build simplified data for change detection
                            files_data = []
                            for f in files:
                                files_data.append({
                                    'id': f.id,
                                    'filename': f.filename,
                                    'processed_at': f.processed_at.isoformat() if f.processed_at else None
                                })
                            
                            # Create hash for change detection (only IDs and processed_at)
                            data_for_hash = [f"{d['id']}|{d['processed_at']}" for d in files_data]
                            current_data_hash = hash('|'.join(sorted(data_for_hash)))
                            
                            # Only send if data changed
                            if current_data_hash != last_data_hash:
                                yield f"data: {json.dumps({'file_count': len(files_data), 'files': files_data})}\n\n"
                                last_data_hash = current_data_hash
                            
                        finally:
                            session.close()
                        
                        await asyncio.sleep(5)  # Check every 5 seconds
                        
                    except Exception as e:
                        logger.error(f"SSE stream error: {str(e)}")
                        yield f"data: {json.dumps({'error': str(e)})}\n\n"
                        await asyncio.sleep(5)
            
            return StreamingResponse(
                audio_files_event_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no"  # Disable nginx buffering
                }
            )

    def start(self):
        """Start the FastAPI server with Uvicorn"""
        try:
            logger.info(f"Starting Audio Server on {self.host}:{self.port}")
            uvicorn_run(
                self.app,
                host=self.host,
                port=self.port,
                log_level="info"
            )
        except Exception as e:
            logger.error(f"Failed to start Audio Server: {str(e)}")
            raise


def setup_database_connection():
    """Setup database connection with user prompts"""
    db_manager = db.DatabaseManager()

    print("\n=== Audio Frontend Server ===")
    print("Database connection required.\n")

    # Get connection details
    db_manager.db_config = {
        'host': input("Host [localhost]: ").strip() or "localhost",
        'port': int(input("Port [3306]: ").strip() or "3306"),
        'user': input("Username: ").strip(),
        'password': getpass.getpass("Password: "),
        'database': input("Database: ").strip()
    }

    # Create engine
    encoded_password = quote_plus(db_manager.db_config['password'])
    mysql_url = (
        f"mysql+pymysql://{db_manager.db_config['user']}:{encoded_password}"
        f"@{db_manager.db_config['host']}:{db_manager.db_config['port']}"
        f"/{db_manager.db_config['database']}"
    )

    db_manager.engine = create_engine(mysql_url, pool_pre_ping=True, pool_recycle=3600)
    db_manager.Session = sessionmaker(bind=db_manager.engine)

    # Test connection
    try:
        with db_manager.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_manager._connected = True
        print("\nDatabase connected successfully!")
    except Exception as e:
        print(f"\nFailed to connect to database: {str(e)}")
        raise

    return db_manager


def main():
    """Main entry point"""
    try:
        # Setup database connection
        db_manager = setup_database_connection()

        # Create and start server
        server = AudioServer(db_manager, host='0.0.0.0', port=8081)
        print(f"\nStarting server at http://localhost:8081/audio\n")
        server.start()

    except KeyboardInterrupt:
        print("\nShutdown requested...")
    except Exception as e:
        logger.error(f"Server error: {str(e)}")
        raise


if __name__ == "__main__":
    main()
