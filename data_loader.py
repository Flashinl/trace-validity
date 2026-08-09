from datasets import load_dataset
from torch.utils.data import DataLoader

from config import DATASET_NAME, DATASET_SPLIT, NUM_SAMPLES


class FormalStepDataset:
    def __init__(self, name=DATASET_NAME, split=DATASET_SPLIT, num_samples=NUM_SAMPLES):
        full_ds = load_dataset(name, split=split)
        self.dataset = full_ds.select(range(num_samples))

    def __len__(self):
        return len(self.dataset)

    def __getitem__(self, idx):
        item = self.dataset[idx]
        return item["problem"], item["ground_truth"]

    def get_dataloader(self, batch_size=1, shuffle=False):
        return DataLoader(self.dataset, batch_size=batch_size, shuffle=shuffle)
