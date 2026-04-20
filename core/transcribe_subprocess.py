# core/transcribe_subprocess.py
import sys
import json
import os
import io

# Forza codifica UTF-8 per la comunicazione console su Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Variabili d'ambiente di sicurezza applicate al sottoprocesso
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["CT2_USE_EXPERIMENTAL_PACKED_GEMM"] = "0"

def _emit(msg_dict):
    """Invia un messaggio JSON al processo padre e svuota il buffer."""
    print(json.dumps(msg_dict, ensure_ascii=False), flush=True)

def main():
    try:
        config_path = sys.argv[1]
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)

        audio_path = cfg["audio_path"]
        model_dir = cfg["model_dir"]
        model_name = cfg["model_name"]
        language = cfg.get("language")
        custom_words = cfg.get("custom_words", [])
        output_file = cfg["output_file"]
        
        initial_prompt = ", ".join(custom_words) if custom_words else None

        _emit({"type": "status", "msg": f"Caricamento modello {model_name} in memoria isolata..."})

        # Il caricamento ora avviene in totale isolamento
        from faster_whisper import WhisperModel
        model = WhisperModel(
            os.path.join(model_dir, model_name),
            device="cpu",
            compute_type="int8",
            cpu_threads=2, # Sicuro su CPU Xeon
            download_root=model_dir
        )
        
        _emit({"type": "progress", "val": 20})
        _emit({"type": "status", "msg": "Modello caricato. Inizio trascrizione..."})
        
        segments_iter, info = model.transcribe(
            audio_path,
            language=language if language != "auto" else None,
            initial_prompt=initial_prompt,
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        
        duration = info.duration if info.duration else 1.0
        final_segments = []

        for seg in segments_iter:
            pct = min(95, 20 + int((seg.end / duration) * 75))
            _emit({
                "type": "segment", 
                "text": seg.text, 
                "start": seg.start, 
                "end": seg.end,
                "pct": pct
            })
            final_segments.append({"text": seg.text, "start": seg.start, "end": seg.end})

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(final_segments, f, ensure_ascii=False)
            
        _emit({"type": "done"})

    except Exception as e:
        _emit({"type": "error", "msg": str(e)})
        sys.exit(1)

if __name__ == "__main__":
    main()
