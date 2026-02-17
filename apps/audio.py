import warnings
# Suppress warnings before imports
warnings.filterwarnings("ignore", category=UserWarning)

import sys
import os
import argparse
import socket

# Check network connectivity when --update is used
def check_network_connectivity():
    """Quick check if we can reach the internet."""
    try:
        # Try to connect to Google DNS with short timeout
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        return True
    except OSError:
        return False


# ==============================================================================
# CORE PROCESSING FUNCTIONS - Can be imported and called programmatically
# ==============================================================================

def process_audio_file(audio_file_path, model_size='medium', translate=False, offline_mode=True):
    """
    Process an audio file with speaker diarization and transcription.

    This function can be imported and called from other Python code without
    using the command-line interface.

    Args:
        audio_file_path (str): Path to the audio file to process
        model_size (str): Whisper model size ('tiny', 'small', 'medium', 'large-v3', 'turbo')
        translate (bool): If True, translate to English; if False, transcribe in original language
        offline_mode (bool): If True, force offline mode (use cached models only)

    Returns:
        dict: Processing results with structure:
            {
                'duration_seconds': float,
                'sample_rate': int,
                'language': str,
                'timeline_str': str,
                'total_speaking_seconds': float,
                'silence_percentage': float,
                'segments': [
                    {
                        'start': float,
                        'end': float,
                        'text': str,
                        'speaker': str,
                        'segment_order': int
                    },
                    ...
                ]
            }

    Raises:
        FileNotFoundError: If audio file doesn't exist
        RuntimeError: If processing fails
    """
    # Set offline mode BEFORE importing pyannote/huggingface_hub
    # so the hub client initializes in offline mode and skips HTTP requests
    if offline_mode:
        os.environ["HF_HUB_OFFLINE"] = "1"

    import torch
    import torchaudio
    from pyannote.audio import Pipeline
    from faster_whisper import WhisperModel
    from datetime import timedelta

    # Validate file exists
    if not os.path.exists(audio_file_path):
        raise FileNotFoundError(f"Audio file not found: {audio_file_path}")

    # Load diarization pipeline
    try:
        diarizer = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")
    except Exception as e:
        if "401" in str(e) or "403" in str(e) or "gated" in str(e).lower():
            raise RuntimeError("Pyannote model not cached. Run 'python apps/audio.py --update' first to download models.")
        else:
            raise RuntimeError(f"Failed to load diarization model: {str(e)}")

    diarizer.to(torch.device("cuda"))

    # Load Whisper transcription model
    device = "cpu"
    compute_type = "int8"
    try:
        transcriber = WhisperModel(model_size, device=device, compute_type=compute_type)
    except Exception as e:
        raise RuntimeError(f"Failed to load Whisper model: {str(e)}")

    # Run diarization - pass file path directly
    diarization = diarizer(audio_file_path)

    # Get audio duration from waveform (more reliable than diarization extent for short audio)
    waveform, sample_rate = torchaudio.load(audio_file_path)
    duration_seconds = waveform.shape[1] / sample_rate
    del waveform
    is_short_audio = duration_seconds <= 2.0

    torch.cuda.empty_cache()
    
    # Build speaker map for timeline and alignment
    speaker_map = {}
    for turn, _, speaker in diarization.speaker_diarization.itertracks(yield_label=True):
        for t in range(int(turn.start * 10), int(turn.end * 10)):  # 100ms steps
            speaker_map[round(t / 10, 2)] = speaker
    
    # Create timeline segments (speech/silence blocks)
    timeline_segments = []
    speaking_seconds = 0

    if not is_short_audio:
        # Standard timeline: group consecutive speech/silence into segments
        current_type = None
        current_start = 0

        for t in range(0, max(1, int(duration_seconds))):
            has_speaker = any(speaker_map.get(round(sub_t / 10, 2), None)
                             for sub_t in range(t*10, (t+1)*10)
                             if speaker_map.get(round(sub_t / 10, 2), None) not in [None, "UNKNOWN"])

            segment_type = "speech" if has_speaker else "silence"

            if segment_type != current_type:
                if current_type is not None:
                    timeline_segments.append({
                        "start": current_start,
                        "end": t,
                        "type": current_type
                    })
                current_start = t
                current_type = segment_type

            if has_speaker:
                speaking_seconds += 1

        # Add final segment
        if current_type is not None:
            timeline_segments.append({
                "start": current_start,
                "end": max(1, int(duration_seconds)),
                "type": current_type
            })
    # Short audio timeline is deferred until after transcription (see below)
    
    # Create compact timeline data structure
    import json
    timeline_data = {
        "format": "segments",
        "version": "2.0",
        "duration": float(duration_seconds),
        "segments": timeline_segments
    }
    timeline_str = json.dumps(timeline_data)
    
    silence_percentage = ((duration_seconds - speaking_seconds) / duration_seconds * 100) if duration_seconds > 0 else 0
    
    # Run transcription
    try:
        task = "translate" if translate else "transcribe"
        segments_iter, info = transcriber.transcribe(audio_file_path, beam_size=1, vad_filter=True, task=task)
    except RuntimeError as e:
        raise RuntimeError(f"Transcription failed: {str(e)}")
    
    torch.cuda.empty_cache()
    
    # Process segments and align with speakers
    segments_list = []
    segment_order = 0
    
    for seg in segments_iter:
        start = seg.start
        end = seg.end
        text = seg.text.strip()
        
        # Find dominant speaker in this segment
        times = range(int(start * 10), int(end * 10))
        speakers_in_seg = [speaker_map.get(round(t / 10, 2), "UNKNOWN") for t in times]
        seg_speaker = max(set(speakers_in_seg), key=speakers_in_seg.count) if speakers_in_seg else "UNKNOWN"
        
        segments_list.append({
            'start': start,
            'end': end,
            'text': text,
            'speaker': seg_speaker,
            'segment_order': segment_order
        })
        segment_order += 1

    # Deferred short audio timeline: full speech if segments found, full silence otherwise
    if is_short_audio:
        if segments_list:
            timeline_segments = [{"start": 0, "end": round(duration_seconds, 2), "type": "speech"}]
            speaking_seconds = round(duration_seconds, 2)
        else:
            timeline_segments = [{"start": 0, "end": round(duration_seconds, 2), "type": "silence"}]
            speaking_seconds = 0
        # Rebuild timeline_str and silence_percentage with updated data
        timeline_data = {
            "format": "segments",
            "version": "2.0",
            "duration": float(duration_seconds),
            "segments": timeline_segments
        }
        timeline_str = json.dumps(timeline_data)
        silence_percentage = ((duration_seconds - speaking_seconds) / duration_seconds * 100) if duration_seconds > 0 else 0

    # Clean up models
    del diarizer
    del transcriber
    torch.cuda.empty_cache()
    
    # Return structured data
    return {
        'duration_seconds': float(duration_seconds),
        'sample_rate': int(sample_rate),
        'language': info.language,
        'timeline_str': timeline_str,
        'total_speaking_seconds': float(speaking_seconds),
        'silence_percentage': float(silence_percentage),
        'segments': segments_list
    }


