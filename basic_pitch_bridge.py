"""Basic Pitch subprocess bridge.

The bridge keeps Basic Pitch / ONNX model loading outside the Qt process so
heavy initialization cannot freeze the transparent overlay. Communication is
newline-delimited JSON over stdin/stdout; audio payloads are base64-encoded
float32 PCM.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import io
import json
import logging
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

from note_model import NoteEvent, filter_and_merge, suppress_weak_harmonics


def send(message: dict) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-rate", type=int, required=True)
    parser.add_argument("--chunk-seconds", type=float, required=True)
    parser.add_argument("--min-amp", type=float, required=True)
    parser.add_argument("--min-confidence", type=float, required=True)
    parser.add_argument("--min-velocity", type=int, required=True)
    return parser.parse_args()


def write_wav(audio: np.ndarray, sample_rate: int) -> Path:
    pcm = np.clip(audio, -1.0, 1.0)
    pcm = (pcm * 32767).astype("<i2", copy=False)
    handle = tempfile.NamedTemporaryFile(
        prefix="piano-shadow-basic-", suffix=".wav", delete=False
    )
    path = Path(handle.name)
    handle.close()
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())
    return path


def run() -> int:
    args = parse_args()
    previous_logging_level = logging.root.manager.disable
    logging.disable(logging.WARNING)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            from basic_pitch import ICASSP_2022_MODEL_PATH
            from basic_pitch.inference import Model, predict

            model = Model(ICASSP_2022_MODEL_PATH)
    except Exception as exc:
        send({"type": "error", "message": f"Basic Pitch 初始化失败：{exc}"})
        return 2
    finally:
        logging.disable(previous_logging_level)

    context_seconds = max(1.5, min(2.5, args.chunk_seconds * 4))
    hop_seconds = max(0.25, min(0.75, args.chunk_seconds))
    context_frames = round(args.sample_rate * context_seconds)
    hop_frames = round(args.sample_rate * hop_seconds)
    recent_frames = round(args.sample_rate * 0.25)
    rolling = np.empty(0, dtype=np.float32)
    frames_since_inference = 0
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
            frames_since_inference += chunk.size
            rolling = np.concatenate((rolling, chunk))[-context_frames:]
            if rolling.size < context_frames or frames_since_inference < hop_frames:
                continue
            advanced_frames = frames_since_inference
            frames_since_inference = 0
            audio = np.ascontiguousarray(rolling)
            rms = float(
                np.sqrt(
                    np.mean(np.square(audio[-recent_frames:]), dtype=np.float64)
                )
            )
            if rms < args.min_amp:
                send({"type": "status", "message": "Listening · 等待清晰的旋律…"})
                continue
            wav_path = write_wav(audio, args.sample_rate)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    _, _, raw_notes = predict(
                        str(wav_path),
                        model,
                        onset_threshold=max(0.58, args.min_confidence),
                        frame_threshold=max(0.38, args.min_confidence * 0.78),
                        minimum_note_length=90,
                        melodia_trick=False,
                    )
            finally:
                wav_path.unlink(missing_ok=True)
            advanced_seconds = advanced_frames / args.sample_rate
            cutoff = (
                0.0
                if first_window
                else max(0.0, context_seconds - advanced_seconds - 0.12)
            )
            window_start = stream_frames / args.sample_rate - context_seconds
            events: list[NoteEvent] = []
            for start, end, pitch, amplitude, *_ in raw_notes:
                onset = float(start)
                if onset < cutoff:
                    continue
                midi = int(pitch)
                absolute_onset = window_start + onset
                if absolute_onset - last_onsets.get(midi, -1e9) < 0.14:
                    continue
                last_onsets[midi] = absolute_onset
                events.append(
                    NoteEvent(
                        midi=midi,
                        start=max(0.0, onset - cutoff),
                        end=max(0.0, float(end) - cutoff),
                        velocity=max(1, min(127, round(float(amplitude) * 127))),
                        confidence=float(amplitude),
                    )
                )
            first_window = False
            stale_before = window_start - 1.0
            last_onsets = {
                midi: onset for midi, onset in last_onsets.items() if onset >= stale_before
            }
            notes = filter_and_merge(
                events, args.min_confidence, args.min_velocity
            )
            notes = suppress_weak_harmonics(notes)
            if notes:
                send(
                    {
                        "type": "notes",
                        "notes": [
                            {
                                "midi": note.midi,
                                "start": note.start,
                                "end": note.end,
                                "velocity": note.velocity,
                                "confidence": note.confidence,
                            }
                            for note in notes
                        ],
                    }
                )
                send({"type": "status", "message": "Listening · Melody detected"})
        except Exception as exc:
            send({"type": "warning", "message": f"Basic Pitch 推理暂时失败：{exc}"})
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
