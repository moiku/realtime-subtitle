import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import sys
import signal
import threading
import queue
import time
from concurrent.futures import ThreadPoolExecutor
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSignal, QTimer

from audio_capture import AudioCapture
from transcriber import Transcriber
from translator import Translator
from overlay_window import OverlayWindow
from config import config
from glossary import load_glossary
from session_logger import SessionLogger

class WorkerSignals(QObject):
    update_text = pyqtSignal(int, str, str)  # (chunk_id, original, translated)

class Pipeline(QObject):
    def __init__(self, audio=None):
        super().__init__()
        self.signals = WorkerSignals()
        self.running = True
        self.logger = None
        
        # Print config for debugging
        config.print_config()
        
        # Initialize components (an alternative audio source can be injected, e.g. a file for simulation)
        self.audio = audio or AudioCapture(
            device_index=config.device_index,
            sample_rate=config.sample_rate,
            silence_threshold=config.silence_threshold,
            silence_duration=config.silence_duration,
            chunk_duration=config.chunk_duration,
            max_phrase_duration=config.max_phrase_duration,
            streaming_mode=config.streaming_mode,
            streaming_interval=config.streaming_interval,
            streaming_step_size=config.streaming_step_size,
            streaming_overlap=config.streaming_overlap
        )
        
        # Initialize Transcriber
        print(f"[Pipeline] Initializing Transcriber with backend={config.asr_backend}, device={config.whisper_device}...")
        
        # Determine model size based on backend
        if config.asr_backend == "funasr":
            model_size = config.funasr_model
        else:
            model_size = config.whisper_model
            
        self.transcriber = Transcriber(
            backend=config.asr_backend,
            model_size=model_size,
            device=config.whisper_device,
            compute_type=config.whisper_compute_type,
            language=config.source_language
        )
        
        # Glossary: terms go to the translator, a short hint list biases ASR via initial_prompt
        self.glossary = load_glossary(config.glossary_files)
        self.glossary.add_slide_hints(config.slide_files)
        self.asr_hints = self.glossary.asr_prompt()
        
        # Initialize Translator
        print(f"[Pipeline] Initializing Translator (target={config.target_lang})...")
        self.translator = Translator(
            target_lang=config.target_lang,
            base_url=config.api_base_url,
            api_key=config.api_key,
            model=config.model,
            glossary=self.glossary,
            domain=config.domain,
            context_size=config.context_size
        )
        
        # Warmup Transcriber (Critical for MLX/GPU)
        self.transcriber.warmup()

    def start(self):
        """Start the processing pipeline in a dedicated thread"""
        # self.audio.start() # DISABLE: Generator manages its own stream. calling this causes double-stream error on macOS
        self.logger = SessionLogger(
            config.log_dir, self.audio.sample_rate, save_audio=config.save_audio,
            meta={"asr_backend": config.asr_backend, "whisper_model": config.whisper_model,
                  "source_language": config.source_language, "translation_model": config.model,
                  "target_lang": config.target_lang, "glossary_files": config.glossary_files,
                  "glossary_terms": len(self.glossary.terms)})
        self.thread = threading.Thread(target=self.processing_loop)
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        print("\n[Pipeline] Stopping...")
        self.running = False
        self.audio.stop()
        if self.thread.is_alive():
            self.thread.join(timeout=2)
        if self.logger:
            self.logger.close()
        print("[Pipeline] Stopped.")

    def processing_loop(self):
        """Fully parallel pipeline: multiple concurrent transcription + translation"""
        print("Pipeline processing loop started (FULLY PARALLEL mode).")
        
        # Create multiple transcribers for concurrent processing
        # CHECK: If using MLX, force 1 worker (MLX is not thread-safe for parallel inference in this way)
        is_mlx = (config.asr_backend == "mlx")
        
        if is_mlx:
            print("[Pipeline] MLX backend detected - forcing single worker (MLX uses GPU parallelism internaly)")
            num_transcription_workers = 1
        else:
            num_transcription_workers = config.transcription_workers
            
        print(f"[Pipeline] Using {num_transcription_workers} transcription workers...")
        
        # Determine model size based on backend
        if config.asr_backend == "funasr":
            model_size = config.funasr_model
        else:
            model_size = config.whisper_model
        
        transcribers = [self.transcriber]  # Reuse existing one
        for i in range(num_transcription_workers - 1):
            t = Transcriber(
                backend=config.asr_backend,
                model_size=model_size,
                device=config.whisper_device,
                compute_type=config.whisper_compute_type,
                language=config.source_language
            )
            transcribers.append(t)
        """Accumulating Buffer Processing Loop (Word-by-Word Streaming)"""
        print("[Pipeline] processing loop started (Accumulating Mode).")
        
        import numpy as np
        
        # Executors
        transcribe_executor = ThreadPoolExecutor(max_workers=1) # Serial transcription
        # Single translation thread: segments are translated in order so the context is correct
        translate_executor = ThreadPoolExecutor(max_workers=1)
        self.translate_executor = translate_executor
        
        # State
        buffer = np.array([], dtype=np.float32)
        chunk_id = 1
        last_update_time = time.time()
        phrase_start_time = time.time()
        total_samples = 0          # samples consumed so far (session clock)
        buffer_start_sample = 0    # session position of buffer[0]
        
        # Generator yielding small chunks (e.g. 0.2s)
        audio_gen = self.audio.generator()
        
        # Context Management
        self.last_final_text = ""

        try:
            for audio_chunk in audio_gen:
                if not self.running:
                    break
                if len(buffer) == 0:
                    buffer_start_sample = total_samples
                buffer = np.concatenate([buffer, audio_chunk])
                total_samples += len(audio_chunk)
                if self.logger:
                    self.logger.write_audio(audio_chunk)
                now = time.time()
                buffer_duration = len(buffer) / self.audio.sample_rate
                
                # Segmentation. The lecturer often pauses inside a phrase (even inside a word:
                # 確率…関数), so short buffers are only cut on a long pause and are otherwise
                # merged with what follows; ASR on the merged audio recovers the split word.
                def tail_silent(sec):
                    n = int(self.audio.sample_rate * sec)
                    return len(buffer) > n and np.sqrt(np.mean(buffer[-n:]**2)) < self.audio.silence_threshold
                
                # 1. Short buffer: cut only on a long pause
                long_pause_cut = buffer_duration > 1.0 and tail_silent(config.long_silence_duration)
                # 2. Standard: long enough AND a normal pause
                standard_cut = buffer_duration > config.segment_min_duration and tail_silent(config.silence_duration)
                # 3. Soft limit: take any brief pause to avoid huge latency
                soft_limit_cut = buffer_duration > config.segment_soft_limit and tail_silent(0.3)
                # 4. Hard limit: force cut
                hard_limit_cut = (buffer_duration > self.audio.max_phrase_duration)
                standard_cut = standard_cut or long_pause_cut

                should_finalize = standard_cut or soft_limit_cut or hard_limit_cut
                
                if should_finalize and buffer_duration > 0.5:
                    # FINALIZE
                    final_buffer = buffer.copy()
                    cid = chunk_id
                    
                    # Store current prompt to pass to task (thread safety)
                    prompt = self._asr_prompt()
                    span = (buffer_start_sample / self.audio.sample_rate, total_samples / self.audio.sample_rate)
                    
                    # PRE-CHECK: Is the entire buffer actually silence?
                    # (Prevent infinite loop of repeating prompt on empty audio)
                    overall_rms = np.sqrt(np.mean(final_buffer**2))
                    if overall_rms < self.audio.silence_threshold:
                         print(f"[Pipeline] Skipped silent chunk {cid} (RMS={overall_rms:.4f})")
                    else:
                        # Submit Final Task
                        # Pass prompt AND translate_executor for async translation
                        transcribe_executor.submit(self._process_final_chunk, final_buffer, cid, prompt, translate_executor, span)
                    
                    # Reset
                    buffer = np.array([], dtype=np.float32)
                    chunk_id += 1
                    phrase_start_time = now
                    last_update_time = now
                    
                # 2. Partial Update if: Interval passed AND not finalizing
                elif now - last_update_time > config.update_interval and buffer_duration > 0.5:
                    # PARTIAL UPDATE
                    partial_buffer = buffer.copy()
                    prompt = self._asr_prompt()
                    
                    # RMS Check to avoid partial hallucination on silence
                    rms = np.sqrt(np.mean(partial_buffer**2))
                    if rms > self.audio.silence_threshold:
                        transcribe_executor.submit(self._process_partial_chunk, partial_buffer, chunk_id, prompt)
                    
                    last_update_time = now
                    
        except Exception as e:
            print(f"[Pipeline] Error in loop: {e}")
        finally:
            # If the source ended by itself (e.g. a file in simulate.py), finish pending work in order
            drain = self.running
            transcribe_executor.shutdown(wait=drain)
            translate_executor.shutdown(wait=drain)

    def _asr_prompt(self):
        """Glossary hints first, then the previous sentence (Whisper keeps the tail of long prompts)"""
        parts = [p for p in (self.asr_hints, self.last_final_text) if p]
        return "。".join(parts)

    def _process_partial_chunk(self, audio_data, chunk_id, prompt=""):
        """Transcribe and update UI (No translation)"""
        try:
            # Use accumulated context as prompt
            text = self.transcriber.transcribe(audio_data, prompt=prompt)
            if text:
                self.signals.update_text.emit(chunk_id, text, "")
        except Exception as e:
            print(f"[Partial {chunk_id}] Error: {e}")

    def _process_final_chunk(self, audio_data, chunk_id, prompt="", translate_executor=None, span=(0.0, 0.0)):
        """Transcribe, Log, and Trigger Translation Async"""
        try:
            t0 = time.time()
            text = self.transcriber.transcribe(audio_data, prompt=prompt)
            asr_sec = time.time() - t0
            if text:
                print(f"[Final {chunk_id}] Transcribed: {text}")
                # Save for context (only if meaningful)
                # (Japanese has no spaces, so count characters as well as words)
                if len(text.split()) > 2 or len(text) > 10:
                    self.last_final_text = text
                
                # Emit final transcription first (confirms text)
                self.signals.update_text.emit(chunk_id, text, "(translating...)")
                
                # Offload translation to separate thread so we don't block next transcription
                if translate_executor:
                    translate_executor.submit(self._run_translation, text, chunk_id, span, asr_sec)
            else:
                pass
        except Exception as e:
            print(f"[Final {chunk_id}] Error: {e}")

    def _run_translation(self, text, chunk_id, span=(0.0, 0.0), asr_sec=0.0):
        """Run translation in background, emit result and log the segment"""
        t0 = time.time()
        try:
            translated = self.translator.translate(text)
            print(f"[Final {chunk_id}] Translated: {translated}")
            self.signals.update_text.emit(chunk_id, text, translated or "…")
        except Exception as e:
            print(f"[Translation {chunk_id}] Failed: {e}")
            translated = None
            self.signals.update_text.emit(chunk_id, text, "[Translation Failed]")
        if self.logger:
            self.logger.write_segment(id=chunk_id, start=round(span[0], 2), end=round(span[1], 2),
                                      ja=text, en=translated, asr_sec=round(asr_sec, 2),
                                      mt_sec=round(time.time() - t0, 2),
                                      wall=time.strftime("%H:%M:%S"))
    
    def _transcribe_chunk(self, transcriber, audio_chunk, chunk_id):
        """Transcribe a single chunk and log timing"""
        t0 = time.time()
        text = transcriber.transcribe(audio_chunk)
        t1 = time.time()
        print(f"[Chunk {chunk_id}] Transcribed in {t1-t0:.2f}s: {text if text else '(empty)'}")
        return text
    
    def _translate_and_log(self, text, chunk_id=0):
        """Translate text and log result"""
        t0 = time.time()
        translated_text = self.translator.translate(text)
        t1 = time.time()
        print(f"[Chunk {chunk_id}] Translated in {t1-t0:.2f}s: {translated_text}")
        return (text, translated_text)

