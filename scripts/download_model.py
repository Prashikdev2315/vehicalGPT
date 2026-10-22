"""Download and verify Qwen2.5-1.5B-Instruct GGUF model."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys

MODEL_REPO = "Qwen/Qwen2.5-1.5B-Instruct-GGUF"
MODEL_FILENAME = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
EXPECTED_SHA256 = "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e"
EXPECTED_SIZE = 1117320736


def verify_checksum(file_path: Path, expected_sha256: str) -> bool:
    """Compute and verify file SHA-256 checksum."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    digest = h.hexdigest()
    return digest.lower() == expected_sha256.lower()


def download_model(dest_dir: Path | str = "models", verify: bool = True) -> Path:
    """Download GGUF model from Hugging Face Hub and verify checksum."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    target_path = dest / MODEL_FILENAME

    if target_path.exists():
        actual_size = target_path.stat().st_size
        if actual_size == EXPECTED_SIZE:
            print(f"Model file already exists at {target_path} ({actual_size:,} bytes).")
            if verify:
                print("Verifying SHA-256 checksum...")
                if verify_checksum(target_path, EXPECTED_SHA256):
                    print("[OK] Checksum verified.")
                    return target_path
                else:
                    print("Checksum mismatch! Re-downloading...")
            else:
                return target_path

    print(f"Downloading {MODEL_FILENAME} from {MODEL_REPO}...")
    try:
        from huggingface_hub import hf_hub_download
        downloaded = hf_hub_download(
            repo_id=MODEL_REPO,
            filename=MODEL_FILENAME,
            local_dir=str(dest),
        )
        downloaded_path = Path(downloaded)
        print(f"Downloaded to: {downloaded_path}")
        if verify:
            print("Verifying SHA-256 checksum...")
            if not verify_checksum(downloaded_path, EXPECTED_SHA256):
                raise ValueError("Downloaded file checksum does not match expected SHA-256!")
            print("[OK] Checksum verified successfully.")
        return downloaded_path
    except Exception as e:
        print(f"Failed to download model: {e}", file=sys.stderr)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Download Qwen2.5-1.5B GGUF Model")
    parser.add_argument("--dest", default="models", help="Destination folder")
    parser.add_argument("--no-verify", action="store_true", help="Skip SHA-256 verification")
    args = parser.parse_args()

    path = download_model(dest_dir=args.dest, verify=not args.no_verify)
    print(f"Model ready at: {path}")


if __name__ == "__main__":
    main()
