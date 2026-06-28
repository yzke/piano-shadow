"""GPU transcription subprocess used by the frozen Windows application.

The bridge runs inside Piano Shadow's optional source virtual environment,
where CUDA PyTorch is installed. Communication is newline-delimited JSON over
stdin/stdout; audio payloads are base64-encoded float32 PCM.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import io
import json
import sys

import numpy as np


def send(message: dict) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--sample-rate", type=int, required=True)
    parser.add_argument("--min-amp", type=float, required=True)
    parser.add_argument("--min-velocity", type=int, required=True)
    return parser.parse_args()


def resample(audio: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate:
        return np.ascontiguousarray(audio, dtype=np.float32)
    from scipy.signal import resample_poly

    divisor = np.gcd(source_rate, target_rate)
    output = resample_poly(audio, target_rate // divisor, source_rate // divisor)
    return np.ascontiguousarray(output, dtype=np.float32)


def run() -> int:
    args = parse_args()
    try:
        import torch
        from piano_transcription_inference import PianoTranscription, sample_rate

        if not torch.cuda.is_available():
            raise RuntimeError("torch.cuda.is_available() returned False")
        with contextlib.redirect_stdout(io.StringIO()):
            transcriptor = PianoTranscription(
                device="cuda",
                segment_samples=sample_rate * 2,
                checkpoint_path=args.model,
            )
        if hasattr(transcriptor.model, "module") and torch.cuda.device_count() == 1:
            transcriptor.model = transcriptor.model.module
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
    except Exception as exc:
        send({"type": "error", "message": f"GPU 初始化失败：{exc}"})
        return 2

    context_seconds = 2.0
    context_frames = round(args.sample_rate * context_seconds)
    recent_frames = round(args.sample_rate * 0.1)
    rolling = np.empty(0, dtype=np.float32)
    stream_frames = 0
    first_window = True
    last_onsets: dict[int, float] = {}
    send({"type": "ready"})

    for line in sys.stdin:
        try:
            message = json.loads(line)
            if message.get("type") == "stop":
                return 0
            encoded = message.get("audio")
            if not encoded:
                continue
            chunk = np.frombuffer(base64.b64decode(encoded), dtype="<f4").copy()
            stream_frames += chunk.size
            rolling = np.concatenate((rolling, chunk))[-context_frames:]
            if rolling.size < context_frames:
                continue
            rms = float(
                np.sqrt(
                    np.mean(np.square(rolling[-recent_frames:]), dtype=np.float64)
                )
            )
            if rms < args.min_amp:
                continue
            model_audio = resample(rolling, args.sample_rate, sample_rate)
            with contextlib.redirect_stdout(io.StringIO()):
                result = transcriptor.transcribe(model_audio, None)
            raw_events = result.get("est_note_events", [])
            cutoff = 0.0 if first_window else context_seconds - 0.20
            window_start = stream_frames / args.sample_rate - context_seconds
            notes = []
            for event in raw_events:
                onset = float(event["onset_time"])
                if onset < cutoff:
                    continue
                midi = int(event["midi_note"])
                velocity = int(event.get("velocity", 90))
                if not 21 <= midi <= 108 or velocity < args.min_velocity:
                    continue
                absolute_onset = window_start + onset
                if absolute_onset - last_onsets.get(midi, -1e9) < 0.14:
                    continue
                last_onsets[midi] = absolute_onset
                notes.append(
                    {
                        "midi": midi,
                        "start": max(0.0, onset - cutoff),
                        "end": max(
                            0.0, float(event["offset_time"]) - cutoff
                        ),
                        "velocity": velocity,
                        "confidence": 1.0,
                    }
                )
            first_window = False
            stale_before = window_start - 1.0
            last_onsets = {
                midi: onset
                for midi, onset in last_onsets.items()
                if onset >= stale_before
            }
            if notes:
                notes.sort(key=lambda note: note["start"])
                send({"type": "notes", "notes": notes})
        except Exception as exc:
            send({"type": "warning", "message": f"GPU 推理暂时失败：{exc}"})
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