# ==============================================================================
# COMMAND-LINE INTERFACE - Only runs when executed as script
# ==============================================================================

def main():
    """Command-line interface for audio processing."""
    import torch
    import torchaudio
    from pyannote.audio import Pipeline
    from faster_whisper import WhisperModel
    from datetime import timedelta
    
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='Process audio file with speaker diarization and transcription.')
    parser.add_argument('audio_file', nargs='?', help='Path to the audio file to process (optional with --update)')
    parser.add_argument('--model_size', default='medium', choices=['tiny', 'small', 'medium', 'large-v3', 'turbo'],
                        help='Whisper model size (default: medium)')
    parser.add_argument('--update', action='store_true', 
                        help='Allow online updates for models (checks connectivity first)')
    parser.add_argument('--list', action='store_true',
                        help='List available models and their cache status')
    parser.add_argument('--translate', action='store_true',
                        help='Translate audio to English (default: transcribe in original language)')

    args = parser.parse_args()

    # Check network connectivity if --update is requested
    if args.update and not check_network_connectivity():
        print("\n" + "="*50)
        print("No internet connection detected.")
        print("Cannot check for model updates.")
        if not args.audio_file:
            print("Exiting - no audio file to process.")
            sys.exit(0)
        print("Using cached models only.")
        print("Connect to internet and try again to check for updates.")
        print("="*50)
        # Force offline mode
        os.environ["HF_HUB_OFFLINE"] = "1"

    # Handle --list (exit early)
    if args.list:
        cache_dir = os.path.expanduser("~/.cache/huggingface/hub")

        print("Available models and cache status:")
        print()

        # Check pyannote model
        pyannote_path = os.path.join(cache_dir, "models--pyannote--speaker-diarization-3.1")
        pyannote_status = "✅ Cached" if os.path.exists(pyannote_path) else "❌ Not cached"
        print(f"Speaker Diarization: {pyannote_status}")
        print("  pyannote/speaker-diarization-3.1")
        print()

        # Check Whisper models
        print("Whisper Transcription Models:")
        whisper_sizes = ['tiny', 'small', 'medium', 'large-v3', 'turbo']
        size_info = {
            'tiny': 'Fastest, least accurate (~39 MB)',
            'small': 'Balanced speed/accuracy (~484 MB)',
            'medium': 'Default, good quality (~1.5 GB)',
            'large-v3': 'Best accuracy, high memory (~2.9 GB)',
            'turbo': 'Fast & accurate, v3 optimized (~809 MB)'
        }

        for size in whisper_sizes:
            model_path = os.path.join(cache_dir, f"models--Systran--faster-whisper-{size}")
            status = "✅ Cached" if os.path.exists(model_path) else "❌ Not cached"
            print(f"  {size:<8} - {size_info[size]:<35} {status}")

        print()
        print("Usage: python apps/audio.py <audio_file> [options]")
        print("Options:")
        print("  --model_size <size>      Whisper model size (tiny/small/medium/large-v3/turbo)")
        print("  --update                 Download missing models")
        sys.exit(0)

    # Set offline mode by default, unless --update is specified
    if not args.update:
        os.environ["HF_HUB_OFFLINE"] = "1"  # Force offline mode to use cached models

    # Set variables from parsed args
    audio_file = args.audio_file
    model_size = args.model_size

    # Handle update-only mode
    if args.update and not audio_file:
        print("Checking for model updates...")
    elif not audio_file:
        print("Error: Audio file required. Usage: python apps/audio.py <audio_file> [--model_size SIZE] [--update]")
        sys.exit(1)
    elif not os.path.exists(audio_file):
        print(f"Error: Audio file '{audio_file}' not found!")
        sys.exit(1)

    # ==================== SETUP ====================
    print("Torch version:", torch.__version__)
    print("CUDA available:", torch.cuda.is_available())
    if torch.cuda.is_available():
        print("GPU name:", torch.cuda.get_device_name(0))

    # Load diarization pipeline (from cache or prompt for token)
    print("\nLoading pyannote speaker diarization pipeline...")
    try:
        diarizer = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")
    except Exception as e:
        if "401" in str(e) or "403" in str(e) or "gated" in str(e).lower():
            print("\n" + "="*60)
            print("Model not cached. Hugging Face token required for first download.")
            print("Get your token at: https://hf.co/settings/tokens")
            print("Make sure you've accepted the model terms at:")
            print("  https://hf.co/pyannote/speaker-diarization-3.1")
            print("="*60)
            hf_token = input("\nEnter your Hugging Face token: ").strip()
            if not hf_token:
                print("Error: Token is required for first-time download.")
                sys.exit(1)
            print("Downloading model (this only needs to happen once)...")
            diarizer = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", token=hf_token)
            print("Model cached successfully! Token won't be needed again.")
        elif args.update and ("Temporary failure in name resolution" in str(e) or 
                              "Max retries exceeded" in str(e) or 
                              "Connection refused" in str(e) or
                              "Name resolution failure" in str(e) or
                              "MaxRetryError" in str(type(e))):
            print("\n" + "="*50)
            print("Network connection error while checking for updates.")
            print("This is expected if you're offline.")
            print("Using cached models - no updates downloaded.")
            print("Run with internet connection to check for updates.")
            print("="*50)
            # Try to load from cache
            try:
                diarizer = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")
            except Exception as cache_e:
                print(f"Error loading cached model: {cache_e}")
                sys.exit(1)
        else:
            raise e
    diarizer.to(torch.device("cuda"))

    # Load Whisper transcription model
    device = "cpu"
    compute_type = "int8"
    print(f"Loading Whisper {model_size} transcription model on {device}...")
    try:
        transcriber = WhisperModel(model_size, device=device, compute_type=compute_type)
    except Exception as e:
        if args.update and ("Temporary failure in name resolution" in str(e) or 
                            "Max retries exceeded" in str(e) or 
                            "Connection refused" in str(e) or
                            "Name resolution failure" in str(e) or
                            "MaxRetryError" in str(type(e))):
            print("\n" + "="*50)
            print("Network connection error while checking for Whisper updates.")
            print("This is expected if you're offline.")
            print("Using cached model - no updates downloaded.")
            print("Run with internet connection to check for updates.")
            print("="*50)
            transcriber = WhisperModel(model_size, device=device, compute_type=compute_type)
        else:
            raise e

    # If update-only mode, exit after loading models
    if args.update and not audio_file:
        print("Model update check complete! All models are loaded and ready.")
        sys.exit(0)

    # ==================== PROCESS AUDIO (CLI OUTPUT) ====================

    print(f"\nLoading audio: {audio_file}")

    print("Running diarization...")
    # Pass file path directly - pyannote handles loading internally
    diarization = diarizer(audio_file)

    # Get audio duration from waveform (more reliable than diarization extent for short audio)
    waveform_cli, sample_rate_cli = torchaudio.load(audio_file)
    duration_seconds = waveform_cli.shape[1] / sample_rate_cli
    del waveform_cli
    is_short_audio = duration_seconds <= 2.0
    duration = str(timedelta(seconds=max(1, int(duration_seconds))))
    print(f"Audio duration: {duration} ({duration_seconds:.2f} seconds)")

    # Clear GPU memory after diarization
    torch.cuda.empty_cache()

    # Note: Keeping diarizer in memory as its result is used later for speaker analysis

    # Build speaker map for timeline and alignment
    speaker_map = {}
    for turn, _, speaker in diarization.speaker_diarization.itertracks(yield_label=True):
        for t in range(int(turn.start * 10), int(turn.end * 10)):  # 100ms steps
            speaker_map[round(t / 10, 2)] = speaker

    # Create timeline visualization (for CLI display only)
    print("\nGenerating timeline visualization...")
    speaking_seconds = 0
    timeline = []
    if not is_short_audio:
        for t in range(0, max(1, int(duration_seconds))):
            has_speaker = any(speaker_map.get(round(sub_t / 10, 2), None)
                             for sub_t in range(t*10, (t+1)*10)
                             if speaker_map.get(round(sub_t / 10, 2), None) not in [None, "UNKNOWN"])
            timeline.append("x" if has_speaker else "_")
            if has_speaker:
                speaking_seconds += 1
    timeline_str = "".join(timeline)
    silence_percentage = ((duration_seconds - speaking_seconds) / duration_seconds * 100) if duration_seconds > 0 else 0
    print(f"Timeline (1 char = 1 sec): {timeline_str}")
    print(f"Speaking: {speaking_seconds}s ({100-silence_percentage:.1f}%) | Silence: {duration_seconds-speaking_seconds:.1f}s ({silence_percentage:.1f}%)")

    print("Running transcription...")
    try:
        task = "translate" if args.translate else "transcribe"
        segments, info = transcriber.transcribe(audio_file, beam_size=1, vad_filter=True, task=task)
    except RuntimeError as e:
        if "out of memory" in str(e).lower():
            print("GPU out of memory! Try using a smaller model (change model_size to 'small' or 'tiny') or set device='cpu'")
            raise e
        else:
            raise e

    torch.cuda.empty_cache()

    # ==================== ALIGN & PRINT ====================
    
    print("\n" + "="*60)
    print("SPEAKER-LABELED TRANSCRIPT")
    print("="*60)

    current_speaker = None
    for seg in segments:
        start = seg.start
        end = seg.end
        text = seg.text.strip()

        # Find dominant speaker in this segment
        times = range(int(start * 10), int(end * 10))
        speakers_in_seg = [speaker_map.get(round(t / 10, 2), "UNKNOWN") for t in times]
        seg_speaker = max(set(speakers_in_seg), key=speakers_in_seg.count) if speakers_in_seg else "UNKNOWN"

        if seg_speaker != current_speaker:
            timestamp = str(timedelta(seconds=int(start)))
            print(f"\n[{timestamp}] {seg_speaker}:")
            current_speaker = seg_speaker

        start_time = str(timedelta(seconds=int(start)))
        end_time = str(timedelta(seconds=int(end)))
        print(f"[{start_time} - {end_time}] {text}")

    if args.translate:
        print(f"\nTranslated from: {info.language} → en")
    else:
        print(f"\nTranscription language: {info.language}")

    # Clean up models
    del diarizer
    del transcriber
    torch.cuda.empty_cache()

    print("\nProcessing complete!")


if __name__ == "__main__":
    main()