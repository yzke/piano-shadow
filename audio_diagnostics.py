"""Local diagnostics for capture devices and the Basic Pitch model."""

from __future__ import annotations

import argparse
import contextlib
import io
import logging
import math
import tempfile
import time
import wave
from pathlib import Path

import numpy as np


def inspect_devices(record_seconds: float) -> bool:
    import soundcard as sc

    speaker = sc.default_speaker()
    print(f"Default speaker: {speaker}")
    microphones = sc.all_microphones(include_loopback=True)
    print("Capture/loopback devices:")
    for index, microphone in enumerate(microphones):
        # Some virtual WASAPI devices expose malformed channel metadata and
        # SoundCard.__repr__ asserts while reading it. Name/id remain safe.
        print(f"  [{index}] name={microphone.name!r}, id={microphone.id!r}")
    if speaker is None:
        print("ERROR: no default speaker")
        return False

    loopback = sc.get_microphone(id=str(speaker.id), include_loopback=True)
    if loopback is None:
        print("ERROR: no WASAPI loopback for the default speaker")
        return False
    print(f"Selected loopback: {loopback}")

    if record_seconds > 0:
        frames = round(22050 * record_seconds)
        print(f"Recording {record_seconds:g}s from loopback...")
        with loopback.recorder(samplerate=22050, channels=2, blocksize=2048) as recorder:
            audio = np.asarray(recorder.record(numframes=frames), dtype=np.float32)
        rms = float(np.sqrt(np.mean(np.square(audio), dtype=np.float64)))
        peak = float(np.max(np.abs(audio)))
        print(f"Captured shape={audio.shape}, RMS={rms:.6f}, peak={peak:.6f}")
        if rms < 0.0001:
            print("WARNING: loopback is available but currently silent")
    return True


def inspect_model() -> bool:
    previous_logging_level = logging.root.manager.disable
    logging.disable(logging.WARNING)
    try:
        from basic_pitch import ICASSP_2022_MODEL_PATH
        from basic_pitch.inference import Model, predict
    finally:
        logging.disable(previous_logging_level)

    sample_rate = 22050
    duration = 2.5
    count = round(sample_rate * duration)
    times = np.arange(count, dtype=np.float32) / sample_rate
    fade = np.minimum(np.minimum(times / 0.08, (duration - times) / 0.15), 1.0)
    audio = sum(
        np.sin(2 * math.pi * frequency * times)
        for frequency in (261.6256, 329.6276, 391.9954)
    )
    audio = (audio / 3 * fade * 0.35).astype(np.float32)

    handle = tempfile.NamedTemporaryFile(prefix="piano-shadow-test-", suffix=".wav", delete=False)
    path = Path(handle.name)
    handle.close()
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm.tobytes())
    try:
        print("Running Basic Pitch synthetic C-major test...")
        load_started = time.perf_counter()
        model = Model(ICASSP_2022_MODEL_PATH)
        load_seconds = time.perf_counter() - load_started
        timings: list[float] = []
        events = []
        for _ in range(2):
            started = time.perf_counter()
            with contextlib.redirect_stdout(io.StringIO()):
                _, _, events = predict(str(path), model)
            timings.append(time.perf_counter() - started)
        pitches = sorted({int(event[2]) for event in events})
        print(f"Detected MIDI pitches: {pitches}")
        print(
            f"Model load={load_seconds:.3f}s, "
            f"first inference={timings[0]:.3f}s, reused inference={timings[1]:.3f}s"
        )
        expected = {60, 64, 67}
        found = expected.intersection(pitches)
        if len(found) < 2:
            print(f"WARNING: expected at least two of {sorted(expected)}, found {sorted(found)}")
            return False
        print("Basic Pitch model: OK")
        return True
    finally:
        path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Piano Shadow local audio diagnostics")
    parser.add_argument("--record", type=float, default=0, metavar="SECONDS")
    parser.add_argument("--model", action="store_true")
    args = parser.parse_args()
    device_ok = inspect_devices(max(0, args.record))
    model_ok = inspect_model() if args.model else True
    return 0 if device_ok and model_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
