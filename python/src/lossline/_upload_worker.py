"""The upload worker: a child process that makes the Hugging Face calls for BucketSync.

Uploads run here instead of on a thread of the training process because a Python thread
cannot be cancelled: an HTTP or hf_xet call that hangs would block that thread for good,
and the run would look stalled. A process can be killed, so the parent gives each call a
deadline and, on timeout, kills the worker and starts a fresh one. A killed worker also
cannot finish an old upload later and overwrite newer files.

Protocol on stdin/stdout: length-prefixed pickles, one reply per request.
  ("batch", bucket_id, [(bytes, remote_path), ...])  ->  ("ok", None)
  ("ensure", bucket_id)                               ->  ("ok", created: bool)
  failures                                            ->  ("err", type_name, message, status, headers)
"""

from __future__ import annotations

import pickle
import struct
import sys
from typing import IO, Any

_HEADER = struct.Struct(">Q")


def send(stream: IO[bytes], obj: Any) -> None:
    data = pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
    stream.write(_HEADER.pack(len(data)) + data)
    stream.flush()


def recv(stream: IO[bytes]) -> Any:
    """The next message, or None at end of stream."""
    head = stream.read(_HEADER.size)
    if len(head) < _HEADER.size:
        return None
    (size,) = _HEADER.unpack(head)
    data = stream.read(size)
    if len(data) < size:
        return None
    return pickle.loads(data)


def error_reply(exc: BaseException) -> tuple[Any, ...]:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or {}
    keep = {k: headers.get(k) for k in ("retry-after", "ratelimit") if headers.get(k)}
    return ("err", type(exc).__name__, str(exc), getattr(response, "status_code", None), keep)


def main() -> None:
    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    sys.stdout = sys.stderr  # stray prints must not corrupt the reply pipe

    from huggingface_hub import HfApi

    from .upload import ensure_bucket, quiet_progress_bars, reset_xet_session

    api = HfApi()  # HF_TOKEN from the parent's environment, or the local login
    while (request := recv(stdin)) is not None:
        try:
            if request[0] == "batch":
                _, bucket_id, add = request
                with quiet_progress_bars():
                    api.batch_bucket_files(bucket_id, add=add)
                send(stdout, ("ok", None))
            elif request[0] == "ensure":
                send(stdout, ("ok", ensure_bucket(api, request[1])))
            else:
                send(stdout, ("err", "ValueError", f"unknown request {request[0]!r}", None, {}))
        except Exception as exc:
            reset_xet_session()
            send(stdout, error_reply(exc))


if __name__ == "__main__":
    main()
