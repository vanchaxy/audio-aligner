import os
from multiprocessing.sharedctypes import SynchronizedArray

import click
import numpy as np
from librosa import feature, onset  # type: ignore[attr-defined]
from scipy.signal import correlate

shared_ref: np.ndarray | SynchronizedArray | None = None
shared_sec: np.ndarray | SynchronizedArray | None = None


def share_arrays(
    ref_: np.ndarray | SynchronizedArray,
    sec_: np.ndarray | SynchronizedArray,
) -> None:
    global shared_ref, shared_sec
    shared_ref = ref_
    shared_sec = sec_


def get_chunks(
    reference_y: np.ndarray,
    secondary_y: np.ndarray,
    chunk_duration: int,
    sample_rate: int,
) -> list[dict]:
    samples_per_chunk = int(chunk_duration * sample_rate)
    chunk_tasks = []
    min_len = min(len(reference_y), len(secondary_y))
    current_pos = 0
    chunk_idx = 0
    while current_pos < min_len:
        start_sample = current_pos
        end_sample = current_pos + samples_per_chunk
        actual_end_sample = min(end_sample, min_len)

        # A very tiny last chunk might not give good correlation.
        # don't process if less than 1/4th
        min_practical_chunk_samples = samples_per_chunk // 4
        if (actual_end_sample - start_sample) < min_practical_chunk_samples and chunk_idx > 0:
            break

        chunk_tasks.append(
            {
                'chunk_idx': chunk_idx,
                'start': start_sample,
                'end': actual_end_sample,
            },
        )
        current_pos = end_sample
        chunk_idx += 1
    return chunk_tasks


def process_single_chunk(
    task_args: tuple[int, str, dict],
) -> tuple[int, int] | None:
    sr, method_name, task_info = task_args

    if shared_ref is None or shared_sec is None:
        raise RuntimeError('shared_ref and shared_sec must be set')

    if isinstance(shared_ref, np.ndarray):
        y_ref_full_data = shared_ref
    else:
        y_ref_full_data = np.frombuffer(shared_ref.get_obj(), dtype=np.float32)

    if isinstance(shared_sec, np.ndarray):
        y_sec_full_data = shared_sec
    else:
        y_sec_full_data = np.frombuffer(shared_sec.get_obj(), dtype=np.float32)

    y_ref_chunk = y_ref_full_data[task_info['start'] : task_info['end']]
    y_sec_chunk = y_sec_full_data[task_info['start'] : task_info['end']]

    try:
        hop_length = int(sr / 1000) + 1
        frame_length = hop_length * 12

        if method_name == 'rms':
            y_ref_feat = feature.rms(
                y=y_ref_chunk,
                frame_length=frame_length,
                hop_length=hop_length,
            )[0]
            y_sec_feat = feature.rms(
                y=y_sec_chunk,
                frame_length=frame_length,
                hop_length=hop_length,
            )[0]
        elif method_name == 'onset':
            y_ref_feat = onset.onset_strength(y=y_ref_chunk, sr=sr, hop_length=hop_length)
            y_sec_feat = onset.onset_strength(y=y_sec_chunk, sr=sr, hop_length=hop_length)
        else:
            raise ValueError("Unsupported method. Choose 'rms' or 'onset'.")

        y_ref_feat = (y_ref_feat - np.mean(y_ref_feat)) / np.std(y_ref_feat)
        y_sec_feat = (y_sec_feat - np.mean(y_sec_feat)) / np.std(y_sec_feat)

        correlation = correlate(y_ref_feat, y_sec_feat, mode='full')
        lags = np.arange(-len(y_sec_feat) + 1, len(y_ref_feat))

        delay_frames = lags[np.argmax(correlation)]
        delay_seconds = delay_frames * hop_length / sr
        return task_info['chunk_idx'], int(delay_seconds * 1000)
    except Exception as e:
        click.echo(
            click.style(
                f'Worker (PID {os.getpid()}) Error in chunk {task_info["chunk_idx"]}: {e}',
                fg='red',
            ),
            err=True,
        )
        return None
