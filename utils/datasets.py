import json
import os

from huggingface_hub import HfApi, hf_hub_download

import utils.helpers as helpers


def update_dataset(data: list[dict], dataset_id: str, filename: str, hf_api_key: str) -> None:
    """
    Update a HF dataset.
    """
    # Filter data and then dump into a data.json file
    with open(filename, "w") as file:
        json.dump(data, file, indent=4)

    # Upload data.json to the HF dataset
    api = HfApi()
    api.upload_file(
        path_or_fileobj=filename, # the file to upload
        path_in_repo=filename, # where to upload it to
        repo_id=dataset_id,
        repo_type="dataset",
        commit_message="Update data.json 🤖",
        token=hf_api_key
    )
    helpers.log("Database updated!")


def load_dataset(dataset_id: str, filename: str, hf_api_key: str | None = None) -> list[dict]:
    """
    Load a HF dataset.
    """
    # Remove filename to ensure hf_hub_download raises an exception on fail
    try:
      os.remove(filename)
    except OSError:
      pass
    
    # Try to download and load the file
    try:
        hf_hub_download(
            filename=filename, # The file to download
            local_dir="", # Where to download it to
            repo_id=dataset_id,
            repo_type="dataset",
            token=hf_api_key
        )
        with open(filename) as file:
            dataset = json.load(file)
        return dataset

    except Exception as e:
        helpers.log("WARNING: dataset is empty or does not exist(?):", e)
        dataset = []

    return dataset