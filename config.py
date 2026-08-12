import os

MODEL_NAME = "Goedel-LM/Goedel-Prover-SFT"
DATASET_NAME = "liuchengwu/FormalStep"
DATASET_SPLIT = "train"
NUM_SAMPLES = 50
NUM_TRAJECTORIES = 10
MAX_NEW_TOKENS = 20000

LEAN_TOOLCHAIN = "leanprover/lean4:v4.26.0"
LEAN_PROJECT_DIR = os.path.join(os.path.dirname(__file__), "lean_project")

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")

LEAN_HEADER = """import Mathlib
import Aesop

set_option maxHeartbeats 400000

"""
