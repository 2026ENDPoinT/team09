"""Explicit download step, separate from recognition; no user audio is transmitted."""
import argparse
from faster_whisper.utils import download_model

parser = argparse.ArgumentParser()
parser.add_argument("--model", choices=["tiny", "small", "medium", "large-v3", "large-v3-turbo"], default="small")
args = parser.parse_args()
print(download_model(args.model, output_dir="models/whisper-" + args.model))