# Global reference for signal handler
_pipeline = None
_app = None

def signal_handler(sig, frame):
    """Handle Ctrl-C gracefully"""
    print("\n[Main] Ctrl-C received, force killing...")
    os._exit(0)

def start_overlay_session():
    """Start the overlay and pipeline without blocking (for use in Dashboard)"""
    global _pipeline, _app
    
    # Initialize Overlay Window
    window = OverlayWindow(
        display_duration=config.display_duration,
        window_width=config.window_width
    )
    window.show()
    
    # Logic
    _pipeline = Pipeline()
    
    # Connect signals
    _pipeline.signals.update_text.connect(window.update_text)
    
    # Start pipeline
    _pipeline.start()
    
    return window, _pipeline

def main():
    global _pipeline, _app
    
    # Set up signal handler for Ctrl-C
    signal.signal(signal.SIGINT, signal_handler)
    
    _app = QApplication.instance()
    if not _app:
        _app = QApplication(sys.argv)
    
    # Start session
    win, pipe = start_overlay_session()
    
    # Timer to let Python interpreter handle signals (Ctrl-C)
    timer = QTimer()
    timer.start(200)
    timer.timeout.connect(lambda: None)
    
    try:
        sys.exit(_app.exec())
    except SystemExit:
        pass
    finally:
        if _pipeline:
            _pipeline.stop()

if __name__ == "__main__":
    main()
